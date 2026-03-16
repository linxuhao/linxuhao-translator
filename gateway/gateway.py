# ==========================================
# 文件名: gateway/gateway.py
# 任务目标: 剥离 TTS，保留全链路毫秒级追踪日志，返回纯 JSON
# ==========================================
import json
import logging
import time
from fastapi import FastAPI, UploadFile, File, Form, Response
from fastapi.responses import HTMLResponse
import httpx

# 配置日志输出格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("gateway")

app = FastAPI()

BRAIN_URL = "http://vllm_qwen:8000/v1/chat/completions"
ASR_URL = "http://whisper_rocm:8000/asr"
# 🎯 移除了 TTS_URL

@app.get("/")
async def serve_frontend():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.post("/api/voice")
async def process_voice(
    audio_file: UploadFile = File(...),
    native_lang: str = Form("zh-cn"),
    last_foreign_lang: str = Form("fr")
):
    req_id = f"REQ-{int(time.time()*1000)}"
    logger.info(f"========== [{req_id}] 新请求切入 ==========")
    logger.info(f"[{req_id}] 状态: 母语={native_lang}, 预期外语={last_foreign_lang}")
    
    t_start = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        # ----------------------------------
        # 1. 听觉层 (ASR)
        # ----------------------------------
        t_asr_start = time.time()
        files = {'audio_file': (audio_file.filename, await audio_file.read(), audio_file.content_type)}
        asr_resp = await client.post(ASR_URL, files=files)
        asr_text = asr_resp.json().get("text", "")
        t_asr_end = time.time()
        
        logger.info(f"[{req_id}] 👂 ASR 耗时: {int((t_asr_end - t_asr_start)*1000)}ms | 识别文本: '{asr_text}'")

        if not asr_text.strip():
            logger.warning(f"[{req_id}] ⚠️ 未识别到有效语音，请求终止。")
            return Response(status_code=400, content="未能识别有效语音")

        # ----------------------------------
        # 2. 大脑层 (Brain)
        # ----------------------------------
        t_brain_start = time.time()
        system_prompt = f"""你是一个核心翻译路由器。
        【当前参数】母语: {native_lang} | 环境外语: {last_foreign_lang}
        
        【严格处理规则】
        1. 语种鉴定：分析用户的输入。
        2. 若输入是母语 ({native_lang})：翻译成环境外语。detected_foreign_lang 必须原样输出 "{last_foreign_lang}"，绝不可瞎编。
        3. 若输入是某种外语：翻译成母语 ({native_lang})。将 detected_foreign_lang 更新为你识别出的这门外语的简码 (如 fr, es, en)。
        
        必须只返回严格的JSON: {{"target_tts_lang": "最终要发音的语种代码", "text": "纯净翻译文本", "detected_foreign_lang": "按照规则得出的环境外语"}}"""

        brain_payload = {
            "model": "qwen3",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": asr_text}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "tool_choice": "none"
        }
        
        logger.info(f"[{req_id}] 🧠 LLM Payload 发送: {json.dumps(brain_payload, ensure_ascii=False)}")
        
        brain_resp = await client.post(BRAIN_URL, json=brain_payload)
        resp_json = brain_resp.json()
        
        try:
            message = resp_json["choices"][0]["message"]
            raw_content = message.get("content") or message.get("reasoning")
            clean_content = raw_content.replace("```json", "").replace("```", "").strip()
            trans_data = json.loads(clean_content)
        except Exception as e:
            logger.error(f"[{req_id}] ❌ LLM 解析失败: {str(e)} | 原始响应: {json.dumps(resp_json, ensure_ascii=False)}")
            return Response(status_code=500, content="大脑解析异常")
            
        t_brain_end = time.time()
        logger.info(f"[{req_id}] 🧠 LLM 耗时: {int((t_brain_end - t_brain_start)*1000)}ms | 解析结果: {json.dumps(trans_data, ensure_ascii=False)}")

        # ----------------------------------
        # 3. 收尾组装 (剥离后端发声)
        # ----------------------------------
        t_end = time.time()
        logger.info(f"[{req_id}] 🗼 网关内部总耗时: {int((t_end - t_start)*1000)}ms")
        logger.info(f"========== [{req_id}] 请求结束 ==========\n")

        # 🎯 直接将所有探针数据打包在 JSON 中给前端
        response_data = {
            "text": trans_data["text"],
            "target_tts_lang": trans_data["target_tts_lang"],
            "detected_foreign_lang": trans_data["detected_foreign_lang"],
            "metrics": {
                "asr_ms": int((t_asr_end - t_asr_start) * 1000),
                "llm_ms": int((t_brain_end - t_brain_start) * 1000),
                "gateway_ms": int((t_end - t_start) * 1000)
            }
        }
        
        return Response(content=json.dumps(response_data), media_type="application/json")