# ==========================================
# 文件名: continuity/Dockerfile
# 架构定位: continuity MCP server (streamable-http), 纯 CPU
#
# 不用 engines/ 那个 Vulkan 镜像, 也不用 media-gen 的: 这个进程一行 GPU 代码都不跑。
# 生图/配音全部是 HTTP 打给 sd_server / audiocpp_server, 本容器只做 MCP 协议层 +
# 抠图 (rembg/onnxruntime, CPU)。所以基础镜像取最小的 python-slim ——
# 塞 mesa-vulkan-drivers 进来只会白白多几百 MB 且暗示它需要显卡。
#
# libgomp1 是 onnxruntime 的运行时依赖 (缺了 import 就报 libgomp.so.1 找不到)。
#
# 版本钉死: dsh-continuity 的工具语义 (19 个工具的 outputSchema) 是调用方的契约,
# 浮动版本意味着某天 docker compose build 会静默换掉这套契约。
# ==========================================
FROM python:3.12-slim
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ARG DSH_CONTINUITY_VERSION=0.3.0
RUN pip install --no-cache-dir "dsh-continuity==${DSH_CONTINUITY_VERSION}"

# rembg 首次抠图会去下载模型 (birefnet-general-lite ~214 MB)。不烤进镜像, 而是把
# HOME/缓存都指到挂出去的 /cache —— 容器重建后不用重下, 也不用为了换模型重建镜像。
ENV HOME=/cache XDG_CACHE_HOME=/cache U2NET_HOME=/cache/u2net
RUN mkdir -p /cache/u2net /state && chmod 777 /cache /cache/u2net /state

WORKDIR /state
EXPOSE 9030
# 传输方式/监听地址全走环境变量 (见 compose), 这样配置只有一处。
CMD ["continuity-mcp"]
