# ==========================================
# 文件名: media-gen/Dockerfile
# 架构定位: 一层薄壳。对外是原来那 16 个 HTTP 端点, 对内通过 MCP over HTTP
# 调用 continuity 服务 (dsh-continuity)。
#
# 2026-08-21: 迁移成薄壳之后, 这个镜像里的下面这些东西全部删掉了 ——
#   - mesa-vulkan-drivers / libvulkan1: 壳一行 GPU 代码都不跑, 生图配音都在
#     continuity 那边。compose 里对应的 devices / group_add 也一并删了。
#   - numpy / pillow / rembg / onnxruntime + 烤进镜像的 ~218 MB 抠图权重:
#     remove_bg 现在也走 MCP, 本进程不再做任何图像处理。
# 留下的只有 FastAPI + MCP 客户端。
# ==========================================
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
WORKDIR /app
COPY app.py .
EXPOSE 9010
CMD ["python", "app.py"]
