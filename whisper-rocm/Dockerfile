# 文件名: Dockerfile.whisper
# 任务目标: 固化底层环境，实现秒级热启动

FROM rocm/pytorch:latest

# 1. 固化系统依赖 (安装完无情清理缓存，减小镜像体积)
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# 2. 固化 Python 依赖
RUN pip install transformers uvicorn fastapi python-multipart soundfile librosa accelerate

# 3. 设定工作目录
WORKDIR /app

# 4. 默认启动指令
CMD ["python", "app.py"]