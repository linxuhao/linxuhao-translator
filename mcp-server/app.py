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
import re
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

# ---- vision_critique 的上下文预算 ----
# vLLM 自己报的有效上下文, 不是 --max-model-len 那个参数 (它会被模型 config 压小)。
# 出处: docker logs vllm_qwen -> "[model.py:1680] Using max model len 12288"
#       (引擎配置行里同一个数写作 max_seq_len=12288)。换模型了就照着新日志改。
VLLM_CONTEXT_TOKENS = int(os.getenv("VLLM_CONTEXT_TOKENS", "12288"))
# Qwen3-VL 把图切成 16x16 patch 再 2x2 合并 —— 即每 32x32 像素 1 个 token, 外加 3 个
# 包裹 token; 边长先按 32 四舍五入 (processor 的 smart_resize 就是这么算的)。
# 2026-08-22 对 qwen3 (sokada4/Qwen3.8-27B-GPTQ-Int4) 实测逐个吻合, 且多图严格相加:
#   960x704 -> 663   640x480 -> 303   320x240 -> 83   1280x960 -> 1203
VISION_PATCH_PX = 32
VISION_WRAP_TOKENS = 3
VISION_MIN_PATCHES = 4       # 极小的图会被 processor 的 min_pixels 顶上来
CHAT_OVERHEAD_TOKENS = 29    # 实测: 纯文本 "hi" 一次请求的 prompt_tokens
VISION_SAFETY_TOKENS = 64    # 文本 token 估算误差的余量

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
        "  create_animal(name='神雕', appearance='外观描述')      # 动物定妆\n"
        "  create_object(name='宝箱', appearance='外观描述')      # 道具定妆; 务必写死几何(盖子平/拱, 边角方/圆)\n"
        "  list_subjects() / subject_image(subject='宝箱', scene='opened, from behind')\n"
        "  delete_actor(name) / delete_subject(name)  # 不可逆\n"
        "  remove_bg(image_url='...', mode?)  # 抠成真 RGBA (FLUX 画的棋盘格不是透明)\n"
        "  slice_sheet(image_url='...', rows=2, cols=2, trim?)  # 网格 sprite sheet 切单帧\n"
        "  vision_critique(prompt='...', image_url='...')  # 自定义提问的看图点评\n"
        "    三个图片参数都兼收数组: 一次按顺序送多帧进去, 直接问差分问题 (这几帧之间 X 变没变)\n"
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
    """上传音频，原样存下，返回 file_id。

    这里刻意不转码。原先上传时就转成 16 kHz 单声道 (ASR 的规格) 并只存转码后的结果,
    有两个后果:
      - 对 ASR 是白做的 —— transcribe_audio 本来就会再调一次 convert_to_wav。
      - 对 import_actor 是有损的 —— 克隆参考音要 24 kHz, 而拿到的已经是 16 kHz,
        media-gen 再从 16k 升到 24k 也补不回被丢掉的那个倍频程。而它会"导入成功"、
        报一个像模像样的格式, 只是音色比你上传的那份闷。
    各自需要什么格式, 由各自去转。
    """
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"error": "no file"}, status_code=400)
    content = await file.read()
    file_id = str(uuid.uuid4())
    file_storage[file_id] = content
    return JSONResponse({"file_id": file_id, "size": len(content)})


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
        raw = resp.json()["choices"][0]["message"]["content"].strip()

    # Qwen3-ASR 的原生输出带一层信封: "language Chinese<asr_text>正文"。
    # 走 /v1/audio/transcriptions 时 vLLM 会自己剥 (qwen3_asr.py:post_process_output),
    # 但我们走的是 chat/completions —— 那条路径原样透传, 所以得自己剥。
    # gateway 的 translation.py / record.py / tutor.py 三个调用方都剥了, 只有这里漏了,
    # 于是 transcribe_audio 一直把 "language Chinese<asr_text>您好…" 整条返给调用方。
    match = re.match(r"^\s*language\s+([A-Za-z]+)\s*<asr_text>\s*(.*)",
                     raw, re.IGNORECASE | re.DOTALL)
    return match.group(2).strip() if match else raw


async def call_vllm(content: list, max_tokens: int = 2048, timeout: float = TIMEOUT) -> str:
    payload = {
        "model": "qwen3",
        "messages": [{"role": "system", "content": "<<DISABLE_THINKING>>"}, {"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0.1
    }
    headers = {}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"

    async with httpx.AsyncClient(timeout=timeout) as client:
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
    """给一个人物定妆(生成并存下参考图), 之后 subject_image 出的每张图长相都一致。

    为什么要有这一步: generate_image 每次给的是"长得不一样的人"。同一个角色的头像 /
    战斗立绘 / 地图小人, 直接用文字描述生成出来是三个人。

    appearance 分两部分, 分清楚很重要:

    (1) 身份 —— 必须写死, 漏掉的每一项模型都会自己编, 而且每张编得不一样:
      - 年龄段 + 体型(高瘦/魁梧/矮壮)
      - 脸: 脸型、显著特征(疤/须/眉眼)
      - 发型 + 发色 + 束发方式
      - 辨识物: 跟着这个人走、换装也不摘的东西(独眼罩/佩剑/护腕/胎记)

    (2) 默认服装 —— 只是个基线, 不是身份的一部分。照样写进 appearance,
        但 subject_image 的 scene 里写新衣服就能换掉(实测: 定妆穿布袍, scene 写
        "wearing heavy red armor" 能换成甲胄而脸不变)。所以一个角色不需要按套装
        定妆很多次。

    不要写场景、动作、表情 —— 那些留给 subject_image 的 scene。

    定完先看返回的定妆图确认是不是你要的人; 定砸了会把整个角色锁死在错的长相上,
    不满意就 force=True 重定。
    """
    return await _pin_subject(name, appearance, "character", width, height, seed, force, "人物")


@mcp.tool()
async def create_animal(name: str, appearance: str, width: int = 512, height: int = 512,
                        seed: int = None, force: bool = False) -> str:
    """给一只动物/坐骑/灵兽定妆, 之后每张图它都是同一只。

    appearance 里必须写死这几样:
      - 物种 + 体型比例(腿长/身长/头身比)
      - 毛色/羽色 + 花纹的分布位置(不是只说"有斑点", 要说斑点在哪)
      - 耳朵、尾巴、翅膀的形状
      - 显著特征(独角/断尾/眼色)
    鞍具、缰绳这类可穿卸的东西和人物的服装同理: 写进 appearance 只是默认值,
    scene 里可以换掉。不要写场景和动作。

    定完先看定妆图, 不满意 force=True 重定。
    """
    return await _pin_subject(name, appearance, "animal", width, height, seed, force, "动物")


@mcp.tool()
async def create_object(name: str, appearance: str, width: int = 512, height: int = 512,
                        seed: int = None, force: bool = False) -> str:
    """给一件道具/物件定妆, 之后每张图它都长一个样, 换角度也不变。

    物件最容易漂的是**几何**, 不是材质配色 —— 实测一个宝箱, 材质配色五金件都对得上,
    盖子却一会儿是平的方的、一会儿是拱的圆的, 因为原始描述里压根没写盖子什么形状。

    appearance 里必须写死这几样:
      - 整体轮廓 + 比例(长方/立方/圆桶, 宽高比)
      - 关键几何: 盖子平的还是拱的、边角方的还是圆的、侧面直的还是弧的、有没有底座
      - 材质 + 主次配色
      - 五金件/纹饰及其位置(锁扣、包角、铆钉在哪)
    不要写场景和角度 —— 角度留给 subject_image 的 scene。

    定完先看定妆图, 不满意 force=True 重定。
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
               身份由定妆图决定。例如 "opened, seen from behind, on a stone floor"。
               人物/动物还可以在这里换装: "wearing heavy red armor" 会换掉定妆图
               里那身衣服而保住脸。
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
    warn = f"\n⚠️ {r['warning']}" if r.get("warning") else ""
    return (f"角色 '{r.get('actor', name)}' 已铸声 (参考音 {r.get('ref_seconds')}s)。"
            f"试音: {MEDIA_GEN_PUBLIC_URL}{r.get('reference_url')} "
            f"(念的是: {r.get('transcript')})。"
            f"先听一遍确认是不是你要的人, 不满意用 create_actor(..., force=True) 重铸。{warn}")


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



async def _resolve_audio_bytes(audio_base64, audio_file_id, audio_url):
    """把三种音频入参统一成 16-bit PCM WAV 字节。非 WAV 用 ffmpeg 转成 24k 单声道。"""
    if audio_file_id and audio_file_id in file_storage:
        data = file_storage[audio_file_id]
    elif audio_url:
        if is_file_url(audio_url):
            return None, "错误: audio_url 不能是本地文件路径，请先 POST /upload/audio 上传"
        data = await download_url(audio_url)
    elif audio_base64:
        data = base64.b64decode(audio_base64)
    else:
        return None, "错误: 必须提供 audio_file_id、audio_url 或 audio_base64"
    if data[:4] == b"RIFF":
        return data, None
    # 不是 WAV 就交给 ffmpeg。参考音要 24 kHz 单声道 —— 和克隆模型的规格一致
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", "pipe:0", "-ar", "24000", "-ac", "1",
            "-acodec", "pcm_s16le", "-f", "wav", "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        out, _ = await proc.communicate(input=data)
        if proc.returncode != 0 or not out:
            return None, "错误: 这段音频 ffmpeg 解不开，换个格式试试 (wav/mp3/m4a/ogg/flac)"
        return out, None
    except FileNotFoundError:
        return None, "错误: 服务器上没有 ffmpeg，请直接提供 16-bit PCM WAV"


@mcp.tool()
async def import_actor(name: str, transcript: str, audio_base64: str = None,
                       audio_file_id: str = None, audio_url: str = None,
                       force: bool = False) -> str:
    """用一段现成的录音铸声 —— 声音是别处做的(真人录音 / 其它 TTS)也照样能保持一致。

    和 create_actor 得到的东西完全一样, 只是参考音由你提供而不是我们生成。之后
    actor_tts 让他说任意台词, 音色都来自这段录音。

    参数:
        name: 角色名, 之后 actor_tts 用它指代
        transcript: 那段录音里念的是什么 —— 必填。克隆模型要拿它对齐音频和文字,
                    写错了音色会明显不对。
        audio_file_id: 通过 POST /upload/audio 上传后获得的 file_id (推荐)
        audio_url: 音频的公开 URL
        audio_base64: 或者直接给 base64
        force: 覆盖已有角色

    录音要求: 2~30 秒, 单人干净人声最好(没有背景音乐和混响)。wav/mp3/m4a/ogg/flac
    都行, 服务端会转成 24 kHz 单声道。

    注意: 你有权使用这段声音才导入它。克隆一个真人的嗓子在很多地方需要本人同意。
    """
    data, err = await _resolve_audio_bytes(audio_base64, audio_file_id, audio_url)
    if err:
        return err
    lowband = None
    try:
        import wave as _w, io as _io
        with _w.open(_io.BytesIO(data)) as _f:
            if _f.getframerate() < 24000:
                lowband = _f.getframerate()
    except Exception:
        pass
    payload = {"actor": name, "audio": base64.b64encode(data).decode(),
               "transcript": transcript, "force": force}
    async with httpx.AsyncClient(timeout=MEDIA_GEN_TIMEOUT) as client:
        r = await client.post(f"{MEDIA_GEN_URL}/v1/actors/import", json=payload)
    d = r.json()
    if r.status_code >= 400:
        return f"导入失败: {d.get('error', r.text[:300])}"
    warn = (f"\n⚠️ 这段录音只有 {lowband} Hz, 低于克隆用的 24 kHz。升采样补不回丢掉的高频, "
            f"音色会比原声闷。有更高采样率的原始文件就换那个。") if lowband else ""
    return (f"角色 '{d['actor']}' 已从录音铸声 ({d['source_format']})。"
            f"参考音: {MEDIA_GEN_PUBLIC_URL}{d['reference_url']} —— "
            f"先用 actor_tts 试一句, 确认克隆出来的音色对不对。{warn}")


@mcp.tool()
async def import_subject(name: str, appearance: str, kind: str = "character",
                         image_base64: str = None, image_file_id: str = None,
                         image_url: str = None, force: bool = False) -> str:
    """用一张现成的图定妆 —— 角色/物件是别处画的也照样能保持一致。

    和 create_character / create_animal / create_object 得到的东西完全一样, 只是定妆图
    由你提供。之后 subject_image 让它出任意场景图, 外观都来自这张图。

    参数:
        name: 名字, 之后 subject_image 用它指代
        appearance: 这是什么的文字描述 —— 必填, 它会被拼进之后每一张场景图的提示词。
                    只给参考图而不给描述, 模型对"这是什么"没有着落, 外观照样会漂。
                    写法同 create_character / create_animal / create_object 的要求。
        kind: character / animal / object (只影响它被当成哪类东西记录)
        image_file_id / image_url / image_base64: 同其它图片工具
        force: 覆盖已有的

    参考图要求和我们自己生成的定妆图一样: 单个主体、正面或四分之三视角、背景干净、
    看得全。一张有场景有动作的插画当参考图, 场景会跟着一起被复制到每张图里。
    大图会缩到 1024 以内; 带透明通道的图会转成 RGB(透明区交给引擎会变成黑块)。
    """
    img_b64, err = await _resolve_image_b64(image_base64, image_file_id, image_url)
    if err:
        return err
    payload = {"subject": name, "image": img_b64, "appearance": appearance,
               "kind": kind, "force": force}
    async with httpx.AsyncClient(timeout=MEDIA_GEN_TIMEOUT) as client:
        r = await client.post(f"{MEDIA_GEN_URL}/v1/subjects/import", json=payload)
    d = r.json()
    if r.status_code >= 400:
        return f"导入失败: {d.get('error', r.text[:300])}"
    size = (f"原图 {d['source_size']} → 存为 {d['stored_size']}"
            if d.get("resized") else d["source_size"])
    return (f"{d['kind']} '{d['subject']}' 已用现成图定妆 ({size})。"
            f"定妆图: {MEDIA_GEN_PUBLIC_URL}{d['reference_url']} —— "
            f"先用 subject_image 出一张试试, 确认外观跟得住。")


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


def _as_str_list(value) -> list:
    """图片入参既收单个字符串, 也收字符串数组, 统一成 list。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [v for v in value if v]


def _image_token_cost(img: Image.Image) -> int:
    """一张 (已 resize 过的) 图在 vLLM 里占多少 prompt token。

    边长按 VISION_PATCH_PX 四舍五入成格子数, 乘起来就是图像 token 数, 再加包裹 token。
    """
    w, h = img.size
    cols = max(1, round(w / VISION_PATCH_PX))
    rows = max(1, round(h / VISION_PATCH_PX))
    return max(cols * rows, VISION_MIN_PATCHES) + VISION_WRAP_TOKENS


def _text_token_estimate(text: str) -> int:
    """保守估算文本 token 数: CJK 一字一个, 其余 3 个字符算一个。"""
    cjk = sum(1 for ch in text if "\u3400" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff")
    return cjk + -(-(len(text) - cjk) // 3)


def _vision_budget_error(costs: list, text_tokens: int, max_tokens: int):
    """超预算就返回一段错误文本, 没超返回 None。

    宁可报错也不截断: 少看了几帧还照样自信给结论的点评, 比不点评更糟。
    """
    fixed = CHAT_OVERHEAD_TOKENS + text_tokens + max_tokens + VISION_SAFETY_TOKENS
    total = fixed + sum(costs)
    if total <= VLLM_CONTEXT_TOKENS:
        return None
    room = VLLM_CONTEXT_TOKENS - fixed
    fits = used = 0
    for c in costs:
        if used + c > room:
            break
        used += c
        fits += 1
    per = "/".join(str(c) for c in costs[:8]) + ("/..." if len(costs) > 8 else "")
    lines = [
        "错误: 超出 vLLM 上下文预算, 已中止 —— 没有丢掉任何一张图, 也没有让服务端截断。",
        f"  上下文上限 {VLLM_CONTEXT_TOKENS} token",
        f"  本次请求 ≈ {total} = 图 {len(costs)} 张 {sum(costs)} (每张 {per})"
        f" + prompt {text_tokens} + max_tokens {max_tokens}"
        f" + 固定开销 {CHAT_OVERHEAD_TOKENS} + 余量 {VISION_SAFETY_TOKENS}",
    ]
    if fits == 0:
        lines.append(f"  按当前 prompt 和 max_tokens={max_tokens}, 一张都放不下。")
    else:
        lines.append(f"  按当前 prompt 和 max_tokens={max_tokens}, 最多放得下 {fits} 张"
                     f" (即按给定顺序的前 {fits} 张)。")
    lines.append("  要看更多帧: 分批调用, 或调小 max_tokens, 或把图缩小 (每 32x32 像素 1 token)。")
    return "\n".join(lines)


@mcp.tool()
async def vision_critique(prompt: str,
                          image_base64: str | list[str] = None,
                          image_file_id: str | list[str] = None,
                          image_url: str | list[str] = None,
                          max_tokens: int = 2048) -> str:
    """用 Qwen3.8-27B 按你给的问题看图并作答; 可以一次给多张图 (画面点评/美术审查/多帧对比)。

    与 ocr_image 的区别: ocr_image 的指令写死成"抄写并校正文字", 本工具由调用方
    自己出题, 适合把游戏截帧丢进来问"主体够不够醒目 / 对比度够不够 / UI 有没有挡住画面"。

    【多图】image_base64 / image_file_id / image_url 三个参数既收单个字符串, 也收字符串
    数组。给数组时, 多张图**按数组给定的顺序**一起送进同一次对话 (每张前面标上
    "Image i of N"), 所以可以直接问差分问题 —— 这才是多图的用处:
      "这几帧之间血条变没变?"、"角色是从第几帧开始走出屏幕的?"、"哪一帧的构图最差?"
    不用一张一张调完再自己汇总 —— 那样模型根本看不到帧与帧的差别。

    参数:
        prompt: 你要模型回答的问题 (英文效果最佳)
        image_base64: base64 编码的图片, 或 base64 数组
        image_file_id: 通过 POST /upload/image 上传后获得的 file_id, 或 file_id 数组
        image_url: 图片的 URL (必须是可访问的公开 URL), 或 URL 数组
        max_tokens: 回答长度上限 (默认 2048); 它也要占上下文预算

    优先使用 image_file_id (最高效)，其次 image_url，直传 base64 最后。
    三者只取一种 (按这个优先级), 不会把三个参数里的图拼在一起。

    【预算】vLLM 上下文 12288 token。一张图 ≈ 每 32x32 像素 1 token: 960x704 的游戏
    截帧 = 663 token/张, 默认 max_tokens=2048 时大约放得下 15 张; 图越大放得越少
    (长边超过 1700 px 会先被缩到 1700)。超预算直接报错并告诉你放得下几张 ——
    绝不悄悄丢图, 也不让服务端截断。
    """
    file_ids = _as_str_list(image_file_id)
    urls = _as_str_list(image_url)
    b64s = _as_str_list(image_base64)

    if file_ids and all(f in file_storage for f in file_ids):
        raws = [file_storage[f] for f in file_ids]
    elif urls:
        if any(is_file_url(u) for u in urls):
            return "错误: image_url 不能是本地文件路径，请使用 image_file_id 上传文件"
        raws = [await download_url(u) for u in urls]
    elif b64s:
        raws = [base64.b64decode(b) for b in b64s]
    elif file_ids:
        missing = ", ".join(f for f in file_ids if f not in file_storage)
        return (f"错误: 这些 image_file_id 不存在或已被 LRU 淘汰: {missing}。"
                "请重新 POST /upload/image 上传。")
    else:
        return "错误: 必须提供 image_base64、image_file_id 或 image_url"

    imgs = [resize_image(Image.open(io.BytesIO(raw))) for raw in raws]
    n = len(imgs)

    content, texts = [], []
    for i, img in enumerate(imgs, 1):
        if n > 1:
            label = f"Image {i} of {n}:"
            content.append({"type": "text", "text": label})
            texts.append(label)
        img_b64 = image_to_jpeg_base64(img)
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}})
    content.append({"type": "text", "text": prompt})
    texts.append(prompt)

    err = _vision_budget_error([_image_token_cost(im) for im in imgs],
                               _text_token_estimate("\n".join(texts)), max_tokens)
    if err:
        return err

    # 多图 prefill 更长, 超时按张数放宽
    return await call_vllm(content, max_tokens=max_tokens, timeout=TIMEOUT + 20.0 * (n - 1))


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
    print("  vision_critique(prompt=..., image_base64?, image_file_id?, image_url?, max_tokens?)"
          "  # 三个图片参数均可传单个或数组")
    print("  gen_sfx(preset=..., seed?, base_freq?, wave?, overrides?)")
    print("=" * 60)

    uvicorn.run(mcp.http_app(), host="0.0.0.0", port=9003)