# ==========================================
# 文件名: gateway/gateway.py
# 架构定位: [核心重构] 基于 Future 模式的异步优先级调度中心与 Admin 鉴权体系
# ==========================================
import json
import logging
import time
import sqlite3
import os
import asyncio
from fastapi import FastAPI, UploadFile, File, Form, Response, Header, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("gateway")

app = FastAPI()

BRAIN_URL = "http://vllm_qwen:8000/v1/chat/completions"
ASR_URL = "http://qwen3_asr:8000/asr"
DB_PATH = "gateway.db"

# 🎯 全局配置与调度中心
ADMIN_EMAIL = "linxuhao84@gmail.com"
MAX_CONCURRENT_TASKS = 2  # 物理防线：绝对锁定对齐 ASR 的 2 个 Worker
task_queue = asyncio.PriorityQueue()

# ==========================================
# 1. 数据库基建与无损扩容 (Migration)
# ==========================================
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS access_logs (
                username TEXT PRIMARY KEY,
                request_count INTEGER DEFAULT 0,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 平滑扩容：尝试注入 role 字段（如果已存在则忽略异常）
        try:
            conn.execute("ALTER TABLE access_logs ADD COLUMN role TEXT DEFAULT 'user'")
        except sqlite3.OperationalError:
            pass
        conn.commit()

# ==========================================
# 局部替换: gateway/gateway.py
# 架构定位: 修复 DB 写入逻辑，强行覆盖历史 role
# ==========================================
def record_usage(username: str):
    if not username:
        username = "anonymous" 
        
    role = 'admin' if username == ADMIN_EMAIL else 'user'
        
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO access_logs (username, request_count, last_active, role)
            VALUES (?, 1, CURRENT_TIMESTAMP, ?)
            ON CONFLICT(username) DO UPDATE SET 
                request_count = request_count + 1,
                last_active = CURRENT_TIMESTAMP,
                role = excluded.role
        """, (username, role)) # 🎯 使用 excluded.role 强行覆盖历史权限
        conn.commit()

# ==========================================
# 2. Worker 引擎核心流水线 (The Execution Pipeline)
# ==========================================
async def execute_translation_pipeline(client: httpx.AsyncClient, payload: dict):
    req_id = payload["req_id"]
    t_start = payload["t_start"]
    audio_bytes = payload["audio_bytes"]
    filename = payload["filename"]
    content_type = payload["content_type"]
    native_lang_base = payload["native_lang_base"]
    last_foreign_lang = payload["last_foreign_lang"]
    is_debug = payload["is_debug"]
    cf_user = payload["cf_user"]

    request_logs = []
    def add_log(msg: str, is_error: bool = False):
        if is_error: logger.error(msg)
        else: logger.info(msg)
        if is_debug: request_logs.append(msg)

    # 1. ASR 听觉层
    t_asr_start = time.time()
    files = {'audio_file': (filename, audio_bytes, content_type)}
    asr_resp = await client.post(ASR_URL, files=files)
    t_asr_end = time.time()
    
    if asr_resp.status_code != 200:
        add_log(f"[{req_id}] ❌ 听觉引擎宕机! 状态码: {asr_resp.status_code}", True)
        return 500, {"error": "听觉引擎崩溃"}
        
    asr_data = asr_resp.json()
    asr_text = asr_data.get("text", "").strip()
    input_lang = asr_data.get("language", "unknown").lower()
    add_log(f"[{req_id}] 👂 ASR 耗时: {int((t_asr_end - t_asr_start)*1000)}ms | 鉴定语种: {input_lang} | 文本: '{asr_text}'")

    if not asr_text or len(asr_text) < 1:
        return 400, {"error": "未能识别有效语音"}

    # 2. 路由匹配
    if input_lang == "unknown" or input_lang == "":
        input_lang = native_lang_base

    is_native = (input_lang == native_lang_base)

    if is_native:
        target_tts_lang = last_foreign_lang
        detected_foreign_lang = last_foreign_lang
    else:
        target_tts_lang = native_lang_base
        detected_foreign_lang = input_lang

    # 3. 大脑层 (Brain)
    from transformers.models.whisper.tokenization_whisper import LANGUAGES
    t_brain_start = time.time()
    
    target_lang_full_name = LANGUAGES.get(target_tts_lang, target_tts_lang).title()
    if target_tts_lang == "zh":
        target_lang_full_name = "中文-普通话"
        
    instruction = f"将user的句子直接翻译为{target_lang_full_name}。"
    system_prompt = f"""{instruction}
如果翻译是中文对中文，那么按照输入可能是方言来翻译。
翻译有礼貌且口语化一些。
必须严格返回JSON格式，禁止输出其他任何字符,:
{{"text": ""}}"""

    brain_payload = {
        "model": "qwen3",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": asr_text}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.5, 
        "tool_choice": "none",
        "max_tokens": 256
    }

    resp_brain = await client.post(BRAIN_URL, json=brain_payload)

    try:
        content = resp_brain.json()["choices"][0]["message"]["content"]
        trans_text = json.loads(content.replace("```json", "").replace("```", "").strip()).get("text", "")
    except Exception as e:
        add_log(f"[{req_id}] ❌ 翻译生成异常: {e}", True)
        return 500, {"error": "翻译生成异常"}
        
    t_brain_end = time.time()
    add_log(f"[{req_id}] 🧠 LLM 耗时: {int((t_brain_end-t_brain_start)*1000)}ms | 目标: {target_lang_full_name} | 结果: '{trans_text}'")

    # 4. 组装组装响应
    t_end = time.time()
    response_data = {
        "original_text": asr_text,
        "text": trans_text,
        "target_tts_lang": target_tts_lang,
        "detected_foreign_lang": detected_foreign_lang,
        "metrics": {
            "asr_ms": int((t_asr_end - t_asr_start) * 1000),
            "llm_ms": int((t_brain_end - t_brain_start) * 1000),
            "gateway_ms": int((t_end - t_start) * 1000)
        },
        "logs": request_logs if is_debug else []
    }
    return 200, response_data

# ==========================================
# 3. 后台消费者协程 (The Async Worker)
# ==========================================
async def voice_worker(worker_id: int):
    """从优先队列中提取任务并分发给算力引擎"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            # item = (priority, timestamp, future_id, future, payload)
            item = await task_queue.get()
            priority, ts, f_id, future, payload = item
            
            if future.cancelled():
                task_queue.task_done()
                continue
                
            try:
                logger.info(f"[Worker-{worker_id}] 🚀 开始处理任务: {payload['req_id']} | 优先级: P{priority}")
                status_code, response_data = await execute_translation_pipeline(client, payload)
                if not future.cancelled():
                    future.set_result((status_code, response_data))
            except Exception as e:
                logger.error(f"[Worker-{worker_id}] 💥 任务执行崩溃: {e}")
                if not future.cancelled():
                    future.set_exception(e)
            finally:
                task_queue.task_done()

@app.on_event("startup")
async def startup_event():
    init_db()
    logger.info("✅ SQLite 计量探针已就绪")
    
    # 启动固定数量的 Worker，锁死并发上限
    for i in range(MAX_CONCURRENT_TASKS):
        asyncio.create_task(voice_worker(i))
    logger.info(f"✅ 已拉起 {MAX_CONCURRENT_TASKS} 个算力调度消费者")

# ==========================================
# 4. 前端路由与入口网关 (The Gateway & Future Await)
# ==========================================
app.mount("/resources", StaticFiles(directory="resources"), name="resources")

@app.get("/")
async def serve_frontend():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.post("/api/voice")
async def process_voice(
    audio_file: UploadFile = File(...),
    native_lang: str = Form("zh"), 
    last_foreign_lang: str = Form("fr"),
    debug: str = Form("false"),
    cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")
):
    req_id = f"REQ-{int(time.time()*1000)}"
    t_start = time.time()
    
    record_usage(cf_user)
    
    # 🎯 鉴别身份分配优先级 (Priority)
    role = 'user'
    
    # 物理防线：内存级绝对判定，无视 SQLite 历史脏数据
    if cf_user == ADMIN_EMAIL:
        role = 'admin'
    else:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute("SELECT role FROM access_logs WHERE username = ?", (cf_user or "anonymous",))
            row = cursor.fetchone()
            if row:
                role = row[0]
            
    # VIP/Admin 权重为 1，普通用户权重为 2 (数字越小越优先)
    priority = 1 if role in ['admin', 'vip'] else 2
    logger.info(f"[{req_id}] 👤 身份: {cf_user or 'Local'} ({role}) | 注入优先级: P{priority}")
    # 因为 HTTP 接口要挂起，必须提前将数据从 Buffer 读出
    audio_bytes = await audio_file.read()
    
    payload = {
        "req_id": req_id,
        "t_start": t_start,
        "audio_bytes": audio_bytes,
        "filename": audio_file.filename,
        "content_type": audio_file.content_type,
        "native_lang_base": native_lang.split('-')[0].lower(),
        "last_foreign_lang": last_foreign_lang,
        "is_debug": debug.lower() == "true",
        "cf_user": cf_user
    }
    
    # 🎯 Future Promise 模式挂起
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    
    # 将任务推入优先队列 (使用 id(future) 防止相同时间戳的对象比较报错)
    await task_queue.put((priority, time.time(), id(future), future, payload))
    
    try:
        # 挂起 HTTP 连接，等待 Worker 将结果写入 future
        status_code, response_data = await future
        return Response(status_code=status_code, content=json.dumps(response_data), media_type="application/json")
    except Exception as e:
        return Response(status_code=500, content=json.dumps({"error": str(e)}), media_type="application/json")


# ==========================================
# 5. Admin API (安全防线与路由隔离)
# ==========================================
def verify_admin(cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")):
    """物理硬编码鉴权防线"""
    if cf_user != ADMIN_EMAIL:
        logger.warning(f"🚨 非法提权尝试: {cf_user} 试图访问 Admin 路由")
        raise HTTPException(status_code=403, detail="Forbidden: You are not an administrator.")
    return cf_user

# ==========================================
# 局部增加: gateway/gateway.py
# 架构定位: 提供给纯静态前端的身份嗅探探针
# ==========================================
@app.get("/api/me")
async def get_my_profile(cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")):
    # 物理防线：绝对内存判定
    role = 'user'
    if cf_user == ADMIN_EMAIL:
        role = 'admin'
    return {"email": cf_user, "role": role}

@app.get("/admin")
async def serve_admin_page(admin_user: str = Depends(verify_admin)):
    with open("admin.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/api/admin/users")
async def get_users_list(admin_user: str = Depends(verify_admin)):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM access_logs ORDER BY role ASC, last_active DESC").fetchall()
        return [dict(r) for r in rows]

@app.post("/api/admin/set_vip")
async def set_user_vip(
    username: str = Form(...), 
    is_vip: str = Form(...), 
    admin_user: str = Depends(verify_admin)
):
    target_role = 'vip' if is_vip.lower() == 'true' else 'user'
    # 终极保护：不能降级 Admin 自己
    if username == ADMIN_EMAIL: 
        target_role = 'admin'
        
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE access_logs SET role = ? WHERE username = ?", (target_role, username))
        conn.commit()
    logger.info(f"🛡️ Admin {admin_user} 修改了权限: {username} -> {target_role}")
    return {"status": "ok", "username": username, "role": target_role}