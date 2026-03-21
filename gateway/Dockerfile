# ==========================================
# 文件名: gateway/Dockerfile
# 架构定位: 极其轻量的无状态前端与 API 路由节点
# ==========================================
FROM python:3.10-slim

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install fastapi uvicorn httpx python-multipart
CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "5000"]