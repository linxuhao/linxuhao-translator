# ==========================================
# 文件名: media-gen/app.py
# 架构定位: media-gen 的 HTTP 外壳 —— 自己不生成任何东西。
#
#   mcp_server (linxuhaserver)  --HTTP 9010, 16 个端点原样-->  本服务
#                                                              |-- MCP over HTTP --> continuity:9030/mcp
#                                                              `-- 直读 /state 提供 /files/ 等下载
#
# 2026-08-21 重写: 生图/配音/抠图/切图/音效/铸声/定妆的全部实现搬到了 continuity
# (dsh-continuity, 以 streamable-http 常驻在同一个 compose 网络里)。本文件只剩三件事:
#   1. 把 HTTP 请求翻译成一次 MCP 工具调用, 再把结构化结果翻译回原来的 JSON 形状;
#   2. 维持异步 job API (POST /v1/jobs -> job_id, GET /v1/jobs/{id} 长轮询);
#   3. 直接从只读挂载的 /state 提供三条下载路径。
#
# 【形状一个字节不许变】mcp-server 是唯一的消费者, 它硬索引一批字段 (file_url /
# job_id / status / actor / subject / deleted / transparent_ratio ...), 改名即 KeyError。
# 而 ~/media_gen_baseline/ 那 93 个用例的行为基线是"迁移没迁坏"的唯一证据 —— 形状一改,
# 基线就废了, 迁移就变成一次无法验证的重写。所以异步 job API 原样保留, 哪怕现在出图
# 只要十几秒、异步看着多余: 先原样搬 (可证明), 要简化是另一轮的事。
#
# 【不许 import continuity_mcp】壳只通过 MCP 协议和 continuity 说话。直接 import 会
# 把"两个进程各自持有自己的显存约束"变成"一个进程里两套逻辑", 而且会让 continuity
# 的版本升级悄悄改变本服务的行为。本文件里 "continuity_mcp" 只出现在 URL 和注释里。
# ==========================================
import asyncio
import base64
import binascii
import json
import logging
import os
import queue
import re
import threading
import time
import uuid
from contextlib import contextmanager

import anyio
import httpx2
from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, ConfigDict, Field

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client, create_mcp_http_client

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("media-gen")

app = FastAPI(title="media-gen", version="0.4.0")

# ---- 配置 ----
CONTINUITY_URL = os.getenv("CONTINUITY_MCP_URL", "http://continuity_mcp:9030/mcp")
# continuity 的状态目录, 在本容器里是只读挂载 —— 写入一律走 MCP。
# 三条下载路径 (/files/, /v1/actors/{n}/audio, /v1/subjects/{n}/image) 直接读它:
# 让文件字节再过一遍 MCP 协议 (base64 进 JSON) 只会白白翻倍内存和延迟。
STATE_DIR = os.getenv("CONTINUITY_STATE_DIR", "/state")
GENERATED_DIR = os.path.join(STATE_DIR, "generated")
ACTORS_DIR = os.path.join(STATE_DIR, "actors")
SUBJECTS_DIR = os.path.join(STATE_DIR, "subjects")

# 三处 base64 入参 (参考图 / 导入的录音 / 导入的图) 在 MCP 那边是"本机路径"参数,
# 所以必须落到两个容器都看得见的地方。本容器对 /state 是只读的, 于是单独再挂一次
# 同一个宿主机目录下的子目录, 可写:
#     宿主机 ./continuity-state/_shell_tmp  ->  本容器 /shell_tmp (rw)
#                                          ->  continuity 容器 /state/_shell_tmp (rw)
# 写用 SHELL_TMP_DIR (本容器的路径), 传给 MCP 的是 SHELL_TMP_REMOTE (对方的路径)。
# 不给 continuity 加挂载, 是因为那要改 compose 里 continuity 那一段。
SHELL_TMP_DIR = os.getenv("SHELL_TMP_DIR", "/shell_tmp")
SHELL_TMP_REMOTE = os.getenv("SHELL_TMP_REMOTE", "/state/_shell_tmp")

VULKAN_DEVICE = os.getenv("VULKAN_DEVICE", "1")

# ⚠️ 【限值耦合】下面四个上限壳自己也要知道 —— 因为 `clamped` 是在 POST /v1/jobs
# 同步返回的, 那时任务还没跑, 拿不到 continuity 的结果。它们必须和 continuity 容器
# 里配的是同一个值, 否则算出来的 clamped 是错的 (而且是静默的错)。
# 对应 continuity 的 config.py: MAX_IMAGE_SIZE / MAX_AUDIO_SECONDS /
# MAX_SPEECH_CHARS / CONTINUITY_MAX_SAMPLE_CHARS。改一边必须改另一边。
MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", "1024"))
MAX_AUDIO_SECONDS = float(os.getenv("MAX_AUDIO_SECONDS", "120"))
MAX_SPEECH_CHARS = int(os.getenv("MAX_SPEECH_CHARS", "200"))
MAX_SAMPLE_CHARS = int(os.getenv("MAX_SAMPLE_CHARS", "45"))
DEFAULT_SAMPLE_TEXT = os.getenv(
    "DEFAULT_SAMPLE_TEXT",
    "江湖路远，人心难测。今日一别，山高水长，来日方长，后会有期。")

JOB_TIMEOUT_S = float(os.getenv("JOB_TIMEOUT_S", "900"))
JOB_RETENTION_S = float(os.getenv("JOB_RETENTION_S", "3600"))

_ACTOR_NAME_RE = re.compile(r"^[\w一-鿿-]{1,40}$")
SUBJECT_KINDS = ("character", "animal", "object")
DEFAULT_SUBJECT_KIND = "character"
REMBG_QUALITIES = ("best", "fast")
JOB_TYPES = ("image", "music", "speech", "actor_create", "subject_create")


# =========================================================
# MCP 客户端
# =========================================================
# 每个请求开一个新会话, 不维护长连接。实测: 新建会话 2ms, 单次调用比复用会话多约 7ms。
# 换来的是"没有需要重连的状态" —— continuity 重启后本服务不需要知道, 下一次调用
# 自己就接上了。长连接的那 7ms 不值得一个连接生命周期管理器。
class ToolFailed(Exception):
    """工具自己报的失败 (structured_content.ok == False)。

    分类只看 error_code, 绝不去正则匹配报错文案 —— 那些文案是 prompt 的一部分,
    随时会被改写, 而匹配失败是静默的 (会把 404 悄悄降级成 500)。
    """

    def __init__(self, message, code=None):
        super().__init__(message)
        self.message = message
        self.code = code


# error_code -> HTTP。缺失一律 500: 宁可把一个本该 400 的错报成 500 (调用方会看到
# 我们不认识它), 也不要猜。
_CODE_STATUS = {"invalid": 400, "not_found": 404, "conflict": 409, "engine_error": 500}


def _status_for(exc):
    return _CODE_STATUS.get(exc.code, 500)


async def _acall(name, args, timeout):
    # 读超时给到 JOB_TIMEOUT_S: 默认 300s 挡不住一次长音乐/冷启动的生图。
    http = create_mcp_http_client(timeout=httpx2.Timeout(30.0, read=timeout))
    async with http:
        async with streamable_http_client(CONTINUITY_URL, http_client=http) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                return await session.call_tool(name, args, read_timeout_seconds=timeout)


def call_tool(_tool, **args):
    """调一次 continuity 的工具, 返回 structured_content。

    工具"业务失败"时协议层的 is_error 是 False —— 判据只有 structured_content["ok"]。
    照着 is_error 写会把每一个 404/409 都当成成功。

    第一个形参带下划线前缀: 它和 **args 共用一个命名空间, 而 args 的键是工具的参数名 ——
    半数工具的第一个参数就叫 name, 撞上时报的是 "got multiple values for argument 'name'",
    跟 MCP 半点关系没有。
    """
    args = {k: v for k, v in args.items() if v is not None}
    res = anyio.run(_acall, _tool, args, JOB_TIMEOUT_S)
    sc = getattr(res, "structured_content", None)
    if sc is None:
        texts = [c.text for c in (res.content or []) if getattr(c, "type", None) == "text"]
        raise RuntimeError(f"continuity 工具 {_tool} 没有返回结构化结果: {' '.join(texts)[:300]}")
    if not sc.get("ok"):
        raise ToolFailed(sc.get("error") or f"{_tool} 失败", sc.get("error_code"))
    return sc


def _flatten(exc):
    """把 ExceptionGroup 摊平成一句能读的话。

    anyio 的 TaskGroup 把真正的错误裹在 ExceptionGroup 里, str() 出来是
    "unhandled errors in a TaskGroup (1 sub-exception)" —— 那句话不含任何信息:
    continuity 容器被重建时 DNS 解析不到, 报的就是它, 和"打错了工具名"长得一模一样。
    实测过一次: 7 个请求连着 500, 而 500 的正文没有一个字说明是名字解析失败。
    """
    seen = []
    def walk(e, depth=0):
        subs = getattr(e, "exceptions", None)
        if subs and depth < 4:
            for s in subs:
                walk(s, depth + 1)
        else:
            seen.append(f"{type(e).__name__}: {e}")
    walk(exc)
    return "; ".join(dict.fromkeys(seen))[:500] or f"{type(exc).__name__}: {exc}"


def _tool_error(exc, fallback_status=500):
    if isinstance(exc, ToolFailed):
        return JSONResponse({"error": exc.message}, status_code=_status_for(exc))
    log.error("continuity 调用失败: %s", _flatten(exc), exc_info=exc)
    return JSONResponse({"error": _flatten(exc)}, status_code=fallback_status)


# =========================================================
# URL / 路径
# =========================================================
# continuity 回的是它自己容器里的绝对路径 (/state/generated/img_....png)。
# 对外的 URL 一律壳自己拼 —— 路径是 continuity 的实现细节, URL 是我们的契约。
def _file_url(path):
    return f"/files/{os.path.basename(path)}" if path else None


def _actor_url(name):
    return f"/v1/actors/{name}/audio"


def _subject_url(name):
    return f"/v1/subjects/{name}/image"


def _actor_names():
    return [a["name"] for a in call_tool("list_actors").get("actors") or []]


def _subject_names():
    return [s["name"] for s in call_tool("list_subjects").get("subjects") or []]


def _actor_meta(name):
    """list_actors 不回 transcript, 从只读挂载的边车 json 里补。"""
    try:
        with open(os.path.join(ACTORS_DIR, name + ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


@contextmanager
def _shared_tmp(data, filename):
    """把一段字节落到两个容器都看得见的临时目录, 交出 continuity 那边的路径。

    文件名用调用方给的那个 (角色名/物件名), 唯一性靠外面套的一层随机目录 ——
    因为 import_actor 会把源文件名写进角色的永久档案 (voice = "(导入自 X.wav)")。
    直接拿 uuid 当文件名, 那份档案里留下的就是一串永远对不上任何东西的十六进制。
    """
    d = os.path.join(SHELL_TMP_DIR, uuid.uuid4().hex)
    os.makedirs(d, exist_ok=True)
    local = os.path.join(d, filename)
    with open(local, "wb") as f:
        f.write(data)
    try:
        yield f"{SHELL_TMP_REMOTE}/{os.path.basename(d)}/{filename}"
    finally:
        try:
            os.remove(local)
            os.rmdir(d)
        except OSError:
            pass


def _sweep_tmp():
    """上次进程被 kill 掉时留下的临时文件。finally 删不掉 SIGKILL。"""
    cutoff = time.time() - 3600
    try:
        entries = os.listdir(SHELL_TMP_DIR)
    except OSError:
        return
    for f in entries:
        p = os.path.join(SHELL_TMP_DIR, f)
        try:
            if os.path.getmtime(p) >= cutoff:
                continue
            if os.path.isdir(p):
                for g in os.listdir(p):
                    os.remove(os.path.join(p, g))
                os.rmdir(p)
            else:
                os.remove(p)
        except OSError:
            pass


# =========================================================
# 任务队列 (单 worker 串行)
# =========================================================
# 串行照旧。continuity 自己也有一把 _gpu_lock, 所以并发在那边只会变成排队 ——
# 但那样 queued/running 的语义就变了 (全都立刻 running), 而基线记的是现在这套。
_jobs = {}
_job_queue = queue.Queue()
_job_lock = threading.Lock()


def _reap_jobs():
    """已结束的作业留够客户端取走的时间就删掉 —— 否则 _jobs 无界增长。调用方须持 _job_lock。"""
    cutoff = time.time() - JOB_RETENTION_S
    for jid in [j for j, v in _jobs.items() if v.get("done_at", float("inf")) < cutoff]:
        del _jobs[jid]


def _image_kwargs(job):
    """引擎参数原样透传。只在非默认时传: 0.3.0 的工具还没有这两个参数,
    而多余的键在那边是被静默忽略的 —— 传了不会错, 只是不生效。"""
    kw = {}
    if job.get("num_inference_steps"):
        kw["num_inference_steps"] = job["num_inference_steps"]
    if job.get("guidance_scale") not in (None, 1.0):
        kw["guidance_scale"] = job["guidance_scale"]
    return kw


def _run_image(job):
    if job.get("subject"):
        # 场景图: 外观由定妆图决定, prompt 只管场景/动作/视角 (continuity 那边叫 scene)
        sc = call_tool("subject_image", subject=job["subject"], scene=job["prompt"],
                       width=job["width"], height=job["height"], seed=job.get("seed"),
                       **_image_kwargs(job))
        return _file_url(sc["path"]), None
    if job.get("image"):
        # 图生图: MCP 那边收的是路径而不是 base64, 所以先落一个共享临时文件
        with _shared_tmp(_b64(job["image"]), "reference.png") as ref:
            sc = call_tool("generate_image", prompt=job["prompt"], width=job["width"],
                           height=job["height"], seed=job.get("seed"),
                           reference_image_path=ref, **_image_kwargs(job))
        return _file_url(sc["path"]), None
    sc = call_tool("generate_image", prompt=job["prompt"], width=job["width"],
                   height=job["height"], seed=job.get("seed"), **_image_kwargs(job))
    return _file_url(sc["path"]), None


def _run_music(job):
    sc = call_tool("generate_music", prompt=job["prompt"], seed=job.get("seed"),
                   duration=job["audio_end_in_s"],
                   num_inference_steps=job.get("num_inference_steps"))
    return _file_url(sc["path"]), None


def _run_speech(job):
    if job.get("actor"):
        sc = call_tool("actor_tts", actor=job["actor"], text=job["prompt"],
                       speaking_rate=job.get("speaking_rate"), seed=job.get("seed"))
    else:
        sc = call_tool("generate_speech", text=job["prompt"], voice=job.get("instruct"),
                       speaking_rate=job.get("speaking_rate"), seed=job.get("seed"))
    return _file_url(sc["path"]), None


def _run_actor_create(job):
    sc = call_tool("create_actor", name=job["actor"], voice=job["instruct"],
                   sample_text=job["prompt"], seed=job.get("seed"),
                   force=job.get("force") or None)
    meta = {"actor": sc["name"], "transcript": sc.get("transcript"),
            "ref_seconds": sc.get("ref_seconds"), "reference_url": _actor_url(sc["name"])}
    if sc.get("warnings"):
        meta["warning"] = "; ".join(sc["warnings"])
    return None, meta


_SUBJECT_TOOL = {"character": "create_character", "animal": "create_animal",
                 "object": "create_object"}


def _run_subject_create(job):
    kind = job["kind"]
    sc = call_tool(_SUBJECT_TOOL[kind], name=job["subject"], appearance=job["prompt"],
                   width=job["width"], height=job["height"], seed=job.get("seed"),
                   force=job.get("force") or None, **_image_kwargs(job))
    return None, {"subject": sc["name"], "kind": sc.get("kind"),
                  "appearance": sc.get("appearance"),
                  "reference_url": _subject_url(sc["name"])}


_RUNNERS = {"image": _run_image, "music": _run_music, "speech": _run_speech,
            "actor_create": _run_actor_create, "subject_create": _run_subject_create}


def _worker():
    while True:
        job_id, job = _job_queue.get()
        with _job_lock:
            _jobs[job_id]["status"] = "running"
        try:
            url, meta = _RUNNERS[job["type"]](job)
            with _job_lock:
                _jobs[job_id].update(status="done", file_url=url, meta=meta,
                                     done_at=time.time())
        except Exception as e:
            log.exception("job %s failed", job_id)
            # ToolFailed 的 message 是 continuity 给调用方的那句话, 原样保留;
            # 其余 (连不上 / 协议错) 摊平, 否则 error 会是一句 "TaskGroup ..." 的废话。
            msg = e.message if isinstance(e, ToolFailed) else _flatten(e)
            with _job_lock:
                _jobs[job_id].update(status="failed", error=msg, done_at=time.time())


threading.Thread(target=_worker, daemon=True).start()


# =========================================================
# 请求体
# =========================================================
# extra="forbid" 六个模型全都要有。Pydantic 默认静默忽略未知字段, 于是一个写错的
# 字段名 (改名后还在传 character= 而不是 subject=) 会让请求"成功"地生成一张完全没
# 用上定妆图的普通图 —— 看起来是 done, 内容是错的。宁可 422。
# 这一层本来就该在壳: 它描述的是本服务的 HTTP 契约, 与 continuity 无关。
class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., description="image / music / speech / actor_create / subject_create")
    prompt: str = ""                  # speech 时是要念的文本; actor_create 时是铸声台词
    actor: str | None = None          # speech: 用哪个角色的音色; actor_create: 角色名
    subject: str | None = None        # image: 用哪个 subject 的外观; subject_create: 名字
    kind: str | None = None           # subject_create: character / animal / object
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


class RemoveBgRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: str                      # base64 原图
    mode: str = "auto"              # auto / checker / rembg
    quality: str = "best"           # best = birefnet-general-lite / fast = u2netp


class SliceSheetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: str                      # base64 原图
    rows: int | None = None
    cols: int | None = None
    frame_width: int | None = None
    frame_height: int | None = None
    trim: bool = True


class SfxRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: str = "select"
    seed: int | None = None                 # 固定 seed -> 逐字节可复现
    overrides: dict | None = None           # 覆盖 SfxParams 的任意字段


class ImportActorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str
    audio: str                      # base64 的 16-bit PCM WAV
    transcript: str                 # 录音里念的是什么 —— 克隆模型要拿它对齐
    force: bool = False


class ImportSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str
    image: str                      # base64 图片
    appearance: str                 # 会被拼进之后每一张场景图的提示词
    kind: str = DEFAULT_SUBJECT_KIND
    force: bool = False


def _b64(s):
    return base64.b64decode(s)


def _err(msg, status):
    return JSONResponse({"error": msg}, status_code=status)


# =========================================================
# 提交 / 轮询
# =========================================================
# 提交时做的那批校验 (400/404/409) 必须留在壳里, 而且必须是同步的: 异步 job API 的
# 形状就是"提交这一步同步告诉你请求本身对不对, 排队之后的失败才走 status=failed"。
# 交给 continuity 的话它们会变成一个 202 + 之后的 500, 那是另一个 API。
@app.post("/v1/jobs")
def submit_job(req: JobRequest):
    if req.type not in _RUNNERS:
        return _err(f"type 必须是 {'/'.join(_RUNNERS)}", 400)
    job = req.model_dump()
    clamped = None
    try:
        if req.type == "subject_create":
            name = (req.subject or "").strip()
            kind = (req.kind or DEFAULT_SUBJECT_KIND).strip()
            if not _ACTOR_NAME_RE.match(name):
                return _err("subject 名只能是字母/数字/下划线/连字符/中文, 1~40 字", 400)
            if kind not in SUBJECT_KINDS:
                return _err(f"kind 必须是 {'/'.join(SUBJECT_KINDS)}", 400)
            if not req.prompt.strip():
                return _err("subject_create 的 prompt 是外观描述, 不能为空", 400)
            if name in _subject_names() and not req.force:
                return _err(f"subject '{name}' 已存在。定妆一次用一辈子, 覆盖会让它之前"
                            f"所有场景图的外观对不上 —— 确实要重定就传 force=true。", 409)
            # width/height 原样交给 continuity: 上限和 256 下限那套 clamp 在它那边,
            # 壳没有第二份。定妆图不报 clamped —— 现在的 API 就不报。
            job["subject"], job["kind"] = name, kind
        elif req.type == "image":
            # 只有上限值得回报, 下限 (引擎的 256 网格) 是 continuity 的内部实现:
            # 它会把出来的图 resize 回调用方要的尺寸, 所以 40x32 拿到的就是 40x32。
            want_w = min(req.width, MAX_IMAGE_SIZE)
            want_h = min(req.height, MAX_IMAGE_SIZE)
            if (want_w, want_h) != (req.width, req.height):
                clamped = {"width": want_w, "height": want_h}
            if req.subject and req.subject not in _subject_names():
                return _err(f"subject '{req.subject}' 不存在 —— 先调 "
                            f"create_character / create_object (name='{req.subject}', "
                            f"appearance='一段外观描述') 定妆, 再用它出场景图。"
                            f"现有: {_subject_names() or '(还没有)'}", 404)
        elif req.type == "actor_create":
            name = (req.actor or "").strip()
            if not _ACTOR_NAME_RE.match(name):
                return _err("actor 名只能是字母/数字/下划线/连字符/中文, 1~40 字", 400)
            if not (req.instruct or "").strip():
                return _err("actor_create 必须给 instruct (声音的自然语言描述)", 400)
            if name in _actor_names() and not req.force:
                return _err(f"actor '{name}' 已存在。铸声一次用一辈子, 覆盖会让它之前"
                            f"所有台词的音色对不上 —— 确实要重铸就传 force=true。", 409)
            job["actor"] = name
            text = (req.prompt or "").strip() or DEFAULT_SAMPLE_TEXT
            job["prompt"] = text[:MAX_SAMPLE_CHARS]
            if len(text) > MAX_SAMPLE_CHARS:
                clamped = {"prompt_chars": MAX_SAMPLE_CHARS,
                           "why": "铸声台词越长, 参考音越长, 之后每一句台词的显存代价越高"}
        elif req.type == "speech":
            text = req.prompt.strip()
            if not text:
                return _err("speech 的 prompt 不能为空", 400)
            if req.actor and req.actor not in _actor_names():
                # 指令式报错: 调用方是 LLM, 告诉它下一步该干什么, 而不是只说"没找到"
                return _err(f"actor '{req.actor}' 不存在 —— 先调 create_actor(name='{req.actor}', "
                            f"voice='一段声音描述') 铸声, 再用它说台词。"
                            f"现有角色: {_actor_names() or '(还没有)'}", 404)
            job["prompt"] = text[:MAX_SPEECH_CHARS]
            if len(text) > MAX_SPEECH_CHARS:
                clamped = {"prompt_chars": MAX_SPEECH_CHARS}
        else:
            job["audio_end_in_s"] = max(1.0, min(float(req.audio_end_in_s), MAX_AUDIO_SECONDS))
            if job["audio_end_in_s"] != req.audio_end_in_s:
                clamped = {"audio_end_in_s": job["audio_end_in_s"]}
    except Exception as e:
        # 存在性检查要打一次 MCP; continuity 不可达时说清楚是谁不可达
        log.exception("提交校验失败")
        return _err(f"continuity 不可用: {_flatten(e)}", 503)
    job_id = uuid.uuid4().hex
    with _job_lock:
        _reap_jobs()
        _jobs[job_id] = {"status": "queued", "file_url": None, "error": None, "meta": None}
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
            if job.get("file_url"):
                out["file_url"] = job["file_url"]
            if job.get("meta"):
                out.update(job["meta"])
            return out
        if job["status"] == "failed":
            return JSONResponse({"status": "failed", "error": job["error"]}, status_code=500)
        if time.time() > deadline:
            return JSONResponse({"status": "timeout"}, status_code=504)
        await asyncio.sleep(1.0)


# =========================================================
# 下载 —— 不走 MCP, 直读只读挂载的 /state
# =========================================================
def _serve(directory, filename, missing):
    safe = os.path.basename(filename)          # 防目录穿越
    path = os.path.join(directory, safe)
    if not os.path.isfile(path):
        return JSONResponse({"error": missing(safe)}, status_code=404)
    return FileResponse(path)


@app.get("/files/{filename}")
async def serve_file(filename: str):
    """下载生成的文件 (图片/音乐), 供远程 agent 直接获取。"""
    return _serve(GENERATED_DIR, filename, lambda _: "not found")


@app.get("/v1/actors/{name}/audio")
async def actor_audio(name: str):
    """角色的参考音。铸声之后应该先听一遍再拿它录整部戏。"""
    return _serve(ACTORS_DIR, name + ".wav", lambda n: f"actor '{n[:-4]}' 不存在")


@app.get("/v1/subjects/{name}/image")
async def subject_reference(name: str):
    """定妆参考图。定妆之后应该先看一眼, 再拿它出整部戏的图。"""
    return _serve(SUBJECTS_DIR, name + ".png", lambda n: f"subject '{n[:-4]}' 不存在")


# =========================================================
# 图像后处理
# =========================================================
@app.post("/v1/remove_bg")
def remove_bg(req: RemoveBgRequest):
    """抠掉背景, 写出真正带 alpha 的 RGBA PNG。"""
    if req.mode not in ("auto", "checker", "rembg"):
        return _err("mode 必须是 auto/checker/rembg", 400)
    if req.quality not in REMBG_QUALITIES:
        return _err(f"quality 必须是 {'/'.join(REMBG_QUALITIES)}", 400)
    try:
        sc = call_tool("remove_bg", image_base64=req.image, mode=req.mode, quality=req.quality)
    except Exception as e:
        return _tool_error(e)
    res = {"file_url": _file_url(sc["path"]),
           "transparent_ratio": sc.get("transparent_ratio"),
           "mode_used": sc.get("mode_used"), "model": sc.get("model")}
    # metrics / checker_evidence 原样透传 (dsh-continuity >= 0.3.1)
    if sc.get("metrics") is not None:
        res["metrics"] = sc["metrics"]
    if sc.get("checker_evidence"):
        res["checker_evidence"] = sc["checker_evidence"]
    if sc.get("warnings"):
        res["warning"] = "; ".join(sc["warnings"])
    return res


@app.post("/v1/slice_sheet")
def slice_sheet(req: SliceSheetRequest):
    """把排成网格的 sprite sheet 切成单帧 PNG。"""
    if not ((req.rows and req.cols) or (req.frame_width and req.frame_height)):
        return _err("必须提供 rows+cols 或 frame_width+frame_height", 400)
    try:
        sc = call_tool("slice_sheet", image_base64=req.image, rows=req.rows, cols=req.cols,
                       frame_width=req.frame_width, frame_height=req.frame_height,
                       trim=req.trim)
    except Exception as e:
        return _tool_error(e)
    return {"file_urls": [_file_url(p) for p in sc.get("paths") or []]}


# =========================================================
# 程序化音效
# =========================================================
@app.post("/v1/gen_sfx")
def gen_sfx(req: SfxRequest):
    """按 sfxr 风格的参数合成一枚游戏音效, 写出 44.1kHz 16bit 单声道 WAV。"""
    try:
        sc = call_tool("gen_sfx", preset=req.preset, seed=req.seed, overrides=req.overrides)
    except Exception as e:
        return _tool_error(e)
    return {"file_url": _file_url(sc["path"]), "preset": req.preset, "seed": req.seed,
            "duration": sc.get("duration"), "params": sc.get("params")}


@app.get("/v1/sfx_presets")
def sfx_presets():
    try:
        try:
            sc = call_tool("sfx_presets")
        except RuntimeError:                 # 工具改了名 (sfx_presets / list_sfx_presets)
            sc = call_tool("list_sfx_presets")
    except Exception as e:
        return _tool_error(e)
    return {"presets": sc.get("presets"), "params": sc.get("params"), "rate": sc.get("rate")}


# =========================================================
# 名册 / 删除
# =========================================================
@app.get("/v1/actors")
def list_actors():
    try:
        actors = call_tool("list_actors").get("actors") or []
    except Exception as e:
        return _tool_error(e)
    out = []
    for a in actors:
        meta = _actor_meta(a["name"])
        out.append({"name": a.get("name"), "voice": a.get("voice"),
                    "transcript": meta.get("transcript"), "created": a.get("created")})
    return {"actors": out}


@app.get("/v1/subjects")
def list_subjects():
    try:
        subjects = call_tool("list_subjects").get("subjects") or []
    except Exception as e:
        return _tool_error(e)
    return {"subjects": [{k: s.get(k) for k in ("name", "kind", "appearance", "created")}
                         for s in subjects]}


def _drop(tool, kind, name, names):
    """删掉一个角色。参考音/参考图不可复现 —— 重铸出来是另一个人, 所以这是不可逆的。"""
    safe = os.path.basename(name)
    try:
        if safe not in names():
            return _err(f"{kind} '{safe}' 不存在", 404)
        sc = call_tool(tool, name=safe)
    except Exception as e:
        return _tool_error(e)
    return {"deleted": sc.get("name") or safe, "files": sc.get("files_removed")}


@app.delete("/v1/actors/{name}")
def delete_actor(name: str):
    return _drop("delete_actor", "actor", name, _actor_names)


@app.delete("/v1/subjects/{name}")
def delete_subject(name: str):
    return _drop("delete_subject", "subject", name, _subject_names)


# =========================================================
# 导入外部素材
# =========================================================
@app.post("/v1/actors/import")
def import_actor(req: ImportActorRequest):
    name = (req.actor or "").strip()
    if not _ACTOR_NAME_RE.match(name):
        return _err("actor 名只能是字母/数字/下划线/连字符/中文, 1~40 字", 400)
    if not (req.transcript or "").strip():
        return _err("必须给 transcript —— 那段录音里念的是什么。"
                    "克隆模型要拿它对齐音频和文字, 写错了音色会明显不对。", 400)
    try:
        audio = _b64(req.audio)
    except (binascii.Error, ValueError) as e:
        return _err(f"读不了这个 WAV: {e}", 400)
    try:
        if name in _actor_names() and not req.force:
            return _err(f"actor '{name}' 已存在。覆盖会让它之前所有台词的"
                        f"音色对不上 —— 确实要换就传 force=true。", 409)
        with _shared_tmp(audio, name + ".wav") as path:
            sc = call_tool("import_actor", name=name, audio_path=path,
                           transcript=req.transcript.strip(), force=req.force or None)
    except Exception as e:
        return _tool_error(e)
    return {"actor": sc["name"], "source_format": sc.get("source_format"),
            "reference_url": _actor_url(sc["name"])}


@app.post("/v1/subjects/import")
def import_subject(req: ImportSubjectRequest):
    name = (req.subject or "").strip()
    if not _ACTOR_NAME_RE.match(name):
        return _err("subject 名只能是字母/数字/下划线/连字符/中文, 1~40 字", 400)
    if req.kind not in SUBJECT_KINDS:
        return _err(f"kind 必须是 {'/'.join(SUBJECT_KINDS)}", 400)
    if not (req.appearance or "").strip():
        return _err("必须给 appearance —— 它会被拼进之后每一张场景图的"
                    "提示词。只有参考图而没有文字描述时, 模型对'这是什么'"
                    "没有着落, 外观照样会漂。", 400)
    try:
        image = _b64(req.image)
    except (binascii.Error, ValueError) as e:
        return _err(f"读不了这张图: {e}", 400)
    try:
        if name in _subject_names() and not req.force:
            return _err(f"subject '{name}' 已存在。覆盖会让它之前所有场景图的"
                        f"外观对不上 —— 确实要换就传 force=true。", 409)
        with _shared_tmp(image, name + ".png") as path:
            sc = call_tool("import_subject", name=name, image_path=path,
                           appearance=req.appearance.strip(), kind=req.kind,
                           force=req.force or None)
    except Exception as e:
        return _tool_error(e)
    return {"subject": sc["name"], "kind": sc.get("kind"),
            "source_size": sc.get("source_size"), "stored_size": sc.get("stored_size"),
            "resized": sc.get("resized"), "reference_url": _subject_url(sc["name"])}


# =========================================================
@app.get("/health")
def health():
    try:
        sc = call_tool("continuity_status")
    except Exception as e:
        return JSONResponse({"status": "degraded", "down": [f"continuity: {e}"]},
                            status_code=503)
    if not sc.get("engines_ok"):
        return JSONResponse({"status": "degraded", "down": sc.get("engines_down") or []},
                            status_code=503)
    # backend/device 描述的是本机这块卡怎么跑的, continuity 不回报它们, 壳自己填。
    return {"status": "ok", "backend": "ggml/vulkan (persistent servers)",
            "device": VULKAN_DEVICE}


_sweep_tmp()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9010)
