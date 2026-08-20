# ==========================================
# 文件名: media-gen/app.py
# 架构定位: GPU 1 (7800 XT / gfx1101) 媒体生成服务 (异步 job API)
#   - POST /v1/jobs         提交任务 -> job_id (不阻塞)
#   - GET  /v1/jobs/{id}    轮询状态 queued/running/done/failed
#   - 生成结果写入 /generated, 由 mcp-server 的 /files/{name} 提供下载
#
# 2026-08-20 重写: 后端从 PyTorch+ROCm 换成 ggml+Vulkan。
#   起因: ROCm 在这张卡上静默算错 —— AutoencoderKLFlux2 / AutoencoderOobleck 的
#   decode 非确定 (同输入连调 5 次两两不相关), 图像出纯灰、音频出宽带噪声, 而每个
#   基础算子 (GEMM/Conv/GroupNorm/SDPA/RNG) 都逐位确定。已报 ROCm/ROCm#6633。
#   Vulkan (RADV) 走的是运行时编译的 SPIR-V, 不查 per-gfx 预编译 kernel 表,
#   同一块卡上结果正确且更快 (生图 15.8s 全 GPU vs 之前 77s 且 VAE 必须放 CPU)。
#
# 每个请求 fork 一次 CLI, 用完即释放显存 —— 图像和音乐不会争 VRAM。
# ==========================================
import io
import os
import json
import uuid
import time
import queue
import asyncio
import base64
import urllib.request
import urllib.error
import threading
import logging
import wave

import numpy as np
from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from PIL import Image

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("media-gen")

app = FastAPI(title="media-gen", version="0.3.0")

# ---- 配置 ----
GENERATED_DIR = os.getenv("GENERATED_DIR", "/generated")
VULKAN_DEVICE = os.getenv("VULKAN_DEVICE", "1")          # 1 = RX 7800 XT
MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", "1024"))
# 引擎自己在 120s 硬截断: 请求 180/240/300/480 都返回 120001 ms 且不报错。
# 保留这个上限不是防炸 (显存/耗时都与时长无关, 实测 6173 MiB / 6s 恒定),
# 而是把引擎的"静默截断"变成响应里显式的 clamped 字段, 让调用方知道自己被截了。
MAX_AUDIO_SECONDS = float(os.getenv("MAX_AUDIO_SECONDS", "120"))
JOB_TIMEOUT_S = float(os.getenv("JOB_TIMEOUT_S", "900"))

# 两个 ggml 引擎以常驻 server 运行, 模型不再每次请求重载。
# 权重是 mmap 的 (sd_server RSS 只有 ~340 MiB, 12.6 GB 走 page cache),
# 所以常驻的内存代价很小, 且内核可在压力下回收。
SD_SERVER = os.getenv("SD_SERVER", "http://sd_server:9020")
AUDIO_SERVER = os.getenv("AUDIO_SERVER", "http://audiocpp_server:9021")
AUDIO_MODEL_ID = os.getenv("AUDIO_MODEL_ID", "stable-audio")
# 引擎冷启动的等待上限 (宿主机重启后要从磁盘重读 12.6 GB 权重)
ENGINE_WAIT_S = float(os.getenv("ENGINE_WAIT_S", "180"))
# 生成产物保留天数; 0 表示不清理
RETENTION_DAYS = float(os.getenv("RETENTION_DAYS", "30"))
CLEANUP_INTERVAL_S = float(os.getenv("CLEANUP_INTERVAL_S", "21600"))   # 6 小时

# ---- 输出校验 ----
# 今天最贵的教训: 旧实现在生成失败时写出一个全 0 的 WAV 却返回 status=done。
# 任何"看起来成功但内容退化"的输出都必须让任务显式失败。
MIN_IMAGE_STD = float(os.getenv("MIN_IMAGE_STD", "3.0"))     # 纯灰图实测 std=0.5
MIN_AUDIO_RMS_DBFS = float(os.getenv("MIN_AUDIO_RMS_DBFS", "-60"))


def _new_name(prefix, ext):
    return f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}"


def _http(req, timeout, tag, retry_s=0.0):
    """引擎冷启动时会拒连: sd_server 要读 12.6 GB 权重, 宿主机重启后 page cache 是冷的,
    可能要几十秒才 listen。对连接错误重试, 对 HTTP 错误立即失败 (那是真错)。"""
    deadline = time.time() + retry_s
    delay = 0.5
    while True:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            if time.time() >= deadline:
                raise RuntimeError(f"{tag} 不可达 (已重试 {retry_s:.0f}s): {e}") from e
            log.warning("[%s] 未就绪, %.1fs 后重试: %s", tag, delay, e)
            time.sleep(delay)
            delay = min(delay * 2, 5.0)


def _post(url, payload, tag, timeout=None):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    return _http(req, timeout or JOB_TIMEOUT_S, tag, retry_s=ENGINE_WAIT_S)


def _get(url, timeout=30, tag="engine", retry_s=0.0):
    return _http(urllib.request.Request(url), timeout, tag, retry_s=retry_s)


def _check_image(path):
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    std = float(a.std())
    if std < MIN_IMAGE_STD:
        raise ValueError(
            f"degenerate image: std={std:.3f} < {MIN_IMAGE_STD} — 输出接近纯色, "
            f"多半是后端算错而不是提示词问题"
        )
    log.info("image ok: %s std=%.1f", os.path.basename(path), std)


def _check_audio(path):
    with wave.open(path) as w:
        n, ch = w.getnframes(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    if x.size == 0:
        raise ValueError("empty audio")
    if not np.all(np.isfinite(x)):
        raise ValueError("audio contains non-finite samples")
    rms = float(np.sqrt((x ** 2).mean()))
    dbfs = 20 * np.log10(rms) if rms > 0 else -999.0
    if dbfs < MIN_AUDIO_RMS_DBFS:
        raise ValueError(f"degenerate audio: rms={dbfs:.1f} dBFS < {MIN_AUDIO_RMS_DBFS}")
    log.info("audio ok: %s %.1fs rms=%.1f dBFS", os.path.basename(path), n / w.getframerate(), dbfs)


# ---- 任务队列 (单 worker 串行) ----
_jobs = {}
_job_queue = queue.Queue()
_job_lock = threading.Lock()


def _run_image(job):
    t = time.time()
    payload = {
        "prompt": job["prompt"],
        "width": job["width"], "height": job["height"],
        "steps": job.get("num_inference_steps") or 4,
        "cfg_scale": job.get("guidance_scale") or 1.0,
    }
    if job.get("seed") is not None:
        payload["seed"] = job["seed"]
    if job.get("image"):
        payload["ref_images"] = [job["image"]]        # base64 参考图 -> 图生图
    sub = _post(f"{SD_SERVER}/sdcpp/v1/img_gen", payload, "sd_server", timeout=60)
    poll = f"{SD_SERVER}{sub['poll_url']}"
    deadline = time.time() + JOB_TIMEOUT_S
    while True:
        st = _get(poll)
        if st.get("error"):
            raise RuntimeError(f"sd_server: {st['error']}")
        if st.get("result"):
            break
        if time.time() > deadline:
            raise TimeoutError(f"sd_server job {sub.get('id')} exceeded {JOB_TIMEOUT_S}s")
        time.sleep(0.5)
    imgs = st["result"].get("images") or []
    if not imgs:
        raise RuntimeError("sd_server returned no images")
    name = _new_name("img", st["result"].get("output_format") or "png")
    out = os.path.join(GENERATED_DIR, name)
    with open(out, "wb") as f:
        f.write(base64.b64decode(imgs[0]["b64_json"]))
    log.info("[sd_server] ok in %.1fs", time.time() - t)
    _check_image(out)
    return name


def _run_music(job):
    t = time.time()
    req = {
        "task_route": "text2music",
        "text": job["prompt"],
        "duration_seconds": job["audio_end_in_s"],
    }
    if job.get("seed") is not None:
        req["seed"] = job["seed"]
    if job.get("num_inference_steps"):
        req["num_inference_steps"] = job["num_inference_steps"]
    res = _post(f"{AUDIO_SERVER}/v1/tasks/run", {"model": AUDIO_MODEL_ID, "request": req}, "audiocpp_server")
    b64 = res.get("audio")
    if not b64:
        raise RuntimeError(f"audiocpp_server returned no audio: {str(res)[:300]}")
    name = _new_name("music", "wav")
    out = os.path.join(GENERATED_DIR, name)
    with open(out, "wb") as f:
        f.write(base64.b64decode(b64))
    tm = res.get("timing") or {}
    log.info("[audiocpp_server] ok in %.1fs (rtf=%s)", time.time() - t, tm.get("rtf"))
    _check_audio(out)
    return name


def _worker():
    while True:
        job_id, job = _job_queue.get()
        with _job_lock:
            _jobs[job_id]["status"] = "running"
        try:
            name = _run_image(job) if job["type"] == "image" else _run_music(job)
            with _job_lock:
                _jobs[job_id].update(status="done", file=name)
        except Exception as e:
            log.exception("job %s failed", job_id)
            with _job_lock:
                _jobs[job_id].update(status="failed", error=str(e))


def _cleanup_loop():
    """删除超过 RETENTION_DAYS 的生成产物。文件名带时间戳但以 mtime 为准。"""
    while True:
        try:
            if RETENTION_DAYS > 0:
                cutoff = time.time() - RETENTION_DAYS * 86400
                freed = n = 0
                for f in os.listdir(GENERATED_DIR):
                    fp = os.path.join(GENERATED_DIR, f)
                    try:
                        if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
                            freed += os.path.getsize(fp)
                            os.remove(fp)
                            n += 1
                    except OSError:
                        pass
                if n:
                    log.info("cleanup: 删除 %d 个超过 %.0f 天的文件, 释放 %.1f MiB",
                             n, RETENTION_DAYS, freed / 2**20)
        except Exception:
            log.exception("cleanup 失败")
        time.sleep(CLEANUP_INTERVAL_S)


threading.Thread(target=_cleanup_loop, daemon=True).start()
threading.Thread(target=_worker, daemon=True).start()


# ---- 请求体 ----
class JobRequest(BaseModel):
    type: str = Field(..., description="image 或 music")
    prompt: str
    width: int = 512
    height: int = 512
    num_inference_steps: int | None = None
    guidance_scale: float = 1.0
    seed: int | None = None
    image: str | None = None          # base64 参考图, 传入即为图生图
    audio_end_in_s: float = 10.0


# ---- 端点 ----
@app.post("/v1/jobs")
async def submit_job(req: JobRequest):
    if req.type not in ("image", "music"):
        return JSONResponse({"error": "type 必须是 image 或 music"}, status_code=400)
    job = req.model_dump()
    clamped = None
    if req.type == "image":
        job["width"] = max(256, min(req.width, MAX_IMAGE_SIZE))
        job["height"] = max(256, min(req.height, MAX_IMAGE_SIZE))
        if (job["width"], job["height"]) != (req.width, req.height):
            clamped = {"width": job["width"], "height": job["height"]}
    else:
        job["audio_end_in_s"] = max(1.0, min(float(req.audio_end_in_s), MAX_AUDIO_SECONDS))
        if job["audio_end_in_s"] != req.audio_end_in_s:
            clamped = {"audio_end_in_s": job["audio_end_in_s"]}
    job_id = uuid.uuid4().hex
    with _job_lock:
        _jobs[job_id] = {"status": "queued", "file": None, "error": None}
    _job_queue.put((job_id, job))
    return {"job_id": job_id, "clamped": clamped}


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


@app.get("/files/{filename}")
async def serve_file(filename: str):
    """下载生成的文件 (图片/音乐), 供远程 agent 直接获取。"""
    safe = os.path.basename(filename)  # 防目录穿越
    path = os.path.join(GENERATED_DIR, safe)
    if not os.path.exists(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


@app.get("/health")
async def health():
    down = []
    for name, url in (("sd_server", f"{SD_SERVER}/sdcpp/v1/capabilities"),
                      ("audiocpp_server", f"{AUDIO_SERVER}/health")):
        try:
            _get(url, timeout=5, tag=name)
        except Exception as e:
            down.append(f"{name}: {e}")
    if down:
        return JSONResponse({"status": "degraded", "down": down}, status_code=503)
    return {"status": "ok", "backend": "ggml/vulkan (persistent servers)", "device": VULKAN_DEVICE}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9010)
