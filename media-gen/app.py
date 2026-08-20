# ==========================================
# 文件名: media-gen/app.py
# 架构定位: GPU 1 (7800 XT) 媒体生成服务 (异步 job API)
#   - POST /v1/jobs         提交任务 -> job_id (不阻塞)
#   - GET  /v1/jobs/{id}    轮询状态 queued/running/done/failed
#   - 生成结果写入 /generated, 由 mcp-server 的 /files/{name} 提供下载
#
# 模型懒加载 + 互斥常驻 + 单 worker 串行 (16GB 只装得下一个模型)
# ==========================================
import io
import os
import uuid
import time
import queue
import asyncio
import base64
import threading
import logging

import numpy as np
import torch
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from PIL import Image

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("media-gen")

app = FastAPI(title="media-gen", version="0.2.0")

# ---- 配置 ----
MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", "768"))
GENERATED_DIR = os.getenv("GENERATED_DIR", "/generated")

# ---- 模型懒加载 (互斥常驻) ----
_LOCK = threading.Lock()
_t2i = {}
_t2m = {}


def _free_t2m():
    _t2m.clear()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _free_t2i():
    _t2i.clear()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def get_t2i():
    if "pipe" not in _t2i:
        with _LOCK:
            if "pipe" not in _t2i:
                _free_t2m()
                from diffusers import Flux2KleinPipeline
                log.info("loading FLUX.2-klein-4B ...")
                pipe = Flux2KleinPipeline.from_pretrained(
                    "black-forest-labs/FLUX.2-klein-4B",
                    torch_dtype=torch.bfloat16,
                )
                # 文本编码器 + VAE 卸载到 CPU, 仅 transformer 常驻 GPU (适配 16GB 卡)
                pipe.enable_model_cpu_offload()
                try:
                    pipe.enable_vae_slicing()
                    pipe.enable_vae_tiling()
                except Exception:
                    pass
                _t2i["pipe"] = pipe
                log.info("FLUX.2-klein-4B loaded")
    return _t2i["pipe"]


def get_t2m():
    if "pipe" not in _t2m:
        with _LOCK:
            if "pipe" not in _t2m:
                _free_t2i()
                from diffusers import StableAudioPipeline
                log.info("loading stable-audio-open-1.0 ...")
                pipe = StableAudioPipeline.from_pretrained(
                    "stabilityai/stable-audio-open-1.0",
                    torch_dtype=torch.float16,
                )
                # AMD torchsde 布朗树递归 bug workaround: 换确定性 EDM scheduler (不用 torchsde)
                from diffusers import EDMDPMSolverMultistepScheduler
                pipe.scheduler = EDMDPMSolverMultistepScheduler.from_config(
                    pipe.scheduler.config, algorithm_type="dpmsolver++"
                )
                pipe.to("cuda")
                _t2m["pipe"] = pipe
                log.info("stable-audio-open-1.0 loaded")
    return _t2m["pipe"]


# ---- 工具函数 ----
def _make_generator(seed):
    gen = torch.Generator(device="cuda")
    if seed is not None:
        gen = gen.manual_seed(seed)
    return gen


def _get_sample_rate(pipe, out):
    for src in (out, pipe, getattr(pipe, "scheduler", None), getattr(pipe, "vae", None)):
        for attr in ("sample_rate", "sampling_rate"):
            v = getattr(src, attr, None)
            if v:
                return int(v)
        cfg = getattr(src, "config", None)
        if isinstance(cfg, dict):
            for k in ("sample_rate", "sampling_rate"):
                if cfg.get(k):
                    return int(cfg[k])
    return 44100


def _to_wav(audio: np.ndarray, sr: int) -> bytes:
    import wave
    data = np.asarray(audio)
    if data.ndim == 1:
        data = data[:, None]
    elif data.ndim == 2 and data.shape[0] < data.shape[1] and data.shape[0] <= 8:
        data = data.T
    if data.dtype != np.int16:
        data = np.clip(data, -1.0, 1.0)
        data = (data * 32767.0).astype(np.int16)
    n_channels = data.shape[1] if data.ndim == 2 else 1
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(n_channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())
    return buf.getvalue()


def _new_name(prefix, ext):
    return f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}"


# ---- 任务队列 (单 worker 串行) ----
_jobs = {}
_job_queue = queue.Queue()
_job_lock = threading.Lock()


def _run_image(job):
    pipe = get_t2i()
    gen = _make_generator(job.get("seed"))
    kwargs = dict(
        prompt=job["prompt"],
        height=job["height"],
        width=job["width"],
        num_inference_steps=job.get("num_inference_steps", 4),
        guidance_scale=job.get("guidance_scale", 1.0),
        generator=gen,
    )
    if job.get("image"):
        ref = Image.open(io.BytesIO(base64.b64decode(job["image"]))).convert("RGB")
        kwargs["image"] = [ref]
    out = pipe(**kwargs)
    img = out.images[0]
    name = _new_name("img", "png")
    img.save(os.path.join(GENERATED_DIR, name), format="PNG")
    return name


def _run_music(job):
    pipe = get_t2m()
    gen = _make_generator(job.get("seed"))
    out = pipe(
        prompt=job["prompt"],
        generator=gen,
        num_inference_steps=job.get("num_inference_steps", 100),
        audio_end_in_s=job.get("audio_end_in_s", 30.0),
    )
    audio = out.audios[0]
    if isinstance(audio, torch.Tensor):
        audio = audio.cpu().numpy()
    sr = _get_sample_rate(pipe, out)
    wav = _to_wav(audio, sr)
    name = _new_name("music", "wav")
    with open(os.path.join(GENERATED_DIR, name), "wb") as f:
        f.write(wav)
    return name


def _worker():
    while True:
        job_id, job = _job_queue.get()
        with _job_lock:
            _jobs[job_id]["status"] = "running"
        try:
            if job["type"] == "image":
                name = _run_image(job)
            else:
                name = _run_music(job)
            with _job_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["file"] = name
        except Exception as e:
            log.exception("job %s failed", job_id)
            with _job_lock:
                _jobs[job_id]["status"] = "failed"
                _jobs[job_id]["error"] = str(e)


threading.Thread(target=_worker, daemon=True).start()


# ---- 请求体 ----
class JobRequest(BaseModel):
    type: str = Field(..., description="image 或 music")
    prompt: str
    width: int = 768
    height: int = 768
    num_inference_steps: int = None
    guidance_scale: float = 1.0
    seed: int = None
    image: str = None  # base64 参考图, 传入即为图生图
    audio_end_in_s: float = 30.0


# ---- 端点 ----
@app.post("/v1/jobs")
async def submit_job(req: JobRequest):
    if req.type not in ("image", "music"):
        return JSONResponse({"error": "type 必须是 image 或 music"}, status_code=400)
    job = req.model_dump()
    if req.type == "image":
        # 限制分辨率上限, 避免 1024 图生图 OOM
        job["width"] = max(256, min(req.width, MAX_IMAGE_SIZE))
        job["height"] = max(256, min(req.height, MAX_IMAGE_SIZE))
    job_id = uuid.uuid4().hex
    with _job_lock:
        _jobs[job_id] = {"status": "queued", "file": None, "error": None}
    _job_queue.put((job_id, job))
    return {"job_id": job_id}


@app.get("/v1/jobs/{job_id}")
async def get_job(job_id: str, timeout: float = 1800.0):
    """长轮询: 阻塞直到任务完成/失败或超时 (async sleep 不占用事件循环)。"""
    deadline = time.time() + timeout
    while True:
        with _job_lock:
            job = _jobs.get(job_id)
        if job is None:
            return JSONResponse({"status": "not_found"}, status_code=404)
        if job["status"] == "done":
            return {"status": "done", "file_url": f"/files/{job['file']}"}
        if job["status"] == "failed":
            return JSONResponse({"status": "failed", "error": job["error"]}, status_code=500)
        if time.time() > deadline:
            return JSONResponse({"status": "timeout"}, status_code=504)
        await asyncio.sleep(1.0)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9010)
