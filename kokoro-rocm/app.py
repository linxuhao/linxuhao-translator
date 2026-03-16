# ==========================================
# 文件名: kokoro-rocm/app.py
# 任务目标: 在 ROCm 环境下运行 Kokoro-82M，提供极低延迟的法/中双语 TTS API
# ==========================================
import os
import io
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn
import soundfile as sf
import numpy as np

# 导入 Kokoro 核心管道
from kokoro import KPipeline

app = FastAPI()

# 预加载法/中双语 Pipeline
# 'z': Mandarin (中文), 'f': French (法语)
# 首次运行会自动从 HuggingFace 极速拉取仅 82M 的权重文件
print("Loading Kokoro-82M Pipelines on ROCm...")
pipelines = {
    "zh-cn": KPipeline(lang_code='z'), 
    "fr": KPipeline(lang_code='f')
}
print("Kokoro Loaded!")

class TTSRequest(BaseModel):
    text: str
    language: str = "zh-cn" # 接收前端路由传来的语种

@app.post("/tts")
async def generate_speech(req: TTSRequest):
    # 动态匹配模型管道
    lang_key = "zh-cn" if "zh" in req.language.lower() else "fr"
    pipe = pipelines.get(lang_key, pipelines["fr"])
    
    # 动态分配顶尖的内置音色
    # zf_xiaoxiao (中文女声), ff_siwis (法语女声)
    voice = 'zf_xiaoxiao' if lang_key == 'zh-cn' else 'ff_siwis' 
    
    # 执行极速流式推理 (生成器模式)
    generator = pipe(req.text, voice=voice, speed=1.0, split_pattern=r'\n+')
    
    audio_data = []
    # 遍历生成器，收集生成的音频片段
    for i, (gs, ps, audio) in enumerate(generator):
        audio_data.extend(audio)
        
    # 将 NumPy 音频数组转化为 24kHz 采样率的 WAV 二进制流
    audio_np = np.array(audio_data)
    wav_io = io.BytesIO()
    sf.write(wav_io, audio_np, 24000, format='WAV')
    wav_bytes = wav_io.getvalue()
    
    # 直接回传纯净的音频二进制数据
    return Response(content=wav_bytes, media_type="audio/wav")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)