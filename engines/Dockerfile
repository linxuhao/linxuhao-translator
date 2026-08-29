# ==========================================
# 文件名: engines/Dockerfile
# 架构定位: ggml/Vulkan 推理引擎的构建 + 运行镜像 (sd_server / audiocpp_server)
#
# ⚠️ 这是一份 VENDORED 拷贝, 会漂。
#   上游: https://github.com/linxuhao/Deepseek-Continuity
#         src/continuity_mcp/deploy/Dockerfile
#   版本: dd0226e (= PyPI dsh-continuity 0.5.5, 和 continuity/Dockerfile 里钉的
#         ARG DSH_CONTINUITY_VERSION 是同一个版本 —— 两边要一起动)
#   本地改动: 无。分割线以下逐字来自上游。
#             vip-gateway 侧的差异全在 docker-compose.yml (权重挂载路径、
#             Q8_0 而不是上游默认的 Q4_0、Vulkan 设备 1 而不是 0)。
#
#   刷新方法:
#     git clone https://github.com/linxuhao/Deepseek-Continuity /tmp/dsh
#     git -C /tmp/dsh checkout <新版本的 tag/commit>
#     diff /tmp/dsh/src/continuity_mcp/deploy/Dockerfile engines/Dockerfile
#     # 确认差异只在本注释块, 然后覆盖并改上面的"版本:"这一行
#     # build 一个就够: 两个引擎在 compose 里共用 image: vip-gateway-engines:latest
#     # (为什么显式写死这个名字, 见 docker-compose.yml 里那段注释)。
#     docker compose build sd-server
#     # 这四个必须一起 up: sd-server/audiocpp-server/continuity 只在 engines 网上,
#     # 只挪两个引擎会把 continuity 甩在旧网上, 媒体链路当场断掉。
#     docker compose up -d media-gen sd-server audiocpp-server continuity
#
#   为什么 vendored 而不是 pip 安装后从包里取: 这个文件是 docker build 的 context,
#   得在 build 之前就存在于仓库里。而它所在的包只装在 continuity 那个镜像内部,
#   宿主机上并不保证有 checkout —— 让 build 依赖一次 pip download 是把
#   "docker compose up -d 能起来" 交给网络。
#
#   历史: 2026-08 之前这个文件只装编译工具, 引擎二进制在宿主机上按
#   media-gen/README-vulkan.md 手工编, 再由 compose 把 ~/audiocpp/*.cpp 挂进来。
#   那让 "新机器上 docker compose up -d" 是假的 —— 挂载点在新机器上根本不存在。
#   现在源码 clone + 编译都在镜像内, 仓库外只剩权重 (22 GB, 见 readme)。
# ==========================================
# ------------------------------------------------------------------
# 以下逐字来自上游 dsh-continuity dd0226e
# ------------------------------------------------------------------
# ==========================================
# 两个 ggml/Vulkan 引擎的构建 + 运行镜像。
#
# 从源码编译而不是拉预编译二进制: Vulkan 后端的 shader 是运行时编译的 SPIR-V,
# 但 host 端还是要针对本机的编译器/库编。这也让镜像与厂商无关 —— 里面没有一行
# CUDA 或 ROCm。换卡不用换镜像, 但接入方式分两种:
#   A 卡 / Intel   宿主机递 /dev/dri, ICD 用镜像里的 mesa      (A 卡实测过)
#   N 卡           nvidia-container-toolkit 注入宿主机驱动     (未实测, 见 nvidia 覆盖文件)
#
# 三个依赖不加就会构建失败, 每个都花过一次:
#   mesa-vulkan-drivers  Vulkan 的 ICD。A 卡 (RADV) 和 Intel (ANV) 的驱动都在 mesa 里,
#                        缺了容器里 vulkaninfo 报 "Found no drivers"。
#                        N 卡不走这条: 它的 ICD 在宿主机驱动里, 由 nvidia-container-toolkit
#                        注入, 见 docker-compose.nvidia.yml。
#   spirv-headers        ggml-vulkan.cpp 条件 include <spirv/unified1/spirv.hpp>,
#                        缺了报 "'spv' has not been declared"
#   glslc/glslang-tools  编译 shader
# libglslang-dev 在 Ubuntu 24.04 不存在, 别加。
# ==========================================
FROM ubuntu:24.04 AS build
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ca-certificates pkg-config ninja-build \
      libvulkan-dev vulkan-tools mesa-vulkan-drivers \
      glslc glslang-tools spirv-tools spirv-headers \
      python3 curl \
 && rm -rf /var/lib/apt/lists/*

# 固定到实测跑通的提交。浮动到 master 意味着某天的上游改动会静默改变本机行为,
# 而这套东西的全部价值就是"跨次调用不变"。
ARG SDCPP_REF=97d2990
# audio.cpp d2ff370 = tag v0.7.0 (2026-08-26)。从 aec444c 上来 452 个提交,
# 换的是两件已经在咬人的事:
#   - #298 给 LoadedModel::unload() 补上 loaded.store(false)。在那之前,
#     /v1/tasks/unload_models (我们卸显存走的那条) 卸完 /v1/models 仍报
#     loaded=true —— 实测卸后进程只剩 4 MiB, 标志位却不动。只有被
#     --ui-management 门控的那条 UI 路径会清它, 而我们没开那个开关。
#   - #306 的 --idle-unload-ms: 引擎自己按空闲时间卸, 判据是 session 是否
#     真在, 不看标志位。这补上了本项目空闲计时器够不着的那半 —— 它按自己的
#     last_use 判, 于是任何不经过本进程的加载, 启动那次幂等卸载之后就再也
#     看不见了 (实测: 带外加载后等 150s, 显存纹丝不动)。
ARG AUDIOCPP_REF=d2ff370

WORKDIR /src
RUN git clone --recursive https://github.com/leejet/stable-diffusion.cpp.git \
 && git -C stable-diffusion.cpp checkout ${SDCPP_REF} \
 && git -C stable-diffusion.cpp submodule update --init --recursive \
 && cmake -S stable-diffusion.cpp -B stable-diffusion.cpp/build \
      -DCMAKE_BUILD_TYPE=Release -DSD_VULKAN=ON -G Ninja \
 && cmake --build stable-diffusion.cpp/build -j"$(nproc)"

RUN git clone https://github.com/0xShug0/audio.cpp.git \
 && git -C audio.cpp checkout ${AUDIOCPP_REF} \
 && git -C audio.cpp submodule update --init --recursive \
 && cd audio.cpp \
 && bash scripts/build_linux.sh --backend vulkan \
      --target audiocpp_cli --target audiocpp_server

# ---- 运行镜像: 只要 Vulkan 运行时, 不要编译器 ----
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      libvulkan1 mesa-vulkan-drivers vulkan-tools libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/stable-diffusion.cpp/build/bin/ /opt/continuity/bin/
COPY --from=build /src/audio.cpp/build/linux-vulkan-release/bin/ /opt/continuity/bin/
# model_specs 不是可选的: /v1/audio/speech 要按 family 找 model contract spec, 找不到就
# 500 "model contract spec not found for family 'qwen3_tts'"。而那个端点是唯一支持
# 内联 base64 参考音的 —— 少了它, 克隆就只能靠文件路径, 跨机部署直接不成立。
# 解析器会从 cwd 逐级向上找 model_specs/<family>.json, 所以放在 WORKDIR 下即可。
COPY --from=build /src/audio.cpp/model_specs/ /opt/continuity/model_specs/
ENV PATH="/opt/continuity/bin:${PATH}"
WORKDIR /opt/continuity
