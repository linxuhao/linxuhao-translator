# ==========================================
# 文件名: app.py
# 架构定位: MCP Server - 暴露 ASR 和 OCR 工具给 Tailscale 网络上的 hermes-agent
#
# 支持三种输入方式:
# 1. REST 上传 (multipart/form-data): 上传文件获取 file_id (最高效)
# 2. URL: 直接传递公开 URL，mcp-server 下载并处理
# 3. base64: 直接传递 base64 编码的内容
#
# REST 端点:
#   POST /upload/audio  - 上传音频 -> file_id
#   POST /upload/image - 上传图片 -> file_id
#   POST /upload/pdf    - 上传 PDF -> file_id
#
# MCP 工具:
#   transcribe_audio(audio_base64?, audio_file_id?, audio_url?)
#   ocr_image(image_base64?, image_file_id?, image_url?)
#   ocr_pdf(pdf_base64?, pdf_file_id?, pdf_url?)
#
# MCP 端点: http://localhost:9003/mcp
# REST 端点: http://localhost:9004 (同一进程内)
# ==========================================
import asyncio
import io
import os
import uuid
import base64

import httpx
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from PIL import Image
from cachetools import LRUCache
import pdfplumber

# ==========================================
# vLLM Vision (GPU-accelerated, no pre-OCR)
# Pure vLLM at full resolution provides best OCR accuracy
# ==========================================

# ==========================================
# 配置
# ==========================================
VLLM_URL = os.getenv("VLLM_URL", "http://vllm_qwen:8000/v1/chat/completions")
ASR_URL = os.getenv("ASR_URL", "http://qwen3_asr:8000/v1/chat/completions")
ASR_MODEL = os.getenv("ASR_MODEL_NAME", "qwen3-asr")
HF_TOKEN = os.getenv("HF_TOKEN", "")

TIMEOUT = 60.0

# Image resize settings
MAX_IMAGE_PIXELS = 3000  # ~300 DPI equivalent (300 DPI × 10"), matches PDF page rendering
JPEG_QUALITY = 98
RESIZE_ENABLED = True  # True = resize if larger than MAX_IMAGE_PIXELS
PDF_PAGE_DPI = 300  # Render PDF pages at 300 DPI (1100x3000px - tested to work with vLLM)

# File storage: LRU cache, max 50 entries, auto-evicts least-recently-used
# Accessing a file_id moves it to most-recently-used position
file_storage = LRUCache(maxsize=50)

# ==========================================
# FastAPI 应用 (用于 REST 上传端点)
# ==========================================
upload_app = FastAPI(title="vip-gateway-mcp-upload")

upload_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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
    # Pure vLLM handles OCR + image description
    # No pre-OCR needed - vLLM vision at full resolution provides best accuracy
    return [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
        {"type": "text", "text": "Format and correct the following text. Fix any OCR errors using context from the image. Briefly describe any icons, logos, screenshots, or graphs visible."}
    ]


async def convert_to_wav(audio_bytes: bytes) -> bytes:
    """Convert audio to 16kHz mono WAV using FFmpeg"""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    stdout_data, _ = await proc.communicate(input=audio_bytes)
    if proc.returncode != 0:
        raise Exception(f"FFmpeg failed with code {proc.returncode}")
    return stdout_data


# ==========================================
# REST 上传端点
# ==========================================

@upload_app.post("/upload/audio")
async def upload_audio(file: UploadFile = File(...)) -> dict:
    """上传音频文件，自动转换为 WAV，返回 file_id"""
    content = await file.read()
    # Convert to WAV
    wav_data = await convert_to_wav(content)
    file_id = str(uuid.uuid4())
    file_storage[file_id] = wav_data
    return {"file_id": file_id, "size": len(wav_data)}


@upload_app.post("/upload/image")
async def upload_image(file: UploadFile = File(...)) -> dict:
    """上传图片文件，返回 file_id"""
    content = await file.read()
    file_id = str(uuid.uuid4())
    file_storage[file_id] = content
    return {"file_id": file_id, "size": len(content)}


@upload_app.post("/upload/pdf")
async def upload_pdf(file: UploadFile = File(...)) -> dict:
    """上传 PDF 文件，返回 file_id"""
    content = await file.read()
    file_id = str(uuid.uuid4())
    file_storage[file_id] = content
    return {"file_id": file_id, "size": len(content)}


# ==========================================
# MCP Server - ASR/OCR 工具 (Tailscale 私有网络)
# ==========================================
mcp = FastMCP("vip-gateway-mcp")


async def download_url(url: str) -> bytes:
    """Download content from URL and return bytes"""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


def is_file_url(url: str) -> bool:
    """Check if URL is a local file URL"""
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

    # All inputs must be converted to 16kHz mono WAV
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

    # Pure vLLM handles OCR + image description at full resolution
    img = resize_image(img)
    img_b64 = image_to_jpeg_base64(img)
    content = [
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
        {"type": "text", "text": "Format and correct the following text. Fix any OCR errors using context from the image. Briefly describe any icons, logos, screenshots, or graphs visible."}
    ]
    ocr_text = await call_vllm(content)

    return ocr_text


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
            # Get native text from PDF
            native_text = page.extract_text() or ""

            # Get full resolution image at high DPI for best quality
            img = page.to_image(PDF_PAGE_DPI).original
            img = resize_image(img)
            img_b64 = image_to_jpeg_base64(img)

            # Pure vLLM handles OCR + image description at full resolution
            # No pre-OCR needed - vLLM vision provides best accuracy
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


# ==========================================
# 启动服务器
# ==========================================
if __name__ == "__main__":
    import uvicorn
    from threading import Thread

    def run_upload_server():
        """启动 REST 上传服务器 (端口 9004)"""
        uvicorn.run(upload_app, host="0.0.0.0", port=9004, log_level="warning")

    # 在独立线程中启动 REST API
    upload_thread = Thread(target=run_upload_server, daemon=True)
    upload_thread.start()

    # 输出文档
    print("=" * 60)
    print("vip-gateway-mcp Server")
    print("=" * 60)
    print()
    print("MCP Endpoint:  http://localhost:9003/mcp")
    print("REST Upload:   http://localhost:9004")
    print()
    print("REST Upload Endpoints:")
    print("  POST /upload/audio - 上传音频文件 -> {file_id}")
    print("  POST /upload/image - 上传图片文件 -> {file_id}")
    print("  POST /upload/pdf   - 上传 PDF 文件 -> {file_id}")
    print()
    print("MCP Tools (support base64, file_id, or URL):")
    print("  transcribe_audio(audio_base64?, audio_file_id?, audio_url?)")
    print("  ocr_image(image_base64?, image_file_id?, image_url?)")
    print("  ocr_pdf(pdf_base64?, pdf_file_id?, pdf_url?)")
    print()
    print("推荐工作流:")
    print("  1. POST /upload/image -> {file_id}  (最高效)")
    print("  2. MCP tool call with image_file_id")
    print()
    print("或使用 URL (mcp-server 会下载并处理):")
    print("  MCP tool call with image_url/audio_url/pdf_url")
    print("=" * 60)

    # 启动 MCP 服务器
    mcp.run(transport="streamable-http", host="0.0.0.0", port=9003)