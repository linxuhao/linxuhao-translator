# ==========================================
# 文件名: qwen3-asr/app.py
# 架构定位: Qwen3-ASR 官方包实现，附带短码物理转换器
# ==========================================
import uvicorn
from fastapi import FastAPI, UploadFile, File
import subprocess
import numpy as np
import torch
from qwen_asr import Qwen3ASRModel

# 🎯 核心变更：直接白嫖 transformers 内部的标准语种字典
from transformers.models.whisper.tokenization_whisper import TO_LANGUAGE_CODE

app = FastAPI()

print("🚀 Loading Qwen3-ASR-1.7B on ROCm via official qwen-asr package...")

# 🎯 使用官方封装类，完美规避架构不识别的问题。使用 float16 适配 ROCm。
model = Qwen3ASRModel.from_pretrained(
    "Qwen/Qwen3-ASR-1.7B",
    dtype=torch.float16,
    device_map="cuda:0",
    max_inference_batch_size=1,
    max_new_tokens=256
)

print("✅ Qwen3-ASR 官方工业引擎就绪。")

def decode_audio(audio_bytes: bytes) -> np.ndarray:
    process = subprocess.Popen(
        ['ffmpeg', '-i', 'pipe:0', '-f', 's16le', '-ac', '1', '-ar', '16000', 'pipe:1'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL
    )
    out, _ = process.communicate(input=audio_bytes)
    return np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768.0

@app.post("/asr")
async def transcribe(audio_file: UploadFile = File(...)):
    audio_bytes = await audio_file.read()
    
    try:
        y = decode_audio(audio_bytes)
    except Exception as e:
        return {"text": "", "language": "unknown", "error": f"FFmpeg 解码失败: {str(e)}"}
    
    if len(y) < 1600:
        return {"text": "", "language": "unknown"}

    try:
        results = model.transcribe(audio=(y, 16000), language=None)
        
        res = results[0]
        # Qwen 吐出的是首字母大写的英文全称 (如 "Chinese", "Spanish")，必须转小写
        raw_language = (res.language or "unknown").lower()
        text = res.text.strip()
        
        # 🎯 查表：将 "chinese" 完美映射为 "zh"，支持全球 99 种语言
        iso_lang = TO_LANGUAGE_CODE.get(raw_language, "unknown")
        
        return {
            "text": text,
            "language": iso_lang
        }
        
    except Exception as e:
        print(f"推理异常: {e}")
        return {"text": "", "language": "unknown", "error": "引擎推理失败"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)