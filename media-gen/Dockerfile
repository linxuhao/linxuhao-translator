# ==========================================
# 文件名: media-gen/Dockerfile
# 架构定位: GPU 1 (7800 XT) - 文生图 (FLUX.2 Klein) + 文生音乐 (Stable Audio 3 Small)
#
# 2026-08-20: 从 rocm/pytorch 换成精简 Vulkan 镜像。
# 推理由挂载进来的 ggml 二进制承担 (sd-cli / audiocpp_cli), 本镜像只提供
# HTTP 层 + Vulkan 运行时。不再需要 ROCm / PyTorch / diffusers / torchsde。
# 见 ROCm/ROCm#6633 —— ROCm 在这张卡上 VAE 解码静默算错。
# mesa-vulkan-drivers 是必需的: 没有 RADV ICD 容器里看不到任何 Vulkan 设备。
# ==========================================
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv libvulkan1 mesa-vulkan-drivers libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
WORKDIR /app
COPY app.py .
EXPOSE 9010
CMD ["python", "app.py"]
