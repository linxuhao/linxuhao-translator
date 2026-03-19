# ==========================================
# 文件名: qwen3-asr/app.py
# 架构定位: Transformers 原生推理 (原生万能解码 + SDPA 物理加速)
# ==========================================
import uvicorn
import logging
from fastapi import FastAPI, UploadFile, File
import subprocess
import numpy as np
import torch
from qwen_asr import Qwen3ASRModel
from transformers.models.whisper.tokenization_whisper import TO_LANGUAGE_CODE

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("qwen3-asr-worker")

app = FastAPI()

logger.info("🚀 Booting Fast ASR Worker on GPU (7800 XT)...")

# 物理隔离与加速引擎
model = Qwen3ASRModel.from_pretrained(
    "Qwen/Qwen3-ASR-1.7B",
    dtype=torch.float16,
    device_map="cuda:0", 
    attn_implementation="sdpa", # 🎯 核心提速 1：强制开启 PyTorch 底层 C++ 融合注意力算子
    max_inference_batch_size=1, 
    max_new_tokens=256
)

logger.info("✅ Fast ASR Worker Ready.")

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
        # 🎯 核心提速 2：释放 GIL 锁与梯度计算，全速推入 GPU
        with torch.inference_mode():
            results = model.transcribe(audio=(y, 16000), language=None)
            
        res = results[0]
        raw_language = (res.language or "unknown").lower()
        text = res.text.strip()
        
        iso_lang = TO_LANGUAGE_CODE.get(raw_language, "unknown")
        
        return {
            "text": text,
            "language": iso_lang
        }
        
    except Exception as e:
        logger.error(f"推理异常: {e}")
        return {"text": "", "language": "unknown", "error": "引擎推理失败"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)