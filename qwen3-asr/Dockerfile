# ==========================================
# 文件名: qwen3-asr/Dockerfile
# 架构定位: 搭载阿里官方 qwen-asr 引擎的极速容器
# ==========================================
FROM rocm/pytorch:latest

# 安装 FFmpeg 进行物理音频降维
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# 🎯 核心变更：直接安装官方的 qwen-asr 库，它会自动处理复杂的架构注册
RUN pip install --no-cache-dir transformers uvicorn fastapi python-multipart accelerate torchvision torchaudio qwen-asr

WORKDIR /app
CMD ["python", "app.py"]