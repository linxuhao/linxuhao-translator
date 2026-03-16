# ==========================================
# 文件名: gateway/gateway.py
# 核心变更: 将 localhost 修改为 Docker Compose 内网服务发现的 hostname
# ==========================================
import json
from fastapi import FastAPI, UploadFile, File, Form, Response
from fastapi.responses import HTMLResponse
import httpx

app = FastAPI()

# 🎯 核心修复：使用 Docker 内部 DNS 直接互联，无需经过宿主机端口映射
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
                {
                    "role": "system",
                    "content": f"""你是一个智能同传路由器。
                    当前用户的母语是: {native_lang}。
                    对话的另一方（外语）预期是: {last_foreign_lang}。
                    
                    执行逻辑：
                    1. 识别用户输入文本的实际语种。
                    2. 如果输入是母语({native_lang})，将其翻译为 {last_foreign_lang}。
                    3. 如果输入是外语，将其翻译为 {native_lang}，并更新外语语种标签。
                    
                    必须严格返回JSON，格式为: 
                    {{"target_tts_lang": "发音语种代码(如 fr, zh-cn)", "text": "纯净的翻译结果", "detected_foreign_lang": "识别出的外语代码(如 fr, en)"}}"""
                },
                {"role": "user", "content": asr_text}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }
        brain_resp = await client.post(BRAIN_URL, json=brain_payload)
        trans_data = json.loads(brain_resp.json()["choices"][0]["message"]["content"])

        # 3. 发声层
        tts_payload = {
            "text": trans_data["text"],
            "language": trans_data["target_tts_lang"]
        }
        tts_resp = await client.post(TTS_URL, json=tts_payload)
        
        headers = {"X-Foreign-Lang": trans_data["detected_foreign_lang"]}
        return Response(content=tts_resp.content, media_type="audio/wav", headers=headers)