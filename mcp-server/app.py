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
#   gen_sfx(preset, seed?, base_freq?, wave?, overrides?)
# ==========================================
import asyncio
import io
import os
import uuid
import base64

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse
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
# 供 agent 下载文件的公开 URL (远程部署时指向模型机的 Tailscale IP)
MEDIA_GEN_PUBLIC_URL = os.getenv("MEDIA_GEN_PUBLIC_URL", MEDIA_GEN_URL)
MEDIA_GEN_TIMEOUT = 600.0

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
        "  - 生成的文件由 media-gen 服务提供下载 (URL 已含在返回结果里, 远程部署时 MEDIA_GEN_PUBLIC_URL 指向模型机的 Tailscale IP)。\n"
        "  - generate_image 支持图生图: 传 reference_image_file_id (先上传参考图) 或 reference_image_base64。\n"
        "  - generate_music 支持 duration (音频秒数, 最长 120) 和 num_inference_steps。\n  - generate_speech 是一次性旁白: voice 传一段声音描述, 但跨句音色会漂, 不适合同一个角色说多句。\n  - 游戏 NPC 对白用 create_actor 铸声一次 + actor_tts 说每一句, 音色才稳定。\n  - 同理: generate_image 每张外观会变。角色用 create_character、道具用 create_object 定妆一次,\n    之后一律 subject_image 出图 —— 否则一个宝箱换个角度就是另一个箱子。\n\n"
        "MCP 工具:\n"
        "  transcribe_audio(audio_file_id='...')\n"
        "  ocr_image(image_file_id='...')\n"
        "  ocr_pdf(pdf_file_id='...')\n"
        "  web_search(query='...')\n"
        "  web_fetch(url='...', prompt='...', max_length=8000, parse_media=False)\n"
        "  generate_image(prompt='...', width?, height?, seed?, reference_image_file_id?)\n"
        "  generate_music(prompt='...', seed?, duration?, num_inference_steps?)\n"
        "  generate_speech(text='...', voice='一段声音描述', seed?, speaking_rate?)  # 一次性旁白\n"
        "  create_actor(name='郭靖', voice='一段声音描述')  # 给角色铸声, 返回试音 URL, 先听\n"
        "  list_actors()\n"
        "  actor_tts(actor='郭靖', text='台词')  # 同一角色每句音色一致\n"
        "  create_character(name='郭靖', appearance='长相描述')  # 角色定妆, 返回定妆图 URL, 先看\n"
        "  create_object(name='宝箱', appearance='外观描述')      # 道具定妆, 换角度也不变样\n"
        "  list_subjects() / subject_image(subject='宝箱', scene='opened, from behind')\n"
        "  delete_actor(name) / delete_subject(name)  # 不可逆\n"
        "  remove_bg(image_url='...', mode?)  # 抠成真 RGBA (FLUX 画的棋盘格不是透明)\n"
        "  slice_sheet(image_url='...', rows=2, cols=2, trim?)  # 网格 sprite sheet 切单帧\n"
        "  vision_critique(prompt='...', image_url='...')  # 自定义提问的看图点评\n"
        "  gen_sfx(preset='jump', seed?)  # 程序化游戏音效 (sfxr 风格, 不用扩散模型)\n"
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


async def _submit_and_poll(payload: dict, timeout_s: int = 1800) -> dict:
    """提交生成任务并长轮询直到完成 (服务端阻塞)。返回 {"ok": bool, "file_url": str, "error": str}。"""
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(f"{MEDIA_GEN_URL}/v1/jobs", json=payload)
        if r.status_code >= 400:
            # 提交期的报错是写给调用方看的指令 (例如"先 create_actor 再说台词"),
            # raise_for_status 会把它吞成一个无信息的 HTTP 异常。
            try:
                msg = r.json().get("error") or r.text
            except Exception:
                msg = r.text
            return {"ok": False, "error": msg}
        job_id = r.json()["job_id"]
        # 一次阻塞 GET (长轮询), 服务端阻塞到完成/失败/超时
        st = await client.get(f"{MEDIA_GEN_URL}/v1/jobs/{job_id}", params={"timeout": timeout_s})
        data = st.json()
    status = data.get("status")
    if status == "done":
        return {"ok": True, **{k: v for k, v in data.items() if k != "status"}}
    if status == "failed":
        return {"ok": False, "error": data.get("error", "unknown error")}
    return {"ok": False, "error": f"任务状态: {status}"}


@mcp.tool()
async def generate_image(prompt: str, width: int = 1024, height: int = 1024, seed: int = None,
                         reference_image_file_id: str = None, reference_image_base64: str = None) -> str:
    """使用 FLUX.2 Klein 4B 生成图片 (文生图/图生图), 保存为文件并返回下载 URL。

    参数:
        prompt: 图片描述 (英文效果最佳)
        width: 宽度 (上限 1024, 超出会被 clamp)
        height: 高度 (上限 1024, 超出会被 clamp)
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
    return f"图片已生成: {MEDIA_GEN_PUBLIC_URL}{result['file_url']}"


@mcp.tool()
async def generate_music(prompt: str, seed: int = None, duration: float = 30.0, num_inference_steps: int = 100) -> str:
    """使用 Stable Audio Open 生成音乐, 保存为 WAV 文件并返回下载 URL。

    参数:
        prompt: 音乐描述 (风格/乐器/情绪, 英文效果最佳)
        seed: 随机种子 (可选, 固定后结果可复现)
        duration: 音频时长秒数 (最长 120 秒, 默认 30)
        num_inference_steps: 推理步数 (默认 100, 越多质量越好越慢)

    返回: 生成文件的下载 URL (用 MCP 服务器 base URL + 该路径获取)
    """
    payload = {"type": "music", "prompt": prompt, "seed": seed, "audio_end_in_s": duration, "num_inference_steps": num_inference_steps}
    result = await _submit_and_poll(payload)
    if not result["ok"]:
        return f"音乐生成失败: {result['error']}"
    return f"音乐已生成: {MEDIA_GEN_PUBLIC_URL}{result['file_url']} (时长 {duration}s)"


@mcp.tool()
async def generate_speech(text: str, voice: str = None, seed: int = None,
                          speaking_rate: float = None) -> str:
    """用 Qwen3-TTS VoiceDesign 合成人声对白, 保存为 WAV 并返回下载 URL。

    做游戏 NPC 对白用这个。它不是克隆某个真人的嗓子 —— 虚构角色没有录音 ——
    而是从一段"这个人听起来是什么样"的描述直接设计出声音, 所以 voice 参数
    写得越具体, 角色越像本人。同一段 voice 描述 + 同一个 seed 可复现,
    整部游戏里同一个 NPC 用同一组参数就能保持音色一致。

    参数:
        text: 要念的台词 (中/英/日/韩/德/法/俄/葡/西/意, 上限 600 字, 超出截断)
        voice: 声音的自然语言描述, 英文效果最佳。写年龄/性别/音色/语速/情绪,
               例如 "An elderly Chinese martial arts master, hoarse low voice,
               slow and deliberate" 或 "A cheerful young woman, bright and fast".
               不传则用中性旁白嗓。
        seed: 随机种子 (可选, 固定后结果可复现)
        speaking_rate: 语速倍率 (可选, 1.0 为原速)

    返回: 生成文件的下载 URL (24 kHz 单声道 WAV)
    """
    payload = {"type": "speech", "prompt": text, "instruct": voice, "seed": seed,
               "speaking_rate": speaking_rate}
    result = await _submit_and_poll(payload)
    if not result["ok"]:
        return f"语音生成失败: {result['error']}"
    return f"语音已生成: {MEDIA_GEN_PUBLIC_URL}{result['file_url']}"


@mcp.tool()
async def create_character(name: str, appearance: str, width: int = 512, height: int = 512,
                           seed: int = None, force: bool = False) -> str:
    """给一个角色定妆(生成并存下参考图), 之后 subject_image 出的每张图长相都一致。

    为什么要有这一步: generate_image 每次给的是"长得不一样的人"。同一个角色的头像 /
    战斗立绘 / 地图小人, 直接用文字描述生成出来是三个人。定妆一次, 之后每张场景图都
    带着参考图走图生图, 长相就和场景描述解耦了。(create_actor 钉音色, 这个钉长相。)

    重要: 定完先看返回的定妆图, 确认是不是你要的那个人。定砸了会把整个角色锁死在错的
    长相上, 之后每一张都错得很一致。不满意就 force=True 重定。

    参数:
        name: 角色名(字母/数字/下划线/连字符/中文, 1~40 字)
        appearance: 只写这个人长什么样(体型/脸/发型/衣着/配色), 不要写场景和动作
        width/height: 定妆图尺寸, 上限 1024
        seed / force: 同 create_actor

    返回: 定妆图 URL —— 先看再用
    """
    return await _pin_subject(name, appearance, "character", width, height, seed, force, "角色")


@mcp.tool()
async def create_object(name: str, appearance: str, width: int = 512, height: int = 512,
                        seed: int = None, force: bool = False) -> str:
    """给一件道具/物件定妆, 之后 subject_image 出的每张图它都长一个样。

    和 create_character 是同一套机制, 区别只在取景: 道具用四分之三视角(正投影看不出
    体积, 换个角度就没有可对齐的信息)。一个宝箱在地图上、打开时、从背面看, 如果每次
    都重新生成就是三个不同的箱子 —— 定妆一次就不会。

    参数:
        name: 物件名
        appearance: 只写它长什么样(材质/形状/配色/纹饰), 不要写场景和角度
        width/height / seed / force: 同 create_character

    返回: 定妆图 URL —— 先看再用
    """
    return await _pin_subject(name, appearance, "object", width, height, seed, force, "物件")


async def _pin_subject(name, appearance, kind, width, height, seed, force, label):
    r = await _submit_and_poll({"type": "subject_create", "subject": name, "kind": kind,
                                "prompt": appearance, "width": width, "height": height,
                                "seed": seed, "force": force})
    if not r["ok"]:
        return f"定妆失败: {r['error']}"
    return (f"{label} '{r.get('subject', name)}' 已定妆。"
            f"定妆图: {MEDIA_GEN_PUBLIC_URL}{r.get('reference_url')} —— "
            f"先看一眼确认是不是你要的, 不满意用 force=True 重定。")


@mcp.tool()
async def list_subjects() -> str:
    """列出已定妆的角色和物件。"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{MEDIA_GEN_URL}/v1/subjects")
    subs = r.json().get("subjects", [])
    if not subs:
        return "还没有定妆过的角色或物件。用 create_character / create_object 定一个。"
    return "\n".join(f"- [{c.get('kind')}] {c['name']}: {c['appearance']} (定于 {c['created']})"
                     for c in subs)


@mcp.tool()
async def subject_image(subject: str, scene: str, width: int = 512, height: int = 512,
                        seed: int = None) -> str:
    """让某个已定妆的角色或物件出一张新图, 外观与它之前每一张都一致。

    做游戏素材用这个, 不要用 generate_image —— 后者每张长相会变。
    subject 不存在会告诉你先去 create_character / create_object。

    参数:
        subject: 名字(定妆时定的)
        scene: 这张图里它在干什么 / 在哪 / 什么角度 —— 只写场景动作视角,
               外观由定妆图决定。例如 "opened, seen from behind, on a stone floor"
        width/height: 上限 1024
        seed: 随机种子(可选)

    返回: 生成文件的下载 URL
    """
    r = await _submit_and_poll({"type": "image", "subject": subject, "prompt": scene,
                                "width": width, "height": height, "seed": seed})
    if not r["ok"]:
        return f"出图失败: {r['error']}"
    return f"{subject} 的新图已生成: {MEDIA_GEN_PUBLIC_URL}{r['file_url']}"


@mcp.tool()
async def delete_subject(name: str) -> str:
    """删掉一个已定妆的角色或物件。不可逆: 定妆图不可复现, 重定出来是另一个。"""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.delete(f"{MEDIA_GEN_URL}/v1/subjects/{name}")
    d = r.json()
    return f"已删除 subject '{d['deleted']}'" if r.status_code < 400 else f"删除失败: {d.get('error')}"


@mcp.tool()
async def delete_actor(name: str) -> str:
    """删掉一个已铸声的角色。不可逆: 参考音不可复现, 重铸出来是另一个人。"""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.delete(f"{MEDIA_GEN_URL}/v1/actors/{name}")
    d = r.json()
    return f"已删除 actor '{d['deleted']}'" if r.status_code < 400 else f"删除失败: {d.get('error')}"


@mcp.tool()
async def create_actor(name: str, voice: str, sample_text: str = None,
                       seed: int = None, force: bool = False) -> str:
    """给一个角色铸声(定妆), 之后用 actor_tts 让他说任意台词都保持同一个音色。

    为什么要有这一步: generate_speech 的 voice 描述只圈定一个大致的音色区间,
    区间内每句台词各漂各的 —— 实测同 voice 同 seed 四句台词基频极差 125 Hz,
    关掉采样走贪心反而涨到 242 Hz(音色是文本的函数, 不是采样随机性, 锁 seed 或
    temperature 都锁不住)。本工具先用 voice 描述生成一段参考音, 之后所有台词
    改由克隆模型照着这段参考音说, 音色与台词内容无关。实测极差降到 5~52 Hz。

    重要: 铸完请先听 reference_url 那段试音, 确认是不是你要的那个人。铸砸了会把
    整个角色锁死在错的音色上, 而且它之后每一句都错得很一致。不满意就 force=True 重铸。

    参数:
        name: 角色名(字母/数字/下划线/连字符/中文, 1~40 字), 之后 actor_tts 用它指代
        voice: 声音的自然语言描述, 英文效果最佳。写年龄/性别/音色/语速/情绪,
               例如 "An elderly Chinese man, gravelly chest voice, commanding"
        sample_text: 铸声用的台词(可选)。默认用一段覆盖面较广的中文
        seed: 随机种子(可选)
        force: 覆盖已有角色。会让该角色之前所有台词的音色对不上, 慎用

    返回: 试音片段的 URL —— 先听再用
    """
    r = await _submit_and_poll({"type": "actor_create", "actor": name, "instruct": voice,
                                "prompt": sample_text or "", "seed": seed, "force": force})
    if not r["ok"]:
        return f"铸声失败: {r['error']}"
    return (f"角色 '{r.get('actor', name)}' 已铸声。"
            f"试音: {MEDIA_GEN_PUBLIC_URL}{r.get('reference_url')} "
            f"(念的是: {r.get('transcript')})。"
            f"先听一遍确认是不是你要的人, 不满意用 create_actor(..., force=True) 重铸。")


@mcp.tool()
async def list_actors() -> str:
    """列出已铸声的角色(名字 + 当初的声音描述 + 铸声时间)。"""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{MEDIA_GEN_URL}/v1/actors")
    actors = r.json().get("actors", [])
    if not actors:
        return "还没有角色。用 create_actor(name='...', voice='...') 铸一个。"
    return "\n".join(f"- {a['name']}: {a['voice']} (铸于 {a['created']})" for a in actors)


@mcp.tool()
async def actor_tts(actor: str, text: str, speaking_rate: float = None,
                    seed: int = None) -> str:
    """让某个已铸声的角色说一句台词, 音色与他之前每一句都一致。

    做游戏 NPC 对白用这个, 不要用 generate_speech —— 后者每句音色会漂。
    角色不存在会告诉你先去 create_actor。

    参数:
        actor: 角色名(create_actor 时定的)
        text: 台词, 上限 200 字(约 45 秒), 超出截断
        speaking_rate: 语速倍率(可选)
        seed: 随机种子(可选)

    返回: 生成文件的下载 URL (24 kHz 单声道 WAV)
    """
    r = await _submit_and_poll({"type": "speech", "actor": actor, "prompt": text,
                                "speaking_rate": speaking_rate, "seed": seed})
    if not r["ok"]:
        return f"配音失败: {r['error']}"
    return f"{actor} 的台词已生成: {MEDIA_GEN_PUBLIC_URL}{r['file_url']}"


async def _resolve_image_b64(image_base64, image_file_id, image_url):
    """把三种图片入参统一成 base64 (转发给 media-gen 用)。返回 (b64, 错误信息)。"""
    if image_file_id and image_file_id in file_storage:
        return base64.b64encode(file_storage[image_file_id]).decode(), None
    if image_url:
        if is_file_url(image_url):
            return None, "错误: image_url 不能是本地文件路径，请使用 image_file_id 上传文件"
        return base64.b64encode(await download_url(image_url)).decode(), None
    if image_base64:
        return image_base64, None
    return None, "错误: 必须提供 image_base64、image_file_id 或 image_url"


@mcp.tool()
async def remove_bg(image_base64: str = None, image_file_id: str = None, image_url: str = None,
                    mode: str = "auto", quality: str = "best") -> str:
    """抠掉图片背景, 输出真正带 alpha 通道的 RGBA PNG, 返回下载 URL。

    FLUX 生成不出 alpha: 你让它画"透明背景", 它是把 PS 那种灰白棋盘格当成不透明
    像素画出来的。做游戏精灵图必须用本工具把它转成真的 RGBA。

    参数:
        image_base64: base64 编码的图片
        image_file_id: 通过 POST /upload/image 上传后获得的 file_id
        image_url: 图片的 URL (必须是可访问的公开 URL, generate_image 返回的 URL 可直接用)
        mode: auto (默认, 按结构证据判断是不是棋盘格: 恰好两级灰度 + 周期方格; 不是就走
              通用抠图) / checker (强制只抠棋盘格) / rembg (强制通用显著物体抠图, CPU)
        quality: best (默认, birefnet-general-lite, ~6s, 边缘干净) / fast (u2netp, ~0.2s,
                 边缘会留一圈灰雾)。只影响 rembg 分支。

    优先使用 image_file_id (最高效)，其次 image_url，直传 base64 最后。

    返回: RGBA PNG 的下载 URL, 附带实际走的分支与透明像素占比。抠出来明显不对
    (几乎全透明 / 几乎没抠掉 / 碎成一堆小块) 时会附一行 ⚠️ 警告 —— 那种结果别直接用。
    """
    img_b64, err = await _resolve_image_b64(image_base64, image_file_id, image_url)
    if err:
        return err
    async with httpx.AsyncClient(timeout=MEDIA_GEN_TIMEOUT) as client:
        r = await client.post(f"{MEDIA_GEN_URL}/v1/remove_bg",
                              json={"image": img_b64, "mode": mode, "quality": quality})
    if r.status_code != 200:
        return f"抠图失败: {r.text[:300]}"
    data = r.json()
    branch = data.get("mode_used", mode)
    model = f"/{data['model']}" if data.get("model") else ""
    out = (f"背景已移除: {MEDIA_GEN_PUBLIC_URL}{data['file_url']} "
           f"(分支 {branch}{model}, 透明像素占比 {data['transparent_ratio']:.1%})")
    if data.get("warning"):
        out += f"\n⚠️ {data['warning']}"
    return out


@mcp.tool()
async def slice_sheet(image_base64: str = None, image_file_id: str = None, image_url: str = None,
                      rows: int = None, cols: int = None, frame_width: int = None,
                      frame_height: int = None, trim: bool = True) -> str:
    """把排成网格的 sprite sheet 切成单帧 PNG, 返回每一帧的下载 URL。

    让 FLUX 画"4 帧动画"时它会摆成 2x2 网格而不是 4 张图, 用本工具切开。

    参数:
        image_base64 / image_file_id / image_url: 同其它图片工具
        rows, cols: 网格行列数 (二者都给)
        frame_width, frame_height: 单帧像素尺寸 (与 rows+cols 二选一)
        trim: 是否把每帧裁到非透明/非背景的外接框 (默认 True)

    返回: 各帧 PNG 的下载 URL
    """
    img_b64, err = await _resolve_image_b64(image_base64, image_file_id, image_url)
    if err:
        return err
    payload = {"image": img_b64, "rows": rows, "cols": cols,
               "frame_width": frame_width, "frame_height": frame_height, "trim": trim}
    async with httpx.AsyncClient(timeout=MEDIA_GEN_TIMEOUT) as client:
        r = await client.post(f"{MEDIA_GEN_URL}/v1/slice_sheet", json=payload)
    if r.status_code != 200:
        return f"切图失败: {r.text[:300]}"
    urls = [f"{MEDIA_GEN_PUBLIC_URL}{u}" for u in r.json()["file_urls"]]
    return f"已切出 {len(urls)} 帧:\n" + "\n".join(urls)


@mcp.tool()
async def vision_critique(prompt: str, image_base64: str = None, image_file_id: str = None,
                          image_url: str = None, max_tokens: int = 2048) -> str:
    """用 Qwen3.6-27B 按你给的问题看图并作答 (画面点评/美术审查/构图判断)。

    与 ocr_image 的区别: ocr_image 的指令写死成"抄写并校正文字", 本工具由调用方
    自己出题, 适合把游戏截帧丢进来问"主体够不够醒目 / 对比度够不够 / UI 有没有挡住画面"。

    参数:
        prompt: 你要模型回答的问题 (英文效果最佳)
        image_base64: base64 编码的图片
        image_file_id: 通过 POST /upload/image 上传后获得的 file_id
        image_url: 图片的 URL (必须是可访问的公开 URL)
        max_tokens: 回答长度上限 (默认 2048)

    优先使用 image_file_id (最高效)，其次 image_url，直传 base64 最后。

    单图工具 (vLLM 上下文 12288)。要点评多帧就多调几次, 自己汇总。
    """
    if image_file_id and image_file_id in file_storage:
        img = Image.open(io.BytesIO(file_storage[image_file_id]))
    elif image_url:
        if is_file_url(image_url):
            return "错误: image_url 不能是本地文件路径，请使用 image_file_id 上传文件"
        img = Image.open(io.BytesIO(await download_url(image_url)))
    elif image_base64:
        img = Image.open(io.BytesIO(base64.b64decode(image_base64)))
    else:
        return "错误: 必须提供 image_base64、image_file_id 或 image_url"

    img_b64 = image_to_jpeg_base64(resize_image(img))
    content = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
        {"type": "text", "text": prompt},
    ]
    return await call_vllm(content, max_tokens=max_tokens)


@mcp.tool()
async def gen_sfx(preset: str = "select", seed: int = None, base_freq: float = None,
                  wave: str = None, overrides: dict = None) -> str:
    """合成一枚 sfxr/jsfxr 风格的游戏音效 (纯程序化, 不用模型), 返回 WAV 下载 URL。

    不要用 generate_music 做音效: 那是 Stable Audio 扩散模型, 出来的是几十秒的宽带
    糊音。游戏音效是 10~200ms 的瞬态, 要精确、即时、可复现 —— 本工具毫秒级出结果,
    同一个 seed 逐字节可复现。

    参数:
        preset: jump / coin / hit / explosion / powerup / laser / select / hurt
        seed: 随机种子。给了就在 preset 周围抖动参数 (不是抖采样点), 同 seed 结果完全相同;
              不给则严格使用 preset 的原始参数。
        base_freq: 覆盖基频 Hz (noise 波形下是采样保持的刷新率)
        wave: 覆盖波形 square / saw / sine / triangle / noise
        overrides: 覆盖任意合成参数的字典, 例如
                   {"freq_slide": -3.0, "release": 0.4, "lpf": 0.5, "duty": 0.25,
                    "vibrato_depth": 0.5, "arp_mult": 1.5, "arp_time": 0.06}
                   完整字段见 media-gen 的 GET /v1/sfx_presets

    返回: 44.1kHz 16bit 单声道 WAV 的下载 URL
    """
    ov = dict(overrides or {})
    if base_freq is not None:
        ov["base_freq"] = base_freq
    if wave is not None:
        ov["wave"] = wave
    payload = {"preset": preset, "seed": seed, "overrides": ov or None}
    async with httpx.AsyncClient(timeout=MEDIA_GEN_TIMEOUT) as client:
        r = await client.post(f"{MEDIA_GEN_URL}/v1/gen_sfx", json=payload)
    if r.status_code != 200:
        return f"音效合成失败: {r.text[:300]}"
    data = r.json()
    return (f"音效已生成: {MEDIA_GEN_PUBLIC_URL}{data['file_url']} "
            f"(preset {data['preset']}, seed {data['seed']}, 时长 {data['duration']:.3f}s, "
            f"波形 {data['params']['wave']}, 基频 {data['params']['base_freq']:.0f}Hz)")


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
    print("  remove_bg(image_base64?, image_file_id?, image_url?, mode?, quality?)")
    print("  slice_sheet(image_base64?, image_file_id?, image_url?, rows?, cols?, frame_width?, frame_height?, trim?)")
    print("  vision_critique(prompt=..., image_base64?, image_file_id?, image_url?, max_tokens?)")
    print("  gen_sfx(preset=..., seed?, base_freq?, wave?, overrides?)")
    print("=" * 60)

    uvicorn.run(mcp.http_app(), host="0.0.0.0", port=9003)