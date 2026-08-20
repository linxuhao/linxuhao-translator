# ==========================================
# 文件名: app.py
# 架构定位: MCP Server - 暴露 ASR、OCR、网页搜索和网页抓取工具给 hermes-agent
#
# 支持三种输入方式:
# 1. REST 上传 (multipart/form-data): 上传文件获取 file_id (最高效)
# 2. URL: 直接传递公开 URL，mcp-server 下载并处理
# 3. base64: 直接传递 base64 编码的内容
#
# 统一端点 (端口 9003):
#   POST /upload/audio  - 上传音频 -> file_id
#   POST /upload/image - 上传图片 -> file_id
#   POST /upload/pdf    - 上传 PDF -> file_id
#   /mcp - MCP JSON-RPC 协议
#
# MCP 工具:
#   transcribe_audio(audio_base64?, audio_file_id?, audio_url?)
#   ocr_image(image_base64?, image_file_id?, image_url?)
#   ocr_pdf(pdf_base64?, pdf_file_id?, pdf_url?)
#   web_search(query, categories?, language?, time_range?, max_results?)
#   web_fetch(url, prompt?, max_length?, parse_media?)
# ==========================================
import asyncio
import io
import os
import time
import uuid
import base64

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, FileResponse
from fastmcp import FastMCP
from PIL import Image
from cachetools import LRUCache
import pdfplumber
from bs4 import BeautifulSoup

# ==========================================
# 配置
# ==========================================
VLLM_URL = os.getenv("VLLM_URL", "http://vllm_qwen:8000/v1/chat/completions")
ASR_URL = os.getenv("ASR_URL", "http://qwen3_asr:8000/v1/chat/completions")
ASR_MODEL = os.getenv("ASR_MODEL_NAME", "qwen3-asr")
HF_TOKEN = os.getenv("HF_TOKEN", "")

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://linxuhaserver:8888/search")

MEDIA_GEN_URL = os.getenv("MEDIA_GEN_URL", "http://media_gen:9010")
MEDIA_GEN_TIMEOUT = 600.0
GENERATED_DIR = os.getenv("GENERATED_DIR", "/generated")
GENERATED_HOST_DIR = os.getenv("GENERATED_HOST_DIR", "/home/linxuhao/vip-gateway/generated")

TIMEOUT = 60.0

# Image resize settings
MAX_IMAGE_PIXELS = 1700  
JPEG_QUALITY = 95
RESIZE_ENABLED = True  # True = resize if larger than MAX_IMAGE_PIXELS
PDF_PAGE_DPI = 300  # Render PDF pages at 300 DPI (1100x3000px - tested to work with vLLM)

# File storage: LRU cache, max 50 entries, auto-evicts least-recently-used
file_storage = LRUCache(maxsize=50)


# ==========================================
# MCP Server
# ==========================================
mcp = FastMCP(
    "asr-ocr-pdf-web-mcp",
    instructions=(
        "本服务器提供: ASR 语音转录、OCR 图片识别、PDF 文字提取、网页搜索、以及 AI 媒体生成 (文生图 + 文生音乐)。\n\n"
        "支持的格式:\n"
        "  Audio: webm, mp4, mp3, wav, ogg, flac, aac, m4a, opus 等 (FFmpeg 支持的全部)\n"
        "  Image: png, jpg/jpeg, gif, bmp, tiff, webp 等 (PIL 支持的全部)\n"
        "  PDF:   pdf\n\n"
        "【上传文件】不是 MCP tool，而是 REST HTTP 端点:\n"
        "  curl -X POST <MCP_URL>/upload/audio -F 'file=@audio.webm'   -> {\"file_id\": \"xxx\"}\n"
        "  curl -X POST <MCP_URL>/upload/image -F 'file=@image.png'   -> {\"file_id\": \"xxx\"}\n"
        "  curl -X POST <MCP_URL>/upload/pdf   -F 'file=@doc.pdf'     -> {\"file_id\": \"xxx\"}\n\n"
        "【媒体生成】generate_image / generate_music:\n"
        "  - 内部是异步任务, 提交后阻塞等待完成 (最长 ~30 分钟), 返回生成文件的下载 URL。\n"
        "  - 生成的文件通过 <MCP_URL>/files/{name} 下载 (name 取自返回的 file_url)。\n"
        "  - generate_image 支持图生图: 传 reference_image_file_id (先上传参考图) 或 reference_image_base64。\n"
        "  - generate_music 支持 duration (音频秒数, 最长 47) 和 num_inference_steps。\n\n"
        "MCP 工具:\n"
        "  transcribe_audio(audio_file_id='...')\n"
        "  ocr_image(image_file_id='...')\n"
        "  ocr_pdf(pdf_file_id='...')\n"
        "  web_search(query='...')\n"
        "  web_fetch(url='...', prompt='...', max_length=8000, parse_media=False)\n"
        "  generate_image(prompt='...', width?, height?, seed?, reference_image_file_id?)\n"
        "  generate_music(prompt='...', seed?, duration?, num_inference_steps?)\n"
    ),
)


def resize_image(img: Image.Image) -> Image.Image:
    if not RESIZE_ENABLED or MAX_IMAGE_PIXELS == 0:
        return img
    w, h = img.size
    longest = max(w, h)
    if longest <= MAX_IMAGE_PIXELS:
        return img
    ratio = MAX_IMAGE_PIXELS / longest
    new_w, new_h = int(w * ratio), int(h * ratio)
    return img.resize((new_w, new_h), Image.LANCZOS)


def image_to_jpeg_base64(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buffer.getvalue()).decode()


def get_audio_content(audio_data: bytes) -> list:
    b64 = base64.b64encode(audio_data).decode()
    return [{"type": "audio_url", "audio_url": {"url": f"data:audio/wav;base64,{b64}"}}]


def get_image_content(img: Image.Image) -> list:
    img = resize_image(img)
    img_b64 = image_to_jpeg_base64(img)
    return [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
        {"type": "text", "text": "Format and correct the following text. Fix any OCR errors using context from the image. Briefly describe any icons, logos, screenshots, or graphs visible."}
    ]


async def convert_to_wav(audio_bytes: bytes) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    stdout_data, _ = await proc.communicate(input=audio_bytes)
    if proc.returncode != 0:
        raise Exception(f"FFmpeg failed with code {proc.returncode}")
    return stdout_data


# ==========================================
# REST 上传端点 (custom_route)
# ==========================================

@mcp.custom_route("/upload/audio", methods=["POST"])
async def upload_audio(request: Request) -> JSONResponse:
    """上传音频文件，自动转换为 WAV，返回 file_id"""
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"error": "no file"}, status_code=400)
    content = await file.read()
    wav_data = await convert_to_wav(content)
    file_id = str(uuid.uuid4())
    file_storage[file_id] = wav_data
    return JSONResponse({"file_id": file_id, "size": len(wav_data)})


@mcp.custom_route("/upload/image", methods=["POST"])
async def upload_image(request: Request) -> JSONResponse:
    """上传图片文件，返回 file_id"""
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"error": "no file"}, status_code=400)
    content = await file.read()
    file_id = str(uuid.uuid4())
    file_storage[file_id] = content
    return JSONResponse({"file_id": file_id, "size": len(content)})


@mcp.custom_route("/upload/pdf", methods=["POST"])
async def upload_pdf(request: Request) -> JSONResponse:
    """上传 PDF 文件，返回 file_id"""
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"error": "no file"}, status_code=400)
    content = await file.read()
    file_id = str(uuid.uuid4())
    file_storage[file_id] = content
    return JSONResponse({"file_id": file_id, "size": len(content)})


@mcp.custom_route("/files/{filename}", methods=["GET"])
async def serve_generated(request: Request) -> FileResponse:
    """下载生成的文件 (图片/音乐), 供远程 agent 通过 URL 获取。"""
    filename = os.path.basename(request.path_params["filename"])  # 防目录穿越
    path = os.path.join(GENERATED_DIR, filename)
    if not os.path.exists(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


# ==========================================
# MCP 工具
# ==========================================

async def download_url(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def is_file_url(url: str) -> bool:
    return url.startswith("file://") or url.startswith("/") or url.startswith("data:")


async def call_asr(content: list) -> str:
    payload = {
        "model": ASR_MODEL,
        "messages": [{"role": "system", "content": "<<DISABLE_THINKING>>"}, {"role": "user", "content": content}],
        "max_tokens": 512,
        "temperature": 0.0
    }
    headers = {}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(ASR_URL, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


async def call_vllm(content: list, max_tokens: int = 2048) -> str:
    payload = {
        "model": "qwen3",
        "messages": [{"role": "system", "content": "<<DISABLE_THINKING>>"}, {"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0.1
    }
    headers = {}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.post(VLLM_URL, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


@mcp.tool()
async def transcribe_audio(audio_base64: str = None, audio_file_id: str = None, audio_url: str = None) -> str:
    """使用 Qwen3-ASR 转录音频。

    参数:
        audio_base64: base64 编码的音频
        audio_file_id: 通过 POST /upload/audio 上传后获得的 file_id
        audio_url: 音频文件的 URL (必须是可访问的公开 URL)

    优先使用 audio_file_id (最高效)，其次 audio_url，直传 base64 最后。

    高效工作流:
        1. POST /upload/audio (multipart/form-data, file 字段为 "file")
        2. 使用返回的 file_id 调用本工具
    """
    if audio_file_id and audio_file_id in file_storage:
        audio_data = file_storage[audio_file_id]
    elif audio_base64:
        audio_data = base64.b64decode(audio_base64)
    elif audio_url:
        if is_file_url(audio_url):
            return "错误: audio_url 不能是本地文件路径，请使用 audio_file_id 上传文件"
        audio_data = await download_url(audio_url)
    else:
        return "错误: 必须提供 audio_base64、audio_file_id 或 audio_url"

    wav_data = await convert_to_wav(audio_data)
    content = get_audio_content(wav_data)
    return await call_asr(content)


@mcp.tool()
async def ocr_image(image_base64: str = None, image_file_id: str = None, image_url: str = None) -> str:
    """使用 Qwen3.6-27B 提取图片中的文字并描述场景。

    参数:
        image_base64: base64 编码的图片
        image_file_id: 通过 POST /upload/image 上传后获得的 file_id
        image_url: 图片的 URL (必须是可访问的公开 URL)

    优先使用 image_file_id (最高效)，其次 image_url，直传 base64 最后。

    高效工作流:
        1. POST /upload/image (multipart/form-data, file 字段为 "file")
        2. 使用返回的 file_id 调用本工具
    """
    if image_file_id and image_file_id in file_storage:
        img = Image.open(io.BytesIO(file_storage[image_file_id]))
    elif image_base64:
        img_data = base64.b64decode(image_base64)
        img = Image.open(io.BytesIO(img_data))
    elif image_url:
        if is_file_url(image_url):
            return "错误: image_url 不能是本地文件路径，请使用 image_file_id 上传文件"
        img_data = await download_url(image_url)
        img = Image.open(io.BytesIO(img_data))
    else:
        return "错误: 必须提供 image_base64、image_file_id 或 image_url"

    img = resize_image(img)
    img_b64 = image_to_jpeg_base64(img)
    content = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
        {"type": "text", "text": "Format and correct the following text. Fix any OCR errors using context from the image. Briefly describe any icons, logos, screenshots, or graphs visible."}
    ]
    return await call_vllm(content)


@mcp.tool()
async def ocr_pdf(pdf_base64: str = None, pdf_file_id: str = None, pdf_url: str = None) -> str:
    """使用 Qwen3.6-27B 提取 PDF 中所有页面的文字。

    参数:
        pdf_base64: base64 编码的 PDF
        pdf_file_id: 通过 POST /upload/pdf 上传后获得的 file_id
        pdf_url: PDF 的 URL (必须是可访问的公开 URL)

    优先使用 pdf_file_id (最高效)，其次 pdf_url，直传 base64 最后。

    高效工作流:
        1. POST /upload/pdf (multipart/form-data, file 字段为 "file")
        2. 使用返回的 file_id 调用本工具
    """
    if pdf_file_id and pdf_file_id in file_storage:
        pdf_bytes = file_storage[pdf_file_id]
        pdf_file = io.BytesIO(pdf_bytes)
    elif pdf_base64:
        pdf_bytes = base64.b64decode(pdf_base64)
        pdf_file = io.BytesIO(pdf_bytes)
    elif pdf_url:
        if is_file_url(pdf_url):
            return "错误: pdf_url 不能是本地文件路径，请使用 pdf_file_id 上传文件"
        pdf_bytes = await download_url(pdf_url)
        pdf_file = io.BytesIO(pdf_bytes)
    else:
        return "错误: 必须提供 pdf_base64、pdf_file_id 或 pdf_url"

    with pdfplumber.open(pdf_file) as pdf:
        page_count = len(pdf.pages)
        results = []

        for page_num, page in enumerate(pdf.pages):
            native_text = page.extract_text() or ""
            img = page.to_image(PDF_PAGE_DPI).original
            img = resize_image(img)
            img_b64 = image_to_jpeg_base64(img)

            content = [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                {"type": "text", "text": f"Format and correct the following text from page {page_num + 1}/{page_count}. Fix any OCR errors using context from the image. Briefly describe any icons, logos, screenshots, or graphs visible."}
            ]
            ocr_text = await call_vllm(content, max_tokens=4096)

            results.append(
                f"=== Page {page_num + 1} ===\n"
                f"[PDF Parsed Text]:\n{native_text}\n\n"
                f"[OCR Text]:\n{ocr_text}"
            )

        return "\n\n".join(results)


@mcp.tool()
async def web_search(query: str, categories: str = None, language: str = None, time_range: str = None, max_results: int = 10) -> str:
    """使用 SearXNG 搜索网页。

    参数:
        query: 搜索关键词
        categories: 搜索类别，如 general, news, images, videos, science 等 (可选)
        language: 语言代码，如 zh, en, ja (可选)
        time_range: 时间范围，可选 day, week, month, year (可选)
        max_results: 返回结果数量上限 (默认 10)
    """
    params = {"q": query, "format": "json"}
    if categories:
        params["categories"] = categories
    if language:
        params["language"] = language
    if time_range:
        params["time_range"] = time_range

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(SEARXNG_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])[:max_results]
    if not results:
        return "未找到结果"

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        snippet = r.get("content", "")
        lines.append(f"{i}. [{title}]({url})\n   {snippet}")

    return "\n\n".join(lines)


@mcp.tool()
async def web_fetch(url: str, prompt: str = None, max_length: int = 8000, parse_media: bool = False) -> str:
    """抓取网页内容并提取纯文本。自动提取页面中的图片、音频、视频、PDF 等非文本资源 URL。
    可选通过 prompt 参数调用 Qwen3.6-27B 进行内容分析，或通过 parse_media 参数自动 OCR 图片+转录音频。

    参数:
        url: 要抓取的网页 URL
        prompt: 可选的分析提示。提供后会将提取的内容+媒体解析结果发给 Qwen3.6-27B 分析并返回分析结果。
               不提供则返回原始文本+媒体 URL 列表。
        max_length: 返回的最大文本长度 (默认 8000 字符，达到上限会截断并标记 [truncated])
        parse_media: 是否自动下载并解析页面中的非文本资源 (默认 False)。
                     True 时会并发处理最多 5 张图片 (Qwen3.6-27B vision OCR/描述) 和 3 个音频 (Qwen3-ASR 转录)。
                     图片/音频下载失败会自动跳过不报错。
                     False 时只在末尾列出媒体 URL，由调用方自行决定是否解析。

    四种输出模式:

    1. web_fetch(url) → 纯文本 + 媒体 URL 列表
       输出格式: Title + Description + 正文 + ## Media Found (Images/Audio/Videos/Documents)
       适用: 快速读取网页文字，知道有哪些图片/音频链接可用

    2. web_fetch(url, prompt="...") → LLM 分析结果
       将模式1的全部内容（含文本+媒体URL列表）交给 Qwen3.6-27B，按 prompt 要求分析
       适用: 快速总结文章、提取关键信息、翻译等

    3. web_fetch(url, parse_media=True) → 纯文本 + 媒体 URL 列表 + ## Parsed Media (每张图/音频的解析)
       适用: 完整理解页面所有内容（文字+图表+截图+音频）

    4. web_fetch(url, prompt="...", parse_media=True) → 全部内容 + 媒体解析 → LLM 分析
       适用: 最完整的页面理解，图文并茂地分析

    注意:
    - 非 HTML 内容 (JSON/XML/纯文本) 直接返回原始内容，不提取媒体
    - 媒体 URL 自动转为绝对路径
    - 每种类型最多列出 20 个 URL
    """
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; vip-gateway-mcp/1.0)"})
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        final_url = str(resp.url)  # After redirects

    if "text/html" in content_type:
        soup = BeautifulSoup(resp.text, "lxml")
        base_url = final_url

        # --- Text extraction ---
        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            meta_desc = meta_tag["content"].strip()

        # Remove non-content elements (before extracting media, so we don't get nav/footer images)
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe", "svg"]):
            tag.decompose()

        body = soup.body
        text = body.get_text(separator="\n") if body else soup.get_text(separator="\n")

        lines = (line.strip() for line in text.splitlines())
        text = "\n".join(line for line in lines if line)

        if len(text) > max_length:
            text = text[:max_length] + "\n... [truncated]"

        result = f"Title: {title or 'N/A'}\n"
        if meta_desc:
            result += f"Description: {meta_desc}\n"
        result += f"\n{text}"

        # --- Extract media URLs ---
        media_sections = _extract_media_urls(soup, base_url)

        if any(media_sections.values()):
            result += "\n\n## Media Found\n"
            for media_type, urls in media_sections.items():
                if urls:
                    result += f"\n### {media_type} ({len(urls)}):\n"
                    for u in urls[:20]:  # Cap at 20 per type
                        result += f"  - {u}\n"
                    if len(urls) > 20:
                        result += f"  ... and {len(urls) - 20} more\n"

        # --- Parse media ---
        if parse_media:
            media_results = await _parse_media_items(
                media_sections.get("Images", []),
                media_sections.get("Audio", []),
            )
            if media_results:
                result += "\n\n## Parsed Media\n"
                for r in media_results:
                    result += f"\n{r}"

    elif "text/" in content_type or "application/json" in content_type or "application/xml" in content_type:
        text = resp.text
        if len(text) > max_length:
            text = text[:max_length] + "\n... [truncated]"
        result = text
    else:
        return f"不支持的内容类型: {content_type}"

    # --- LLM analysis ---
    if prompt:
        content = [
            {"type": "text", "text": f"以下是从 {final_url} 抓取的内容:\n\n{result}\n\n---\n用户问题: {prompt}"}
        ]
        result = await call_vllm(content, max_tokens=2048)

    return result


def _save_generated(data: bytes, prefix: str, ext: str) -> str:
    """将生成结果写入共享卷, 返回宿主机绝对路径。"""
    os.makedirs(GENERATED_DIR, exist_ok=True)
    name = f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}"
    path = os.path.join(GENERATED_DIR, name)
    with open(path, "wb") as f:
        f.write(data)
    return os.path.join(GENERATED_HOST_DIR, name)


async def _submit_and_poll(payload: dict, timeout_s: int = 1800) -> dict:
    """提交生成任务并长轮询直到完成 (服务端阻塞)。返回 {"ok": bool, "file_url": str, "error": str}。"""
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(f"{MEDIA_GEN_URL}/v1/jobs", json=payload)
        r.raise_for_status()
        job_id = r.json()["job_id"]
        # 一次阻塞 GET (长轮询), 服务端阻塞到完成/失败/超时
        st = await client.get(f"{MEDIA_GEN_URL}/v1/jobs/{job_id}", params={"timeout": timeout_s})
        data = st.json()
    status = data.get("status")
    if status == "done":
        return {"ok": True, "file_url": data.get("file_url")}
    if status == "failed":
        return {"ok": False, "error": data.get("error", "unknown error")}
    return {"ok": False, "error": f"任务状态: {status}"}


@mcp.tool()
async def generate_image(prompt: str, width: int = 1024, height: int = 1024, seed: int = None,
                         reference_image_file_id: str = None, reference_image_base64: str = None) -> str:
    """使用 FLUX.2 Klein 4B 生成图片 (文生图/图生图), 保存为文件并返回下载 URL。

    参数:
        prompt: 图片描述 (英文效果最佳)
        width: 宽度 (上限 768, 超出会被 clamp)
        height: 高度 (上限 768, 超出会被 clamp)
        seed: 随机种子 (可选, 固定后结果可复现)
        reference_image_file_id: 参考图 file_id (先 POST /upload/image 上传获得), 用于图生图
        reference_image_base64: 参考图 base64 (可选, 与 file_id 二选一)

    返回: 生成文件的下载 URL (用 MCP 服务器 base URL + 该路径获取)
    """
    payload = {"type": "image", "prompt": prompt, "width": width, "height": height, "seed": seed}
    if reference_image_file_id and reference_image_file_id in file_storage:
        payload["image"] = base64.b64encode(file_storage[reference_image_file_id]).decode()
    elif reference_image_base64:
        payload["image"] = reference_image_base64
    result = await _submit_and_poll(payload)
    if not result["ok"]:
        return f"图片生成失败: {result['error']}"
    return f"图片已生成: {result['file_url']} (远程 agent 用 MCP 服务器 base URL + 此路径)"


@mcp.tool()
async def generate_music(prompt: str, seed: int = None, duration: float = 30.0, num_inference_steps: int = 100) -> str:
    """使用 Stable Audio Open 生成音乐, 保存为 WAV 文件并返回下载 URL。

    参数:
        prompt: 音乐描述 (风格/乐器/情绪, 英文效果最佳)
        seed: 随机种子 (可选, 固定后结果可复现)
        duration: 音频时长秒数 (最长 47 秒, 默认 30)
        num_inference_steps: 推理步数 (默认 100, 越多质量越好越慢)

    返回: 生成文件的下载 URL (用 MCP 服务器 base URL + 该路径获取)
    """
    payload = {"type": "music", "prompt": prompt, "seed": seed, "audio_end_in_s": duration, "num_inference_steps": num_inference_steps}
    result = await _submit_and_poll(payload)
    if not result["ok"]:
        return f"音乐生成失败: {result['error']}"
    return f"音乐已生成: {result['file_url']} (时长 {duration}s) (远程 agent 用 MCP 服务器 base URL + 此路径)"


def _abs_url(base_url: str, href: str) -> str:
    """Resolve relative URL against base."""
    from urllib.parse import urljoin
    return urljoin(base_url, href)


def _extract_media_urls(soup: BeautifulSoup, base_url: str) -> dict:
    """Extract image, audio, video, and document URLs from parsed HTML."""
    result: dict[str, list[str]] = {}

    # Images
    img_urls = []
    for img in soup.find_all("img"):
        src = img.get("src")
        if src:
            abs_url = _abs_url(base_url, src)
            if abs_url not in img_urls:
                img_urls.append(abs_url)
    if img_urls:
        result["Images"] = img_urls

    # Audio
    audio_urls = []
    for audio in soup.find_all("audio"):
        for src_tag in audio.find_all("source"):
            src = src_tag.get("src")
            if src:
                abs_url = _abs_url(base_url, src)
                if abs_url not in audio_urls:
                    audio_urls.append(abs_url)
        src = audio.get("src")
        if src:
            abs_url = _abs_url(base_url, src)
            if abs_url not in audio_urls:
                audio_urls.append(abs_url)
    if audio_urls:
        result["Audio"] = audio_urls

    # Video
    video_urls = []
    for video in soup.find_all("video"):
        for src_tag in video.find_all("source"):
            src = src_tag.get("src")
            if src:
                abs_url = _abs_url(base_url, src)
                if abs_url not in video_urls:
                    video_urls.append(abs_url)
        src = video.get("src")
        if src:
            abs_url = _abs_url(base_url, src)
            if abs_url not in video_urls:
                video_urls.append(abs_url)
    if video_urls:
        result["Videos"] = video_urls

    # Documents (PDF, DOC, etc.)
    doc_exts = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".epub", ".csv")
    doc_urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if any(href.lower().endswith(ext) or f".{ext}?" in href.lower() for ext in doc_exts):
            abs_url = _abs_url(base_url, href)
            if abs_url not in doc_urls:
                doc_urls.append(abs_url)
    if doc_urls:
        result["Documents"] = doc_urls

    return result


async def _parse_media_items(image_urls: list[str], audio_urls: list[str]) -> list[str]:
    """Download and OCR/transcribe media. Limits: 5 images, 3 audio."""
    import asyncio

    results = []

    # Parse images via vLLM vision
    async def ocr_one(img_url: str, idx: int) -> str | None:
        try:
            img_data = await download_url(img_url)
            img = Image.open(io.BytesIO(img_data))
            img = resize_image(img)
            img_b64 = image_to_jpeg_base64(img)
            content = [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                {"type": "text", "text": "Describe this image in one sentence, including any text visible in it."}
            ]
            desc = await call_vllm(content, max_tokens=256)
            return f"  [Image {idx}]({img_url}): {desc.strip()}"
        except Exception:
            return None

    # Transcribe audio via ASR
    async def asr_one(audio_url: str, idx: int) -> str | None:
        try:
            audio_data = await download_url(audio_url)
            wav_data = await convert_to_wav(audio_data)
            content = get_audio_content(wav_data)
            transcript = await call_asr(content)
            return f"  [Audio {idx}]({audio_url}): {transcript.strip()}"
        except Exception:
            return None

    # Run images (up to 5) and audio (up to 3) concurrently
    tasks = []
    for i, u in enumerate(image_urls[:5], 1):
        tasks.append(ocr_one(u, i))
    for i, u in enumerate(audio_urls[:3], 1):
        tasks.append(asr_one(u, i))

    gathered = await asyncio.gather(*tasks)
    for r in gathered:
        if r:
            results.append(r)

    return results


# ==========================================
# 启动服务器
# ==========================================
if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("vip-gateway-mcp Server")
    print("=" * 60)
    print()
    print("Endpoint: http://localhost:9003")
    print("  POST /upload/audio - 上传音频 -> file_id")
    print("  POST /upload/image - 上传图片 -> file_id")
    print("  POST /upload/pdf   - 上传 PDF -> file_id")
    print("  /mcp              - MCP JSON-RPC")
    print()
    print("MCP Tools:")
    print("  transcribe_audio(audio_base64?, audio_file_id?, audio_url?)")
    print("  ocr_image(image_base64?, image_file_id?, image_url?)")
    print("  ocr_pdf(pdf_base64?, pdf_file_id?, pdf_url?)")
    print("  web_search(query=..., categories=?, language=?, time_range=?, max_results=?)")
    print("  web_fetch(url=..., max_length=?)")
    print("  generate_image(prompt=..., width?, height?, seed?)")
    print("  generate_music(prompt=..., seed?)")
    print("=" * 60)

    uvicorn.run(mcp.http_app(), host="0.0.0.0", port=9003)