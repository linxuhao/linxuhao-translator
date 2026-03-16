# 文件名: gateway/gateway.py
# 修复：兼容 vLLM 的 reasoning 字段提取，确保在开启 reasoning-parser 时依然能获取翻译结果。

import json
import logging
from fastapi import FastAPI, UploadFile, File, Form, Response
from fastapi.responses import HTMLResponse
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")

app = FastAPI()

BRAIN_URL = "http://vllm_qwen:8000/v1/chat/completions"
ASR_URL = "http://whisper_rocm:8000/asr"
TTS_URL = "http://kokoro_rocm:8000/tts"

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
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. 听觉层
        files = {'audio_file': (audio_file.filename, await audio_file.read(), audio_file.content_type)}
        asr_resp = await client.post(ASR_URL, files=files)
        asr_text = asr_resp.json().get("text", "")

        if not asr_text.strip():
            return Response(status_code=400, content="未能识别有效语音")

        # 2. 大脑层
        brain_payload = {
            "model": "qwen3",
            "messages": [
                {"role": "system", "content": f"你是一个同传机器人。中法互译。输入母语({native_lang})译为外语({last_foreign_lang})，反之亦然。必须严格返回JSON格式: {{\"target_tts_lang\": \"语种\", \"text\": \"翻译结果\", \"detected_foreign_lang\": \"语种\"}}。禁止返回其他内容。"},
                {"role": "user", "content": asr_text}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "tool_choice": "none" 
        }
        
        brain_resp = await client.post(BRAIN_URL, json=brain_payload)
        resp_json = brain_resp.json()
        
        try:
            message = resp_json["choices"][0]["message"]
            
            # 🎯 核心逻辑升级：双字段提取
            # 先拿 content，如果 content 为空就拿 reasoning
            raw_content = message.get("content") or message.get("reasoning")
            
            if not raw_content:
                logger.error(f"无法从响应中找到有效内容。原始数据: {resp_json}")
                return Response(status_code=500, content="大脑未生成翻译内容")
            
            # 兼容处理：如果 reasoning 中带有 Markdown 代码块标签，先清洗
            clean_content = raw_content.replace("```json", "").replace("```", "").strip()
            trans_data = json.loads(clean_content)
            
        except Exception as e:
            logger.error(f"解析失败: {str(e)}, 原始内容: {resp_json}")
            return Response(status_code=500, content="翻译大脑格式化异常")

        # 3. 发声层
        tts_payload = {
            "text": trans_data["text"],
            "language": trans_data["target_tts_lang"]
        }
        tts_resp = await client.post(TTS_URL, json=tts_payload)
        
        headers = {"X-Foreign-Lang": trans_data["detected_foreign_lang"]}
        return Response(content=tts_resp.content, media_type="audio/wav", headers=headers)