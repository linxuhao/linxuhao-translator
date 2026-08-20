# ==========================================
# 文件名: engines/Dockerfile
# 架构定位: ggml/Vulkan 推理引擎的构建 + 运行镜像 (sd-server / audiocpp_server)
#
# 用 build: 而不是从 registry 拉, 是因为这个镜像只在本机用, 推 registry 要凭证和托管;
# 但它必须留在仓库里 —— 否则 docker image prune 之后两个 server 就永远起不来了,
# restart: unless-stopped 救不了一个不存在的镜像。
#
# 两个依赖不加就会构建失败, 各花过一次:
#   mesa-vulkan-drivers  没有 RADV ICD, 容器里 vulkaninfo 报 "Found no drivers"
#   spirv-headers        ggml-vulkan.cpp 条件 include <spirv/unified1/spirv.hpp>,
#                        缺了会在 952/956 处报 "'spv' has not been declared"
# libglslang-dev 在 Ubuntu 24.04 不存在, 别加。
#
# 引擎源码与权重在仓库外 (体积大), 由 compose 以 volume 挂入。
# 构建步骤见 media-gen/README-vulkan.md。
# ==========================================
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ca-certificates pkg-config ninja-build \
      libvulkan-dev vulkan-tools mesa-vulkan-drivers \
      glslc glslang-tools spirv-tools spirv-headers \
      python3 curl \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /work
