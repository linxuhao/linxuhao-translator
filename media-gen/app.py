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
import re
from dataclasses import dataclass, asdict

import numpy as np
from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, ConfigDict, Field
from PIL import Image, ImageDraw

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("media-gen")

app = FastAPI(title="media-gen", version="0.4.0")

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
SPEECH_MODEL_ID = os.getenv("SPEECH_MODEL_ID", "qwen3-tts")
# Qwen3-TTS VoiceDesign: 声音由一段自然语言描述决定, 不需要参考音频 ——
# 虚构角色本来就没有真人录音, 但一定有人设描述。
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "A neutral adult narrator, clear and natural")
# 文本长度上限 —— 这是护栏, 不是礼貌性的限制。实测:
#   201 字 -> 45.7 s 音频, 生成 16 s   OK
#   402 字 -> 90.3 s 音频, 生成 42 s   OK
#   600 字 -> ~135 s 音频, 生成 ~63 s  GPU 挂死 (amdgpu GPU reset(6),
#             连带 GPU0 的 vllm SIGSEGV) —— 与音乐那条算力预算同一类问题:
#             单次 Vulkan 提交扛不住这么长的持续计算。
# 200 字取在已知安全值 (402) 的一半, 而且 200 字已经是 45 秒旁白 ——
# 游戏里一句 NPC 台词通常 10~40 字, 这个上限不会碰到。更长的文本请分多次调用。
MAX_SPEECH_CHARS = int(os.getenv("MAX_SPEECH_CHARS", "200"))
# 字数上限只挡住"输入长", 挡不住"输出跑飞": 引擎默认 max_tokens=2048 (~170 s 音频),
# 一句短台词一旦退化成循环, 照样能生成几分钟并拖挂 GPU。按字数推 token 预算,
# 让跑飞的请求早早自己停下。实测 ~2.7 token/字, 取 4.0 留余量。
SPEECH_TOKENS_PER_CHAR = float(os.getenv("SPEECH_TOKENS_PER_CHAR", "4.0"))
SPEECH_MAX_TOKENS = int(os.getenv("SPEECH_MAX_TOKENS", "900"))

# ---- Actor: 把音色钉死在一段参考音上 ----
# VoiceDesign 只圈定一个大致的音色区间, 区间内每句台词各漂各的 (实测同 voice
# 同 seed 四句台词基频极差 125 Hz; 关掉采样走贪心反而涨到 242 Hz —— 音色是
# 文本的函数, 不是采样随机性, 所以锁 seed / temperature / top_k 都锁不住)。
# 唯一的修法是换模型: 用 VoiceDesign 铸一句参考音, 之后所有台词交给 Base
# 以那段音频克隆, 音色由参考音决定, 与台词内容无关。
#
# 参考音是长期资产, 不是产物, 所以单独挂一个卷。/generated 上有 30 天清理,
# 它眼下不递归、也只删文件, 子目录"碰巧"安全 —— 但那是意外不是设计,
# 哪天改成 os.walk, 全部角色的声音会在第 30 天集体静默消失。
ACTORS_DIR = os.getenv("ACTORS_DIR", "/actors")
CLONE_MODEL_ID = os.getenv("CLONE_MODEL_ID", "qwen3-tts-base")
_AUDIO_MODELS = {AUDIO_MODEL_ID, SPEECH_MODEL_ID, CLONE_MODEL_ID}
# 铸声用的台词: 覆盖面尽量广, 时长 ~7 s (克隆参考音的常用区间)
DEFAULT_SAMPLE_TEXT = os.getenv(
    "DEFAULT_SAMPLE_TEXT",
    "江湖路远，人心难测。今日一别，山高水长，来日方长，后会有期。")
_ACTOR_NAME_RE = re.compile(r"^[\w\u4e00-\u9fff-]{1,40}$")

# ---- Subject: 把"长什么样"钉在一张定妆图上 ----
# 和 actor 同一个病、同一个解法。text2img 每次给的是"长得不一样的东西": 同一个角色
# 的头像 / 战斗立绘 / 地图小人是三个人; 同一个宝箱换个角度也是另一个箱子。
# 定妆一次存成参考图, 之后每张图都带着它走图生图, 外观就跟场景描述解耦了。
#
# 角色和道具是同一个机制, 差别只在取景 —— 所以这里是一套存储, 用 kind 选取景,
# 而不是把同样的 150 行复制两份。
SUBJECTS_DIR = os.getenv("SUBJECTS_DIR", "/subjects")
# 三类要盯的东西不一样, 所以取景也不一样 —— 定妆图上没留下的信息, 出场景图时
# 模型只能自己编, 而它每次编得都不一样。
SUBJECT_FRAMING = {
    # 人: 脸和衣着是识别点, 要正面全身看全
    "character": "full body character reference, neutral standing pose, facing viewer, "
                 "plain flat background, clean game art",
    # 动物: 体型比例和花纹分布是识别点, 四分之三站姿同时给出侧面轮廓和正面头部
    "animal": "full body animal reference, standing in three-quarter view, head visible, "
              "plain flat background, no scenery, clean game art",
    # 物件: 几何是识别点, 且最容易漂 —— 正投影看不出体积, 换个角度就没有可对齐的信息
    "object": "single game asset reference, three-quarter view, centered, isolated, "
              "plain flat background, no scenery, clean game art",
}
DEFAULT_SUBJECT_KIND = "character"


def _subject_paths(name):
    return (os.path.join(SUBJECTS_DIR, name + ".png"),
            os.path.join(SUBJECTS_DIR, name + ".json"))


def _load_subject(name):
    _, meta = _subject_paths(name)
    if not os.path.isfile(meta):
        return None
    with open(meta, encoding="utf-8") as f:
        return json.load(f)


def _subject_names():
    try:
        return sorted(f[:-5] for f in os.listdir(SUBJECTS_DIR) if f.endswith(".json"))
    except OSError:
        return []


def _actor_paths(name):
    return (os.path.join(ACTORS_DIR, name + ".wav"),
            os.path.join(ACTORS_DIR, name + ".json"))


def _load_actor(name):
    _, meta = _actor_paths(name)
    if not os.path.isfile(meta):
        return None
    with open(meta, encoding="utf-8") as f:
        return json.load(f)


def _actor_names():
    try:
        return sorted(f[:-5] for f in os.listdir(ACTORS_DIR) if f.endswith(".json"))
    except OSError:
        return []
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


def _sd_generate(job, prompt, ref_b64=None):
    """向 sd_server 提交一张图并等它出来, 返回 (图片字节, 后缀)。"""
    payload = {
        "prompt": prompt,
        "width": job["width"], "height": job["height"],
        "steps": job.get("num_inference_steps") or 4,
        "cfg_scale": job.get("guidance_scale") or 1.0,
    }
    if job.get("seed") is not None:
        payload["seed"] = job["seed"]
    if ref_b64:
        payload["ref_images"] = [ref_b64]             # base64 参考图 -> 图生图
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
    return (base64.b64decode(imgs[0]["b64_json"]),
            st["result"].get("output_format") or "png")


def _ref_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _run_image(job):
    t = time.time()
    ref, prompt = job.get("image"), job["prompt"]
    subject = job.get("subject")
    if subject:
        # 场景图: 外观由定妆图决定, prompt 只管场景/动作/视角
        c = _load_subject(subject)
        if c is None:
            raise RuntimeError(f"subject '{subject}' 不存在")
        ref = _ref_b64(c["reference_path"])
        prompt = f'{c["appearance"]}, {prompt}'
    data, ext = _sd_generate(job, prompt, ref)
    name = _new_name("img", ext)
    out = os.path.join(GENERATED_DIR, name)
    with open(out, "wb") as f:
        f.write(data)
    log.info("[sd_server] ok in %.1fs%s", time.time() - t,
             f" (subject={subject})" if subject else "")
    _fit_size(out, job.get("want_width", job["width"]), job.get("want_height", job["height"]))
    _check_image(out)
    return name


def _run_subject_create(job):
    """定妆: 生成一张参考图存成 subject。和铸声一样走任务队列 —— 它要用 GPU。"""
    t = time.time()
    name, kind = job["subject"], job.get("kind") or DEFAULT_SUBJECT_KIND
    png, meta_path = _subject_paths(name)
    prompt = f'{job["prompt"]}, {SUBJECT_FRAMING[kind]}'
    data, _ = _sd_generate(job, prompt)
    os.makedirs(SUBJECTS_DIR, exist_ok=True)
    with open(png, "wb") as f:
        f.write(data)
    _check_image(png)          # 退化的定妆图会污染这个 subject 的每一张场景图
    meta = {
        "name": name,
        "kind": kind,
        "appearance": job["prompt"],
        "prompt": prompt,
        "reference_path": png,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": job.get("seed"),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log.info("[subject] 定妆 %s (%s) 完成 (%.1fs)", name, kind, time.time() - t)
    return None, {"subject": name, "kind": kind, "appearance": job["prompt"],
                  "reference_url": f"/v1/subjects/{name}/image"}


def _fit_size(path, want_w, want_h):
    """Make the file the size that was ASKED for, not the one the model felt like.

    The engine snaps a request onto its own latent grid (and to a minimum edge),
    so a 40x32 sprite comes back as 256x256. Callers that need an exact canvas —
    a game asset pipeline validating sprite dimensions — then reject every image
    and ship nothing, which is exactly what happened. width/height are documented
    as the output size, so honour them here instead of leaking the grid.

    LANCZOS going down (almost always the case: the grid minimum is far above a
    sprite), NEAREST going up so an upscaled pixel sprite keeps hard edges."""
    try:
        img = Image.open(path)
        if (img.width, img.height) == (want_w, want_h):
            return
        shrinking = want_w * want_h < img.width * img.height
        img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB").resize(
            (want_w, want_h),
            Image.LANCZOS if shrinking else Image.NEAREST,
        ).save(path)
        log.info("[sd_server] resized %dx%d -> %dx%d", img.width, img.height, want_w, want_h)
    except Exception:
        log.warning("resize to %dx%d failed; keeping engine canvas", want_w, want_h,
                    exc_info=True)


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
    _use_audio_model(AUDIO_MODEL_ID)
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


def _use_audio_model(keep):
    """同一时刻只让一个音频模型占着显存。

    三个音频模型 (音乐 / VoiceDesign / Base 克隆) 全常驻时实测峰值 15.70/16.00 GB,
    再叠一张 1024 生图就把 GPU 挤挂了 (第三次 device lost)。而它们的显存是"用过就
    留着"的: 三个都推理过是 11.09 GB, 卸掉两个降到 7.90, 全卸掉降到 3.62。
    media_gen 本来就是单 worker 串行, 同一时刻只需要一个 —— 重载实测 4.3 s
    (权重在 page cache 里), 只在音乐/配音/铸声之间切换时才付这个钱。
    卸载失败不让任务失败: 那只是少省一点显存, 不是错误。"""
    others = sorted(_AUDIO_MODELS - {keep})
    if not others:
        return
    try:
        _post(f"{AUDIO_SERVER}/v1/tasks/unload_models", {"model_ids": others}, "audiocpp_server",
              timeout=120)
    except Exception:
        log.warning("卸载 %s 失败, 继续", others, exc_info=True)


def _tts(model_id, req, tag):
    _use_audio_model(model_id)
    req["max_tokens"] = max(64, min(SPEECH_MAX_TOKENS,
                                    int(len(req["text"]) * SPEECH_TOKENS_PER_CHAR)))
    res = _post(f"{AUDIO_SERVER}/v1/tasks/run", {"model": model_id, "request": req}, tag)
    b64 = res.get("audio")
    if not b64:
        raise RuntimeError(f"{model_id} returned no audio: {str(res)[:300]}")
    return base64.b64decode(b64), res.get("timing") or {}


def _run_actor_create(job):
    """用 VoiceDesign 铸一句参考音, 存成角色。这一步走任务队列而不是同步端点,
    是因为它要用 GPU —— 必须和生图/音乐串行, 否则显存会撞车。"""
    t = time.time()
    name, text = job["actor"], job["prompt"]
    wav_path, meta_path = _actor_paths(name)
    audio, tm = _tts(SPEECH_MODEL_ID, {
        "task_route": "vdes", "text": text,
        "instruct": job["instruct"], "seed": job.get("seed"),
    }, "audiocpp_server")
    os.makedirs(ACTORS_DIR, exist_ok=True)
    with open(wav_path, "wb") as f:
        f.write(audio)
    _check_audio(wav_path)          # 退化的参考音会污染这个角色的每一句台词
    meta = {
        "name": name,
        "voice": job["instruct"],
        "transcript": text,          # Base 克隆要参考音的文字, 而这段是我们自己生成的
        "reference_path": wav_path,  # 引擎和本服务挂的是同一个 /actors
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": job.get("seed"),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    log.info("[actor] 铸声 %s 完成 (%.1fs, rtf=%s)", name, time.time() - t, tm.get("rtf"))
    return None, {"actor": name, "transcript": text,
                  "reference_url": f"/v1/actors/{name}/audio"}


def _run_speech(job):
    t = time.time()
    actor = job.get("actor")
    if actor:
        # 角色台词: Base 模型克隆参考音, 音色与台词内容无关
        a = _load_actor(actor)
        if a is None:
            raise RuntimeError(f"actor '{actor}' 不存在")
        model_id = CLONE_MODEL_ID
        req = {"task_route": "tts", "text": job["prompt"],
               "voice_ref": a["reference_path"], "reference_text": a["transcript"]}
    else:
        # 一次性旁白: VoiceDesign 直接从描述生成, 不保证跨句音色一致
        model_id = SPEECH_MODEL_ID
        req = {"task_route": "vdes", "text": job["prompt"],
               "instruct": job.get("instruct") or DEFAULT_VOICE}
    if job.get("seed") is not None:
        req["seed"] = job["seed"]
    if job.get("speaking_rate"):
        req["speaking_rate"] = job["speaking_rate"]
    audio, tm = _tts(model_id, req, "audiocpp_server")
    name = _new_name("speech", "wav")
    out = os.path.join(GENERATED_DIR, name)
    with open(out, "wb") as f:
        f.write(audio)
    log.info("[%s] speech ok in %.1fs (rtf=%s)", model_id, time.time() - t, tm.get("rtf"))
    _check_audio(out)
    return name


_RUNNERS = {"image": _run_image, "music": _run_music, "speech": _run_speech,
            "actor_create": _run_actor_create, "subject_create": _run_subject_create}


def _worker():
    while True:
        job_id, job = _job_queue.get()
        with _job_lock:
            _jobs[job_id]["status"] = "running"
        try:
            out = _RUNNERS[job["type"]](job)
            name, meta = out if isinstance(out, tuple) else (out, None)
            with _job_lock:
                _jobs[job_id].update(status="done", file=name, meta=meta)
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
    # 未知字段一律报错。Pydantic 默认是静默忽略, 于是一个写错的/过时的字段名
    # (例如改名后还在传 character= 而不是 subject=) 会让请求"成功"地生成一张
    # 完全没用上定妆图的普通图 —— 看起来是 done, 内容是错的。宁可 422。
    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., description="image / music / speech / actor_create / subject_create")
    prompt: str = ""                  # speech 时是要念的文本; actor_create 时是铸声台词
    actor: str | None = None          # speech: 用哪个角色的音色; actor_create: 角色名
    subject: str | None = None        # image: 用哪个 subject 的外观; subject_create: 名字
    kind: str | None = None           # subject_create: character / object (只影响取景)
    instruct: str | None = None       # 声音的自然语言描述 (actor_create 必填)
    force: bool = False               # actor_create: 覆盖已有角色
    speaking_rate: float | None = None
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
    if req.type not in _RUNNERS:
        return JSONResponse({"error": f"type 必须是 {'/'.join(_RUNNERS)}"}, status_code=400)
    job = req.model_dump()
    clamped = None
    if req.type == "subject_create":
        name = (req.subject or "").strip()
        kind = (req.kind or DEFAULT_SUBJECT_KIND).strip()
        if not _ACTOR_NAME_RE.match(name):
            return JSONResponse({"error": "subject 名只能是字母/数字/下划线/连字符/中文, 1~40 字"},
                                status_code=400)
        if kind not in SUBJECT_FRAMING:
            return JSONResponse({"error": f"kind 必须是 {'/'.join(SUBJECT_FRAMING)}"},
                                status_code=400)
        if not req.prompt.strip():
            return JSONResponse({"error": "subject_create 的 prompt 是外观描述, 不能为空"},
                                status_code=400)
        if _load_subject(name) is not None and not req.force:
            return JSONResponse(
                {"error": f"subject '{name}' 已存在。定妆一次用一辈子, 覆盖会让它之前"
                          f"所有场景图的外观对不上 —— 确实要重定就传 force=true。"},
                status_code=409)
        job["subject"], job["kind"] = name, kind
        job["want_width"] = job["width"] = max(256, min(req.width, MAX_IMAGE_SIZE))
        job["want_height"] = job["height"] = max(256, min(req.height, MAX_IMAGE_SIZE))
    elif req.type == "image":
        # Two different sizes, and conflating them is what made every sprite the
        # wrong shape: `want_*` is what the CALLER gets (only the upper bound
        # applies — _fit_size resizes the result at the end), while `width`/
        # `height` are what the ENGINE is asked to render, which has a 256px
        # floor. Only the upper clamp is worth reporting; the floor is internal.
        job["want_width"] = min(req.width, MAX_IMAGE_SIZE)
        job["want_height"] = min(req.height, MAX_IMAGE_SIZE)
        job["width"] = max(256, job["want_width"])
        job["height"] = max(256, job["want_height"])
        if (job["want_width"], job["want_height"]) != (req.width, req.height):
            clamped = {"width": job["want_width"], "height": job["want_height"]}
        if req.subject and _load_subject(req.subject) is None:
            return JSONResponse(
                {"error": f"subject '{req.subject}' 不存在 —— 先调 "
                          f"create_character / create_object (name='{req.subject}', "
                          f"appearance='一段外观描述') 定妆, 再用它出场景图。"
                          f"现有: {_subject_names() or '(还没有)'}"},
                status_code=404)
    elif req.type == "actor_create":
        name = (req.actor or "").strip()
        if not _ACTOR_NAME_RE.match(name):
            return JSONResponse({"error": "actor 名只能是字母/数字/下划线/连字符/中文, 1~40 字"},
                                status_code=400)
        if not (req.instruct or "").strip():
            return JSONResponse({"error": "actor_create 必须给 instruct (声音的自然语言描述)"},
                                status_code=400)
        if _load_actor(name) is not None and not req.force:
            return JSONResponse(
                {"error": f"actor '{name}' 已存在。铸声一次用一辈子, 覆盖会让它之前"
                          f"所有台词的音色对不上 —— 确实要重铸就传 force=true。"},
                status_code=409)
        job["actor"] = name
        text = (req.prompt or "").strip() or DEFAULT_SAMPLE_TEXT
        job["prompt"] = text[:MAX_SPEECH_CHARS]
        if len(text) > MAX_SPEECH_CHARS:
            clamped = {"prompt_chars": MAX_SPEECH_CHARS}
    elif req.type == "speech":
        text = req.prompt.strip()
        if not text:
            return JSONResponse({"error": "speech 的 prompt 不能为空"}, status_code=400)
        if req.actor and _load_actor(req.actor) is None:
            # 指令式报错: 调用方是 LLM, 告诉它下一步该干什么, 而不是只说"没找到"
            return JSONResponse(
                {"error": f"actor '{req.actor}' 不存在 —— 先调 create_actor(name='{req.actor}', "
                          f"voice='一段声音描述') 铸声, 再用它说台词。"
                          f"现有角色: {_actor_names() or '(还没有)'}"},
                status_code=404)
        job["prompt"] = text[:MAX_SPEECH_CHARS]
        if len(text) > MAX_SPEECH_CHARS:
            clamped = {"prompt_chars": MAX_SPEECH_CHARS}
    else:
        job["audio_end_in_s"] = max(1.0, min(float(req.audio_end_in_s), MAX_AUDIO_SECONDS))
        if job["audio_end_in_s"] != req.audio_end_in_s:
            clamped = {"audio_end_in_s": job["audio_end_in_s"]}
    job_id = uuid.uuid4().hex
    with _job_lock:
        _jobs[job_id] = {"status": "queued", "file": None, "error": None, "meta": None}
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
            out = {"status": "done"}
            if job.get("file"):
                out["file_url"] = f"/files/{job['file']}"
            if job.get("meta"):
                out.update(job["meta"])
            return out
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


# ---- 图像后处理 (纯 CPU, 同步执行) ----
# 不走上面的 job 队列: 那个队列是单 worker 串行的, 为的是让两个 ggml 引擎不争显存;
# 抠图/切图既不碰 GPU 也只要几百毫秒, 排在一次 15s 生图后面纯属浪费。
# 路由用 def 而不是 async def, Starlette 会把它丢进线程池, 不阻塞事件循环。

# rembg 模型: 默认换成 birefnet-general-lite。同机实测 (512x512, 容器内热推理):
#   u2netp            0.16s  软边最多, 猫尾巴留一圈灰雾
#   isnet-general-use 1.38s  尾巴仍有轻雾
#   birefnet-general-lite 5.89s  干净  <- 默认
#   bria-rmbg        10.85s  同样干净, 但翻倍的耗时只换来边缘的一点点提升
# 慢 6s 换一张能直接用的图是划算的; 要快就传 quality="fast"。
REMBG_MODELS = {"best": "birefnet-general-lite", "fast": "u2netp"}
_rembg_sessions = {}          # 每个模型一个常驻 session (onnxruntime 初始化很贵)

# 棋盘格判定阈值 (见 _looks_like_checkerboard)
CHECKER_MIN_CAND = float(os.getenv("CHECKER_MIN_CAND", "0.05"))
CHECKER_MIN_GAP = float(os.getenv("CHECKER_MIN_GAP", "15"))
CHECKER_MAX_VALLEY = float(os.getenv("CHECKER_MAX_VALLEY", "0.30"))
CHECKER_MIN_RUNS = float(os.getenv("CHECKER_MIN_RUNS", "0.60"))

# alpha 退化判定 (见 _alpha_warning)
ALPHA_MAX_TRANSPARENT = float(os.getenv("ALPHA_MAX_TRANSPARENT", "0.95"))
ALPHA_MIN_TRANSPARENT = float(os.getenv("ALPHA_MIN_TRANSPARENT", "0.02"))
ALPHA_MIN_BLOB = float(os.getenv("ALPHA_MIN_BLOB", "0.02"))
ALPHA_MAX_HOLES = float(os.getenv("ALPHA_MAX_HOLES", "0.05"))
ALPHA_MAX_BG_DETAIL = float(os.getenv("ALPHA_MAX_BG_DETAIL", "0.5"))


def _checker_candidates(a, bright=195, neutral=20):
    """又亮又接近中性灰的像素 —— 棋盘格的必要条件, 但远不是充分条件。"""
    return (a.min(2) >= bright) & ((a.max(2) - a.min(2)) <= neutral)


def _key_checkerboard(img, bright=195, neutral=20):
    """把 FLUX 画出来的"透明棋盘格"抠掉, 返回 alpha 数组。

    FLUX.2 Klein 不会输出 alpha 通道: 你要"透明背景", 它就把 PS 那种灰白格子当成
    不透明像素画出来。这些格子的特征是又亮又接近中性灰 (实测 255 与 220 两种方块)。
    只按颜色判定会连鸟肚子上的白色一起抠掉, 所以再加一条: 必须与画面边缘连通。
    """
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    cand = _checker_candidates(a, bright, neutral)
    # Image.fromarray 返回的是只读 buffer, floodfill 的写入会被静默丢弃, 必须 copy()
    m = Image.fromarray(np.where(cand, 255, 0).astype(np.uint8)).copy()
    w, h = img.size
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if m.getpixel(xy) == 255:
            ImageDraw.floodfill(m, xy, 128, thresh=0)
    return np.where(np.array(m) == 128, 0, 255).astype(np.uint8)


def _two_tone(grey, cand):
    """候选区的灰度是不是"两级"。返回 (峰1, 峰2, 谷/峰)。

    真棋盘格实测并不是干净的两个值 (FLUX 画出来带噪): 255/254 一簇, 219~224 一簇。
    所以用平滑直方图找两个峰, 再看两峰之间的谷有多深 —— 连续渐变的摄影背景填满谷,
    两级方格则谷接近 0。
    """
    hist = np.bincount(grey[cand], minlength=256).astype(np.float64)
    sm = np.convolve(hist, np.ones(5) / 5.0, mode="same")
    total = sm.sum()
    if total <= 0:
        return 0, 0, 1.0
    sm /= total
    p1 = int(np.argmax(sm))
    far = np.ones(256, dtype=bool)
    far[max(0, p1 - 10):p1 + 11] = False          # 第二个峰必须离第一个足够远
    p2 = int(np.argmax(np.where(far, sm, -1.0)))
    lo, hi = sorted((p1, p2))
    peak = float(min(sm[p1], sm[p2]))
    valley = float(sm[lo + 1:hi].min()) if hi - lo > 1 else peak
    return p1, p2, (valley / peak if peak > 0 else 1.0)


def _tone_runs(tone, cand):
    """沿行统计交替方块的游程长度。

    只看候选像素占多数的行, 并丢掉每段两端不完整的游程 —— 半个方块会污染中位数。
    """
    out = []
    for r in range(tone.shape[0]):
        row = cand[r]
        if row.mean() < 0.5:
            continue
        idx = np.flatnonzero(row)
        if idx.size < 32:
            continue
        for span in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
            if span.size < 32:
                continue
            t = tone[r, span]
            bounds = np.concatenate(([0], np.flatnonzero(np.diff(t)) + 1, [t.size]))
            rl = np.diff(bounds)
            if rl.size > 2:
                out.extend(rl[1:-1].tolist())
    return np.asarray(out, dtype=np.float64)


def _looks_like_checkerboard(img, bright=195, neutral=20):
    """这张图的亮中性区域到底是不是 FLUX 的"假透明"棋盘格。返回 (bool, 证据)。

    旧实现按"抠掉了多少"来判 (yield): 先抠一遍, 抠掉 >5% 就认为是棋盘格。那是错的 ——
    任何明亮中性的摄影背景都满足候选条件。实测白猫 + 浅灰影棚背景被判成 checker (0.662),
    floodfill 从边缘连通进猫身体, 把猫身上和头上啃出大洞。

    改判结构证据: 棋盘格是恰好两级灰度 (实测 253 与 221) 铺成的固定边长方块。
    两个条件都成立才算; 否则一律走 rembg。
    """
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    cand = _checker_candidates(a, bright, neutral)
    ev = {"cand_ratio": round(float(cand.mean()), 4)}
    if cand.mean() < CHECKER_MIN_CAND:
        return False, dict(ev, reason="亮中性区域太小, 没有假透明背景")
    grey = a.mean(2).astype(np.uint8)
    p1, p2, valley = _two_tone(grey, cand)
    ev.update(tones=[p1, p2], tone_gap=abs(p1 - p2), valley_ratio=round(valley, 3))
    if abs(p1 - p2) < CHECKER_MIN_GAP or valley > CHECKER_MAX_VALLEY:
        return False, dict(ev, reason="灰度是连续渐变而非两级, 像摄影背景")
    tone = grey >= (p1 + p2) / 2.0
    rows, cols = _tone_runs(tone, cand), _tone_runs(tone.T, cand.T)
    if rows.size < 16 or cols.size < 16:
        return False, dict(ev, reason="没有成片的候选区可判周期")
    cell_r, cell_c = float(np.median(rows)), float(np.median(cols))
    cons_r = float((np.abs(rows - cell_r) <= max(1.0, 0.25 * cell_r)).mean())
    cons_c = float((np.abs(cols - cell_c) <= max(1.0, 0.25 * cell_c)).mean())
    ev.update(cell=[round(cell_r, 1), round(cell_c, 1)],
              run_consistency=[round(cons_r, 3), round(cons_c, 3)])
    if cons_r < CHECKER_MIN_RUNS or cons_c < CHECKER_MIN_RUNS:
        return False, dict(ev, reason="方块边长不规则, 不是周期网格")
    if not (3 <= cell_r <= 128 and 3 <= cell_c <= 128):
        return False, dict(ev, reason="方块尺寸不合理")
    if abs(cell_r - cell_c) > 0.25 * max(cell_r, cell_c):
        return False, dict(ev, reason="方块不是正方形")
    return True, dict(ev, reason="两级灰度 + 周期方格 = FLUX 假透明")


def _rembg_alpha(img, quality="best"):
    """通用显著物体抠图。放 CPU (onnxruntime) —— GPU 留给两个 ggml 引擎。"""
    import onnxruntime as ort
    from rembg import new_session, remove
    model = REMBG_MODELS.get(quality, REMBG_MODELS["best"])
    sess = _rembg_sessions.get(model)
    if sess is None:
        log.info("rembg: 首次加载 %s", model)
        # onnxruntime 的 CPU memory arena 把推理峰值变成常驻内存, 且永不归还:
        # 实测 1024x1024 两次调用后 RSS 0.06 -> 7.5 -> 12.1 GB 封顶不动
        # (30 GB 的机器凭空少掉 40% 内存, available 只剩 2 GB)。
        # 关掉 arena 后常驻 0.69 GB, alpha 输出逐位相同 —— 纯粹是分配器行为。
        so = ort.SessionOptions()
        so.enable_cpu_mem_arena = False
        sess = _rembg_sessions[model] = new_session(model, sess_opts=so)
    return model, np.array(remove(img.convert("RGB"), session=sess))[:, :, 3]

def _largest_blob_ratio(mask, max_side=192):
    """最大不透明连通块占整图的比例。

    缩到 <=192px 再做标签传播 (取 4 邻域最大值直到不动): 这个数只用来判"抠出来的东西
    碎成了渣", 不需要像素级精度, 而全分辨率的纯 python 连通域太慢。
    """
    h, w = mask.shape
    s = max_side / max(h, w)
    if s < 1.0:
        m = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize(
            (max(1, int(w * s)), max(1, int(h * s))), Image.NEAREST)) > 127
    else:
        m = mask
    if not m.any():
        return 0.0
    lab = np.where(m, np.arange(1, m.size + 1).reshape(m.shape), 0)
    for _ in range(4 * max(m.shape)):
        nb = lab.copy()
        nb[1:] = np.maximum(nb[1:], lab[:-1])
        nb[:-1] = np.maximum(nb[:-1], lab[1:])
        nb[:, 1:] = np.maximum(nb[:, 1:], lab[:, :-1])
        nb[:, :-1] = np.maximum(nb[:, :-1], lab[:, 1:])
        nb = np.where(m, nb, 0)
        if np.array_equal(nb, lab):
            break
        lab = nb
    counts = np.bincount(lab.ravel())
    counts[0] = 0
    return float(counts.max() / m.size)


def _hole_ratio(alpha):
    """主体轮廓内部被抠出来的洞, 占不透明面积的比例。

    白猫那次翻车不是比例算错 —— 0.662 对那张图完全是个合理的数字; 真正错的是
    猫身上和头上被啃出了洞。洞是"透明、但从画面边缘走不到"的像素, 用 _key_checkerboard
    已经在用的 floodfill 就能数出来 (外面先套一圈透明, 让所有贴边的透明区连成一片,
    一次 floodfill 就够), 不必为此引入 scipy。
    """
    opaque = alpha > 0
    n = int(opaque.sum())
    if n == 0:
        return 0.0
    h, w = opaque.shape
    pad = np.zeros((h + 2, w + 2), dtype=np.uint8)
    pad[1:-1, 1:-1] = np.where(opaque, 255, 0)
    m = Image.fromarray(pad).copy()          # fromarray 的 buffer 只读, 必须 copy
    ImageDraw.floodfill(m, (0, 0), 128, thresh=0)
    return float((np.asarray(m)[1:-1, 1:-1] == 0).sum() / n)


def _bg_detail_ratio(img, alpha):
    """被抠掉的那片区域, 细节密度相对于留下来的主体有多高。

    合格的抠图, 去掉的是背景: 影棚灰、白桌面、绿幕、棋盘格, 都很平。当"背景"和主体
    一样满是边缘时 (集市那张: 0.90), 说明模型只是从一整幅场景里随手挑了几个人留下,
    这种结果多半不是调用方想要的。返回 (相对比值, 去掉区域的平均梯度)。
    """
    g = np.asarray(img.convert("L"), dtype=np.float32)
    gx, gy = np.abs(np.diff(g, axis=1)), np.abs(np.diff(g, axis=0))
    def mean_in(mask):
        mx, my = mask[:, :-1] & mask[:, 1:], mask[:-1] & mask[1:]
        v = np.concatenate([gx[mx], gy[my]])
        return float(v.mean()) if v.size else 0.0
    removed, kept = mean_in(alpha == 0), mean_in(alpha > 127)
    return (removed / kept if kept > 1.0 else 0.0), removed


def _alpha_report(img, alpha, extra=()):
    """算出抠图质量指标, 并在明显不对时给一句话警告 (不失败, 只是别再默默报成功)。"""
    tr = float((alpha == 0).mean())
    solid = float((alpha > 127).mean())
    holes = _hole_ratio(alpha)
    blob = _largest_blob_ratio(alpha > 127)
    detail, removed_grad = _bg_detail_ratio(img, alpha)
    m = {"transparent_ratio": round(tr, 4), "solid_ratio": round(solid, 4),
         "hole_ratio": round(holes, 4), "largest_blob_ratio": round(blob, 4),
         "bg_detail_ratio": round(detail, 3)}
    w = list(extra)
    if tr > ALPHA_MAX_TRANSPARENT:
        w.append(f"{tr:.1%} 的像素被抠成了透明, 主体几乎整个没了")
    if tr < ALPHA_MIN_TRANSPARENT:
        w.append(f"只抠掉了 {tr:.1%}, 基本什么都没去掉")
    if blob < ALPHA_MIN_BLOB:
        w.append(f"最大的不透明连通块只占整图 {blob:.1%}, 抠出来的是碎片不是主体")
    if holes > ALPHA_MAX_HOLES:
        w.append(f"主体轮廓内部有 {holes:.1%} 的面积被挖成了洞 (相对不透明面积), "
                 f"多半是背景色和主体撞色被啃穿了")
    if detail > ALPHA_MAX_BG_DETAIL and removed_grad > 5.0:
        w.append(f"被去掉的区域细节密度是主体的 {detail:.0%}, 那不是背景而是画面的一部分, "
                 f"这张图没有明确的前景主体")
    return m, ("抠图结果很可能不对: " + "; ".join(w) if w else None)


def _trim(frame):
    """裁到非透明/非棋盘格的外接框。"""
    if frame.mode == "RGBA":
        box = frame.getchannel("A").getbbox()
    else:
        box = Image.fromarray(_key_checkerboard(frame)).getbbox()
    return frame.crop(box) if box else frame


class RemoveBgRequest(BaseModel):
    image: str                      # base64 原图
    mode: str = "auto"              # auto / checker / rembg
    quality: str = "best"           # best = birefnet-general-lite / fast = u2netp


class SliceSheetRequest(BaseModel):
    image: str                      # base64 原图
    rows: int | None = None
    cols: int | None = None
    frame_width: int | None = None
    frame_height: int | None = None
    trim: bool = True


@app.post("/v1/remove_bg")
def remove_bg(req: RemoveBgRequest):
    """抠掉背景, 写出真正带 alpha 的 RGBA PNG。"""
    if req.mode not in ("auto", "checker", "rembg"):
        return JSONResponse({"error": "mode 必须是 auto/checker/rembg"}, status_code=400)
    if req.quality not in REMBG_MODELS:
        return JSONResponse({"error": f"quality 必须是 {'/'.join(REMBG_MODELS)}"}, status_code=400)
    img = Image.open(io.BytesIO(base64.b64decode(req.image)))
    evidence, is_checker, extra = None, None, []
    if req.mode == "auto":
        # 按结构证据路由, 不按"抠掉了多少"
        is_checker, evidence = _looks_like_checkerboard(img)
        used = "checker" if is_checker else "rembg"
    else:
        used = req.mode
        if used == "checker":
            # 手动指定也照样取证: 强行对一张照片走 checker 正是白猫翻车的那条路,
            # 抠出来的洞常常与背景连通 (不是闭合的洞), hole_ratio 抓不到, 只有
            # "这压根不是棋盘格"这个证据抓得到。
            is_checker, evidence = _looks_like_checkerboard(img)
    if used == "checker":
        alpha, model = _key_checkerboard(img), None
        if is_checker is False:
            extra.append(f"你指定了 mode=checker, 但这张图不是 FLUX 的假透明棋盘格 "
                         f"({evidence.get('reason')}) —— 亮色背景会顺着边缘连通吃进主体, "
                         f"改用 mode=auto 或 mode=rembg")
    else:
        model, alpha = _rembg_alpha(img, req.quality)
    out = img.convert("RGBA")
    out.putalpha(Image.fromarray(alpha))
    name = _new_name("cut", "png")
    out.save(os.path.join(GENERATED_DIR, name), format="PNG")
    metrics, warning = _alpha_report(img, alpha, extra)
    res = {"file_url": f"/files/{name}", "transparent_ratio": metrics["transparent_ratio"],
           "mode_used": used, "model": model, "metrics": metrics}
    if evidence:
        res["checker_evidence"] = evidence
    if warning:
        log.warning("remove_bg %s: %s", name, warning)
        res["warning"] = warning
    return res


@app.post("/v1/slice_sheet")
def slice_sheet(req: SliceSheetRequest):
    """把排成网格的 sprite sheet 切成单帧 PNG。"""
    img = Image.open(io.BytesIO(base64.b64decode(req.image)))
    W, H = img.size
    if req.rows and req.cols:
        rows, cols = req.rows, req.cols
        fw, fh = W // cols, H // rows
    elif req.frame_width and req.frame_height:
        fw, fh = req.frame_width, req.frame_height
        rows, cols = H // fh, W // fw
    else:
        return JSONResponse({"error": "必须提供 rows+cols 或 frame_width+frame_height"}, status_code=400)
    urls = []
    for r in range(rows):
        for c in range(cols):
            f = img.crop((c * fw, r * fh, (c + 1) * fw, (r + 1) * fh))
            if req.trim:
                f = _trim(f)
            name = _new_name("frame", "png")
            f.save(os.path.join(GENERATED_DIR, name), format="PNG")
            urls.append(f"/files/{name}")
    return {"file_urls": urls}


# ---- 程序化音效 (sfxr/jsfxr 风格, 纯 numpy) ----
# 刻意不走 generate_music: 那是 Stable Audio 扩散模型, 47s 上限、单声道铺成立体声、
# 没有循环点、出来的是宽带糊音。游戏音效是 10~200ms 的瞬态, 要的是精确、即时、可复现,
# 扩散模型是彻底用错了乐器。这里不碰 GPU 也不碰网络, 一次合成 ~10ms。
SFX_RATE = 44100
MAX_SFX_SECONDS = float(os.getenv("MAX_SFX_SECONDS", "5"))
SFX_WAVES = ("square", "saw", "sine", "triangle", "noise")


@dataclass
class SfxParams:
    wave: str = "square"          # square / saw / sine / triangle / noise
    # 包络 (秒): attack 0->1, decay 1->sustain_level, sustain 保持, release ->0
    attack: float = 0.005
    decay: float = 0.03
    sustain: float = 0.06
    sustain_level: float = 0.8
    release: float = 0.10
    base_freq: float = 440.0      # Hz (noise 波形下是采样保持的刷新率)
    freq_slide: float = 0.0       # 八度/秒
    delta_slide: float = 0.0      # 八度/秒^2
    duty: float = 0.5             # 方波占空比
    duty_sweep: float = 0.0       # 占空比变化/秒
    vibrato_depth: float = 0.0    # 半音
    vibrato_speed: float = 0.0    # Hz
    arp_mult: float = 1.0         # arp_time 之后基频乘以它 (金币的两段音阶)
    arp_time: float = 0.0         # 秒
    lpf: float = 1.0              # 低通截止, 归一化 (1 = 不滤)
    lpf_sweep: float = 0.0        # 截止的八度/秒
    hpf: float = 0.0              # 高通截止, 归一化 (0 = 不滤)
    volume: float = 0.95          # 归一化后的峰值


SFX_PRESETS = {
    "jump":      dict(wave="square", base_freq=360, freq_slide=3.0, attack=0.005, decay=0.03,
                      sustain=0.07, sustain_level=0.85, release=0.09, duty=0.5, duty_sweep=0.5),
    "coin":      dict(wave="square", base_freq=988, arp_mult=1.5, arp_time=0.06, attack=0.002,
                      decay=0.012, sustain=0.10, sustain_level=0.9, release=0.22, duty=0.35),
    "hit":       dict(wave="noise", base_freq=3000, freq_slide=-2.5, attack=0.001, decay=0.02,
                      sustain=0.02, sustain_level=0.5, release=0.13, lpf=0.55, lpf_sweep=-2.5),
    "explosion": dict(wave="noise", base_freq=44100, freq_slide=-0.9, attack=0.002, decay=0.10,
                      sustain=0.25, sustain_level=0.8, release=0.85, lpf=0.95, lpf_sweep=-0.5),
    "powerup":   dict(wave="square", base_freq=320, freq_slide=1.2, arp_mult=1.25, arp_time=0.20,
                      attack=0.01, decay=0.05, sustain=0.24, sustain_level=0.85, release=0.24,
                      vibrato_depth=0.35, vibrato_speed=13.0),
    "laser":     dict(wave="saw", base_freq=1500, freq_slide=-3.6, attack=0.001, decay=0.02,
                      sustain=0.05, sustain_level=0.7, release=0.15, hpf=0.02),
    "select":    dict(wave="square", base_freq=880, attack=0.002, decay=0.012, sustain=0.03,
                      sustain_level=0.8, release=0.045, duty=0.25),
    "hurt":      dict(wave="saw", base_freq=520, freq_slide=-1.5, attack=0.002, decay=0.03,
                      sustain=0.05, sustain_level=0.6, release=0.17, lpf=0.7),
}

# seed 抖动的是参数, 不是采样点 —— 同一个 preset 听起来还是它自己, 只是每次略有不同。
_SFX_JITTER = {"base_freq": 0.10, "freq_slide": 0.15, "duty": 0.12, "decay": 0.15,
               "sustain": 0.15, "release": 0.15, "arp_mult": 0.04, "arp_time": 0.15,
               "vibrato_depth": 0.20, "lpf": 0.08}


def _sfx_params(preset, seed=None, overrides=None):
    if preset not in SFX_PRESETS:
        raise ValueError(f"未知 preset: {preset} (可用: {', '.join(SFX_PRESETS)})")
    p = SfxParams(**SFX_PRESETS[preset])
    rng = np.random.default_rng(seed)
    if seed is not None:
        for field, amount in _SFX_JITTER.items():
            v = getattr(p, field)
            if v:
                setattr(p, field, float(v) * float(1.0 + rng.uniform(-amount, amount)))
    for k, v in (overrides or {}).items():
        if not hasattr(p, k):
            raise ValueError(f"未知参数: {k}")
        setattr(p, k, v if k == "wave" else float(v))
    if p.wave not in SFX_WAVES:
        raise ValueError(f"wave 必须是 {'/'.join(SFX_WAVES)}")
    total = p.attack + p.decay + p.sustain + p.release
    if not (0.005 <= total <= MAX_SFX_SECONDS):
        raise ValueError(f"总时长 {total:.3f}s 超出 0.005~{MAX_SFX_SECONDS}s")
    return p, rng


def _sfx_envelope(p, n):
    na = max(1, int(p.attack * SFX_RATE))
    nd = max(1, int(p.decay * SFX_RATE))
    ns = max(0, int(p.sustain * SFX_RATE))
    nr = max(1, n - na - nd - ns)
    sl = float(np.clip(p.sustain_level, 0.0, 1.0))
    env = np.concatenate([
        np.linspace(0.0, 1.0, na, endpoint=False),
        np.linspace(1.0, sl, nd, endpoint=False),
        np.full(ns, sl),
        np.linspace(sl, 0.0, nr),
    ])
    return env[:n] if env.size >= n else np.concatenate([env, np.zeros(n - env.size)])


def _sfx_filters(x, p, t):
    """一阶低通 (可扫频) + 一阶高通。逐样本递归, 无法向量化, 但音效最长几万个样本。"""
    if p.lpf >= 1.0 and not p.lpf_sweep and p.hpf <= 0.0:
        return x
    cut = np.clip(p.lpf * np.exp2(p.lpf_sweep * t), 0.001, 1.0).tolist()
    a = float(np.clip(1.0 - p.hpf, 0.0, 1.0))
    xs, out = x.tolist(), []
    lp = hp = hp_prev_in = 0.0
    for i, s in enumerate(xs):
        lp += cut[i] * (s - lp)
        hp = a * (hp + lp - hp_prev_in)
        hp_prev_in = lp
        out.append(hp)
    return np.asarray(out, dtype=np.float64)


def _sfx_render(p, rng):
    """按参数合成一段单声道 float64 波形 (峰值归一化到 p.volume)。"""
    n = max(2, int(round((p.attack + p.decay + p.sustain + p.release) * SFX_RATE)))
    t = np.arange(n, dtype=np.float64) / SFX_RATE
    octaves = p.freq_slide * t + 0.5 * p.delta_slide * t * t
    if p.vibrato_depth and p.vibrato_speed:
        octaves = octaves + (p.vibrato_depth / 12.0) * np.sin(2 * np.pi * p.vibrato_speed * t)
    f = p.base_freq * np.exp2(octaves)
    if p.arp_mult != 1.0 and p.arp_time > 0:
        f = np.where(t >= p.arp_time, f * p.arp_mult, f)
    # noise 的"频率"是采样保持的刷新率, 可以一直到采样率 (刷新率 = 采样率就是白噪声)
    f = np.clip(f, 10.0, SFX_RATE if p.wave == "noise" else 0.45 * SFX_RATE)
    phase = np.cumsum(f) / SFX_RATE
    frac = phase - np.floor(phase)
    if p.wave == "sine":
        x = np.sin(2 * np.pi * frac)
    elif p.wave == "saw":
        x = 2.0 * frac - 1.0
    elif p.wave == "triangle":
        x = 4.0 * np.abs(frac - 0.5) - 1.0
    elif p.wave == "noise":
        table = rng.uniform(-1.0, 1.0, size=n + 8)     # 够长, 不会在一次音效里循环
        x = table[np.floor(phase).astype(np.int64) % table.size]
    else:                                              # square
        duty = np.clip(p.duty + p.duty_sweep * t, 0.01, 0.99)
        x = np.where(frac < duty, 1.0, -1.0)
    x = _sfx_filters(x * _sfx_envelope(p, n), p, t)
    peak = float(np.max(np.abs(x)))
    if peak > 0:
        x = x * (p.volume / peak)
    return x


def _write_wav(path, x):
    pcm = np.clip(np.round(x * 32767.0), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SFX_RATE)
        w.writeframes(pcm.tobytes())


class SfxRequest(BaseModel):
    preset: str = "select"
    seed: int | None = None                 # 固定 seed -> 逐字节可复现
    overrides: dict | None = None           # 覆盖 SfxParams 的任意字段


@app.post("/v1/gen_sfx")
def gen_sfx(req: SfxRequest):
    """按 sfxr 风格的参数合成一枚游戏音效, 写出 44.1kHz 16bit 单声道 WAV。"""
    try:
        p, rng = _sfx_params(req.preset, req.seed, req.overrides)
        x = _sfx_render(p, rng)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    name = _new_name("sfx", "wav")
    _write_wav(os.path.join(GENERATED_DIR, name), x)
    log.info("sfx: %s preset=%s seed=%s %.3fs", name, req.preset, req.seed, x.size / SFX_RATE)
    return {"file_url": f"/files/{name}", "preset": req.preset, "seed": req.seed,
            "duration": round(x.size / SFX_RATE, 4), "params": asdict(p)}


@app.get("/v1/sfx_presets")
def sfx_presets():
    return {"presets": sorted(SFX_PRESETS), "params": asdict(SfxParams()), "rate": SFX_RATE}


@app.get("/v1/subjects")
async def list_subjects():
    out = []
    for n in _subject_names():
        c = _load_subject(n)
        if c:
            out.append({k: c.get(k) for k in ("name", "kind", "appearance", "created")})
    return {"subjects": out}


@app.get("/v1/subjects/{name}/image")
async def subject_reference(name: str):
    """定妆参考图。定妆之后应该先看一眼, 再拿它出整部戏的图。"""
    safe = os.path.basename(name)
    png, _ = _subject_paths(safe)
    if not os.path.isfile(png):
        return JSONResponse({"error": f"subject '{safe}' 不存在"}, status_code=404)
    return FileResponse(png)


def _drop(paths, kind, name):
    """删掉一个角色。参考音/参考图不可复现 —— 重铸出来是另一个人, 所以这是不可逆的。"""
    gone = [q for q in paths if os.path.isfile(q)]
    if not gone:
        return JSONResponse({"error": f"{kind} '{name}' 不存在"}, status_code=404)
    for q in gone:
        os.remove(q)
    log.info("[%s] 删除 %s (%d 个文件)", kind, name, len(gone))
    return {"deleted": name, "files": len(gone)}


@app.delete("/v1/actors/{name}")
async def delete_actor(name: str):
    safe = os.path.basename(name)
    return _drop(_actor_paths(safe), "actor", safe)


@app.delete("/v1/subjects/{name}")
async def delete_subject(name: str):
    safe = os.path.basename(name)
    return _drop(_subject_paths(safe), "subject", safe)


@app.get("/v1/actors")
async def list_actors():
    out = []
    for n in _actor_names():
        a = _load_actor(n)
        if a:
            out.append({k: a.get(k) for k in ("name", "voice", "transcript", "created")})
    return {"actors": out}


@app.get("/v1/actors/{name}/audio")
async def actor_audio(name: str):
    """角色的参考音。铸声之后应该先听一遍再拿它录整部戏。"""
    safe = os.path.basename(name)
    wav, _ = _actor_paths(safe)
    if not os.path.isfile(wav):
        return JSONResponse({"error": f"actor '{safe}' 不存在"}, status_code=404)
    return FileResponse(wav)


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
