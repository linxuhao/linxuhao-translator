# ==========================================
# 文件名: gateway/gateway.py
# 架构定位: [Phase 5] 融合流式推流 (SSE) 与优先级队列的任务分发中心
# ==========================================
import json
import logging
import time
import sqlite3
import os
import asyncio
from fastapi import FastAPI, UploadFile, File, Form, Response, Header, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("gateway")

app = FastAPI()

BRAIN_URL = "http://vllm_qwen:8000/v1/chat/completions"
ASR_URL = "http://qwen3_asr:8000/asr"
DB_PATH = "gateway.db"

ADMIN_EMAIL = "linxuhao84@gmail.com"
MAX_CONCURRENT_TASKS = 2  # 严格对齐 ASR
task_queue = asyncio.PriorityQueue()

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS access_logs (
                username TEXT PRIMARY KEY,
                request_count INTEGER DEFAULT 0,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            conn.execute("ALTER TABLE access_logs ADD COLUMN role TEXT DEFAULT 'user'")
        except sqlite3.OperationalError:
            pass
        conn.commit()

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
        """, (username, role))
        conn.commit()

# ==========================================
# 核心算子 1: 传统同步流水线 (SYNC)
# ==========================================
async def execute_translation_pipeline(client: httpx.AsyncClient, payload: dict):
    req_id = payload["req_id"]
    t_start = payload["t_start"]
    audio_bytes = payload["audio_bytes"]
    filename = payload["filename"]
    content_type = payload["content_type"]
    native_lang_base = payload["native_lang_base"]
    last_foreign_lang = payload["last_foreign_lang"]
    is_debug = payload.get("is_debug", False)

    request_logs = []
    def add_log(msg: str, is_error: bool = False):
        if is_error: logger.error(msg)
        else: logger.info(msg)
        if is_debug: request_logs.append(msg)

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
    add_log(f"[{req_id}] 👂 ASR 耗时: {int((t_asr_end - t_asr_start)*1000)}ms | 文本: '{asr_text}'")

    if not asr_text or len(asr_text) < 1:
        return 400, {"error": "未能识别有效语音"}

    if input_lang == "unknown" or input_lang == "": input_lang = native_lang_base
    is_native = (input_lang == native_lang_base)

    if is_native:
        target_tts_lang = last_foreign_lang
        detected_foreign_lang = last_foreign_lang
    else:
        target_tts_lang = native_lang_base
        detected_foreign_lang = input_lang

    from transformers.models.whisper.tokenization_whisper import LANGUAGES
    t_brain_start = time.time()
    
    target_lang_full_name = LANGUAGES.get(target_tts_lang, target_tts_lang).title()
    if target_tts_lang == "zh": target_lang_full_name = "中文-普通话"
        
    system_prompt = f"将user的句子直接翻译为{target_lang_full_name}。\n如果翻译是中文对中文，那么按照输入可能是方言来翻译。\n翻译有礼貌且口语化一些。\n必须严格返回JSON格式，禁止输出其他任何字符,:\n{{\"text\": \"\"}}"
    brain_payload = {
        "model": "qwen3",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": asr_text}],
        "response_format": {"type": "json_object"},
        "temperature": 0.5, "tool_choice": "none", "max_tokens": 256
    }

    resp_brain = await client.post(BRAIN_URL, json=brain_payload)
    try:
        content = resp_brain.json()["choices"][0]["message"]["content"]
        trans_text = json.loads(content.replace("```json", "").replace("```", "").strip()).get("text", "")
    except Exception as e:
        add_log(f"[{req_id}] ❌ 翻译生成异常: {e}", True)
        return 500, {"error": "翻译生成异常"}
        
    t_brain_end = time.time()
    add_log(f"[{req_id}] 🧠 LLM 耗时: {int((t_brain_end-t_brain_start)*1000)}ms | 结果: '{trans_text}'")

    response_data = {
        "original_text": asr_text, "text": trans_text, "target_tts_lang": target_tts_lang,
        "detected_foreign_lang": detected_foreign_lang,
        "metrics": {"asr_ms": int((t_asr_end - t_asr_start) * 1000), "llm_ms": int((t_brain_end - t_brain_start) * 1000), "gateway_ms": int((time.time() - payload["t_start"]) * 1000)},
        "logs": request_logs if is_debug else []
    }
    return 200, response_data

async def execute_stream_pipeline(client: httpx.AsyncClient, payload: dict, chunk_queue: asyncio.Queue):
    req_id = payload["req_id"]
    audio_bytes = payload["audio_bytes"]
    native_lang_base = payload["native_lang_base"]
    last_foreign_lang = payload["last_foreign_lang"]

    try:
        # 1. ASR 听觉层
        t_asr_start = time.time()
        files = {'audio_file': (payload["filename"], audio_bytes, payload["content_type"])}
        asr_resp = await client.post(ASR_URL, files=files)
        
        if asr_resp.status_code != 200:
            raise Exception("ASR Engine Error")
            
        asr_data = asr_resp.json()
        asr_text = asr_data.get("text", "").strip()
        input_lang = asr_data.get("language", "unknown").lower()
        logger.info(f"[{req_id}] 👂 ASR 耗时: {int((time.time() - t_asr_start)*1000)}ms | 文本: '{asr_text}'")

        if not asr_text or len(asr_text) < 1:
            await chunk_queue.put({"event": "end", "reason": "empty_audio"})
            return

        # 2. 路由匹配与语种裁定
        if input_lang == "unknown" or input_lang == "": input_lang = native_lang_base
        is_native = (input_lang == native_lang_base)

        if is_native:
            target_tts_lang = last_foreign_lang
            actual_source_lang = native_lang_base
            detected_foreign_lang = last_foreign_lang # 🎯 锁定环境外语
        else:
            target_tts_lang = native_lang_base
            actual_source_lang = input_lang
            detected_foreign_lang = input_lang # 🎯 捕获环境外语

        from transformers.models.whisper.tokenization_whisper import LANGUAGES
        target_lang_full_name = LANGUAGES.get(target_tts_lang, target_tts_lang).title()
        if target_tts_lang == "zh": target_lang_full_name = "中文-普通话"

        # 推送 UI 占位 (🎯 修复 1：补齐 detected_foreign_lang 字段)
        await chunk_queue.put({
            "event": "start", 
            "original_text": asr_text, 
            "source_lang": actual_source_lang, 
            "target_lang": target_tts_lang,
            "detected_foreign_lang": detected_foreign_lang 
        })

        # 3. vLLM 流式推字 
        system_prompt = f"将user的句子直接翻译为{target_lang_full_name}。\n如果翻译是同语言，那么按照输入可能是方言来翻译。\n翻译有礼貌且口语化一些。\n必须严格返回翻译结果，禁止输出其他任何字符"
        brain_payload = {
            "model": "qwen3",
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": asr_text}],
            "stream": True, "temperature": 0.5, "max_tokens": 256
        }

        full_trans_text = "" # 🎯 准备拼接字符串
        async with client.stream("POST", BRAIN_URL, json=brain_payload) as r:
            async for line in r.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        data_json = json.loads(line[6:])
                        delta = data_json["choices"][0]["delta"].get("content", "")
                        if delta: 
                            full_trans_text += delta # 🎯 内存拼接
                            await chunk_queue.put({"event": "token", "text": delta})
                    except Exception:
                        pass
                        
        await chunk_queue.put({"event": "end", "target_lang": target_tts_lang})
        # 🎯 修复 2：在流式结束后，统一打印一次完整 Log
        logger.info(f"[{req_id}] 🧠 LLM 流式推字完毕 | 目标: {target_lang_full_name} | 结果: '{full_trans_text}'")
        
    except Exception as e:
        logger.error(f"[{req_id}] 💥 Stream 崩溃: {e}")
        await chunk_queue.put({"event": "error", "message": str(e)})
    finally:
        await chunk_queue.put(None)

# ==========================================
# 消费者调度 Worker
# ==========================================
async def voice_worker(worker_id: int):
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            # 兼容多态路由 (SYNC/STREAM)
            item = await task_queue.get()
            priority, ts, task_type, target_obj, payload = item
            
            try:
                if task_type == "SYNC":
                    future = target_obj
                    if future.cancelled(): continue
                    logger.info(f"[Worker-{worker_id}] 🚀 同步处理: {payload['req_id']} | P{priority}")
                    status_code, response_data = await execute_translation_pipeline(client, payload)
                    if not future.cancelled(): future.set_result((status_code, response_data))
                
                elif task_type == "STREAM":
                    chunk_queue = target_obj
                    logger.info(f"[Worker-{worker_id}] 🌊 流式推演: {payload['req_id']} | P{priority}")
                    await execute_stream_pipeline(client, payload, chunk_queue)
                    
            except Exception as e:
                logger.error(f"[Worker-{worker_id}] 💥 崩溃: {e}")
                if task_type == "SYNC" and not target_obj.cancelled(): target_obj.set_exception(e)
            finally:
                task_queue.task_done()

@app.on_event("startup")
async def startup_event():
    init_db()
    for i in range(MAX_CONCURRENT_TASKS):
        asyncio.create_task(voice_worker(i))
    logger.info(f"✅ 已拉起 {MAX_CONCURRENT_TASKS} 个算力调度消费者")

app.mount("/resources", StaticFiles(directory="resources"), name="resources")

@app.get("/")
async def serve_frontend():
    with open("index.html", "r", encoding="utf-8") as f: return HTMLResponse(f.read())

def verify_admin(cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")):
    if cf_user != ADMIN_EMAIL: raise HTTPException(status_code=403, detail="Forbidden")
    return cf_user

@app.get("/api/me")
async def get_my_profile(cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")):
    return {"email": cf_user, "role": 'admin' if cf_user == ADMIN_EMAIL else 'user'}

@app.get("/admin")
async def serve_admin_page(admin_user: str = Depends(verify_admin)):
    with open("admin.html", "r", encoding="utf-8") as f: return HTMLResponse(f.read())

@app.get("/api/admin/users")
async def get_users_list(admin_user: str = Depends(verify_admin)):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM access_logs ORDER BY role ASC, last_active DESC").fetchall()
        return [dict(r) for r in rows]

@app.post("/api/admin/set_vip")
async def set_user_vip(username: str = Form(...), is_vip: str = Form(...), admin_user: str = Depends(verify_admin)):
    target_role = 'vip' if is_vip.lower() == 'true' else 'user'
    if username == ADMIN_EMAIL: target_role = 'admin'
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE access_logs SET role = ? WHERE username = ?", (target_role, username))
        conn.commit()
    return {"status": "ok"}

def get_user_priority(cf_user: str):
    role = 'user'
    if cf_user == ADMIN_EMAIL:
        role = 'admin'
    else:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("SELECT role FROM access_logs WHERE username = ?", (cf_user or "anonymous",)).fetchone()
            if row: role = row[0]
    return 1 if role in ['admin', 'vip'] else 2

@app.post("/api/voice")
async def process_voice(
    audio_file: UploadFile = File(...), native_lang: str = Form("zh"), 
    last_foreign_lang: str = Form("fr"), debug: str = Form("false"),
    cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")
):
    req_id = f"REQ-{int(time.time()*1000)}"
    record_usage(cf_user)
    priority = get_user_priority(cf_user)
    payload = {
        "req_id": req_id, "t_start": time.time(), "audio_bytes": await audio_file.read(),
        "filename": audio_file.filename, "content_type": audio_file.content_type,
        "native_lang_base": native_lang.split('-')[0].lower(), "last_foreign_lang": last_foreign_lang,
        "is_debug": debug.lower() == "true", "cf_user": cf_user
    }
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    await task_queue.put((priority, time.time(), "SYNC", future, payload))
    try:
        status_code, response_data = await future
        return Response(status_code=status_code, content=json.dumps(response_data), media_type="application/json")
    except Exception as e:
        return Response(status_code=500, content=json.dumps({"error": str(e)}), media_type="application/json")

@app.post("/api/stream_voice")
async def stream_voice(
    audio_file: UploadFile = File(...), native_lang: str = Form("zh"), 
    last_foreign_lang: str = Form("fr"), cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")
):
    req_id = f"REQ-{int(time.time()*1000)}"
    record_usage(cf_user)
    priority = get_user_priority(cf_user)
    payload = {
        "req_id": req_id, "audio_bytes": await audio_file.read(),
        "filename": audio_file.filename, "content_type": audio_file.content_type,
        "native_lang_base": native_lang.split('-')[0].lower(), "last_foreign_lang": last_foreign_lang,
    }
    chunk_queue = asyncio.Queue()
    await task_queue.put((priority, time.time(), "STREAM", chunk_queue, payload))
    
    async def event_generator():
        while True:
            chunk = await chunk_queue.get()
            if chunk is None: break
            yield f"data: {json.dumps(chunk)}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")