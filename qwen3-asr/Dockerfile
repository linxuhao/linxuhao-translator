# ==========================================
# 文件名: qwen3-asr/Dockerfile
# 架构定位: 纯净 ROCm 环境 + Gunicorn 多进程并发引擎
# ==========================================
FROM rocm/pytorch:latest

USER root

# 1. 安装 FFmpeg 进行音频物理降维
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# 2. 安装基础依赖与生产级进程管理器 gunicorn
RUN pip install --no-cache-dir transformers uvicorn gunicorn fastapi python-multipart accelerate torchvision torchaudio qwen-asr

WORKDIR /app

# 🎯 核心并发引擎启动：拉起 3 个 Worker，榨取 7800 XT 显存实现真·并发
CMD ["gunicorn", "app:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "120"]