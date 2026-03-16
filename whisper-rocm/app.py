# 文件名: whisper-rocm/app.py
# 修复：HuggingFace pipeline 在无时间戳模式下 language 标签隐式输出 null 的问题。已清洗冗余 chunks 数据，仅返回纯净文本，语种动态判定全权交由 30B 翻译大脑。

import torch
from fastapi import FastAPI, UploadFile, File, HTTPException
from transformers import pipeline
import uvicorn
import tempfile
import os

app = FastAPI()

pipe = pipeline(
    "automatic-speech-recognition",
    model="openai/whisper-large-v3",
    torch_dtype=torch.float16,
    device="cuda:0",
    model_kwargs={"attn_implementation": "sdpa"} 
)

@app.post("/asr")
async def transcribe(audio_file: UploadFile = File(...)):
    audio_bytes = await audio_file.read()
    
    # 动态获取前端录音的后缀名（兼容手机端 webm 和本地测试 m4a）
    ext = os.path.splitext(audio_file.filename)[1] or ".tmp"
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
        tmp_file.write(audio_bytes)
        tmp_path = tmp_file.name

    try:
        result = pipe(tmp_path, generate_kwargs={"task": "transcribe"})
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    # 仅返回文本，舍弃失效的 chunk 标签
    return {"text": result["text"]}

if __name__ == "__main__":
    # 注意：对应 docker-compose 的 "9000:8000" 映射
    uvicorn.run(app, host="0.0.0.0", port=8000)