# ==========================================
# 文件名: qwen3-asr/Dockerfile
# 架构定位: 纯净 ROCm 环境 + vllm 多进程并发引擎
# ==========================================
FROM  vllm/vllm-openai-rocm:latest

USER root

#1. 安装系统级音频解码底层库 (FFmpeg 和 libsndfile)
RUN apt-get update && apt-get install -y ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*

#2. 安装 Python 层面的音频接口库
RUN pip install --no-cache-dir soundfile librosa


