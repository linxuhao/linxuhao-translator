# ==========================================
# 文件名: kokoro-rocm/Dockerfile
# 架构定位: 发声微服务 (TTS) - 基于极速轻量级 Kokoro-82M 模型
# ==========================================
FROM rocm/pytorch:latest

# 1. 固化系统依赖
RUN apt-get update && apt-get install -y espeak-ng ffmpeg && rm -rf /var/lib/apt/lists/*

# 2. 固化 Python 依赖
# 🎯 核心修复：替换官方 phonemizer 为 phonemizer-fork，并用卸载指令确保环境绝对纯净，防止依赖污染。
RUN pip install fastapi uvicorn python-multipart soundfile kokoro "misaki[zh]" phonemizer-fork accelerate && \
    pip uninstall -y phonemizer || true

# 3. 设定工作目录
WORKDIR /app

# 4. 默认启动指令
CMD ["python", "app.py"]