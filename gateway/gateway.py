# ==========================================
# 文件名: gateway/gateway.py
# 架构定位: 增加基于 Cloudflare 身份注入的 SQLite 物理计量探针
# 参考文献: https://developers.cloudflare.com/cloudflare-one/identity/users/validating-users/
# ==========================================
import json
import logging
import time
import sqlite3
import os
from fastapi import FastAPI, UploadFile, File, Form, Response, Header
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("gateway")

app = FastAPI()

BRAIN_URL = "http://vllm_qwen:8000/v1/chat/completions"
ASR_URL = "http://qwen3_asr:8000/asr"

# 🎯 物理层：定义 SQLite 计量数据库路径
DB_PATH = "gateway.db"

def init_db():
    """初始化数据库表，如果不存在则自动创建"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS access_logs (
                username TEXT PRIMARY KEY,
                request_count INTEGER DEFAULT 0,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def record_usage(username: str):
    """极速 UPSERT：存在则 +1，不存在则新建"""
    if not username:
        username = "anonymous" # 兜底本地无 CF 环境的测试
        
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT INTO access_logs (username, request_count, last_active)
            VALUES (?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(username) DO UPDATE SET 
                request_count = request_count + 1,
                last_active = CURRENT_TIMESTAMP
        """, (username,))
        conn.commit()

# 在网关启动时触发数据库物理初始化
@app.on_event("startup")
async def startup_event():
    init_db()
    logger.info("✅ SQLite 计量探针已就绪")

# 挂载子文件夹资源
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
    # 🎯 截获 Cloudflare Access 注入的用户身份头 (通过 alias 强绑定 HTTP Header)
    cf_user: str = Header(None, alias="Cf-Access-Authenticated-User-Email")
):
    req_id = f"REQ-{int(time.time()*1000)}"
    t_start = time.time()
    
    # 触发 SQLite 物理记录
    record_usage(cf_user)
    logger.info(f"[{req_id}] 👤 访客身份: {cf_user or 'Local'} | 计量已更新")
    
    native_lang_base = native_lang.split('-')[0].lower()
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # ----------------------------------
        # 1. 听觉层 (ASR)
        # ----------------------------------
        t_asr_start = time.time()
        files = {'audio_file': (audio_file.filename, await audio_file.read(), audio_file.content_type)}
        asr_resp = await client.post(ASR_URL, files=files)
        t_asr_end = time.time()
        
        if asr_resp.status_code != 200:
            logger.error(f"[{req_id}] ❌ 听觉引擎宕机! 状态码: {asr_resp.status_code}")
            return Response(status_code=500, content=json.dumps({"error": "听觉引擎崩溃"}), media_type="application/json")
            
        asr_data = asr_resp.json()
        asr_text = asr_data.get("text", "").strip()
        input_lang = asr_data.get("language", "unknown").lower()
        logger.info(f"[{req_id}] 👂 ASR 耗时: {int((t_asr_end - t_asr_start)*1000)}ms | 物理鉴定语种: {input_lang} | 文本: '{asr_text}'")

        if not asr_text or len(asr_text) < 1:
            return Response(status_code=400, content=json.dumps({"error": "未能识别有效语音"}), media_type="application/json")

        # ----------------------------------
        # 2. 路由层 - Python 绝对物理接管
        # ----------------------------------
        if input_lang == "unknown" or input_lang == "":
            input_lang = native_lang_base

        if input_lang.startswith(native_lang_base):
            target_tts_lang = last_foreign_lang
            detected_foreign_lang = last_foreign_lang
        else:
            target_tts_lang = native_lang_base
            detected_foreign_lang = input_lang

        # ----------------------------------
        # 3. 大脑层 (Brain) - 注入绝对的语义权重
        # ----------------------------------
        from transformers.models.whisper.tokenization_whisper import LANGUAGES
        t_brain_start = time.time()
        
        target_lang_full_name = LANGUAGES.get(target_tts_lang, target_tts_lang).title()
        instruction = f"将以下句子直接翻译为{target_lang_full_name}。"
        # Prompt 换装：用完整的人类语言名称发号施令
        system_prompt = f"""{instruction}
        必须严格返回JSON格式，禁止输出其他任何字符,:
        {{"text": "纯净的翻译结果"}}"""

        brain_payload = {
            "model": "qwen3",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": asr_text}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0, # 彻底剥离创造力
            "tool_choice": "none",
            "max_tokens": 256
        }

        resp_brain = await client.post(BRAIN_URL, json=brain_payload)

        try:
            content = resp_brain.json()["choices"][0]["message"]["content"]
            trans_text = json.loads(content.replace("```json", "").replace("```", "").strip()).get("text", "")
        except Exception as e:
            logger.error(f"[{req_id}] ❌ 翻译生成异常: {e}")
            return Response(status_code=500, content=json.dumps({"error": "翻译生成异常"}), media_type="application/json")
            
        t_brain_end = time.time()
        logger.info(f"[{req_id}] 🧠 LLM 翻译耗时: {int((t_brain_end-t_brain_start)*1000)}ms | 目标发音: {target_lang_full_name} | 结果: '{trans_text}'")

        # ----------------------------------
        # 4. 组装响应
        # ----------------------------------
        t_end = time.time()
        response_data = {
            "text": trans_text,
            "target_tts_lang": target_tts_lang,
            "detected_foreign_lang": detected_foreign_lang,
            "metrics": {
                "asr_ms": int((t_asr_end - t_asr_start) * 1000),
                "llm_ms": int((t_brain_end - t_brain_start) * 1000),
                "gateway_ms": int((t_end - t_start) * 1000)
            }
        }
        
        return Response(content=json.dumps(response_data), media_type="application/json")