# media-gen: ggml/Vulkan 后端

## 为什么不用 ROCm

这张 RX 7800 XT (gfx1101) 上，ROCm 会**静默算出错误结果**：
`AutoencoderKLFlux2.decode()` 非确定 —— 同一输入连调 5 次，结果两两不相关
(SNR -1.2 / -0.6 / -0.2 / -0.3 dB)，图像输出纯灰 (std=0.5)；Stable Audio 的
`AutoencoderOobleck` 同样 (SNR -0.0 dB，幅度小 22 倍)，音频输出宽带噪声。

而它用到的每个基础算子都**逐位确定**且精度正常 (Conv2d 各通道数、GroupNorm、SiLU、
interpolate、SDPA、GEMM、Conv1d、weight_norm，fp32 +118~131 dB)，GPU RNG 也正常。
已排除：dtype、`HSA_OVERRIDE_GFX_VERSION` (unset/11.0.0/11.0.1 均复现)、transformers 版本、
权重损坏、triton/MIOpen 缓存、`expandable_segments`、干净重启、内核升级。

上游 issue: https://github.com/ROCm/ROCm/issues/6633

同一块卡上 Vulkan (RADV) 结果正确且更快 —— RADV 正确识别为 NAVI32，不需要 arch 伪装，
且运行时编译 SPIR-V 而不是查 per-gfx 预编译 kernel 表。

## 架构

```
media_gen (9010)  FastAPI，保持 /v1/jobs 契约不变
   ├── sd_server        (9020)  stable-diffusion.cpp + Vulkan  FLUX.2-klein-4B
   └── audiocpp_server  (9021)  audio.cpp + Vulkan             Stable Audio 3 Small Music
```

两个引擎常驻，模型不重载。权重是 mmap 的（`sd_server` RSS 约 340 MiB，12.6 GB 走 page cache），
内核可在内存压力下回收。

实测：生图 12 s @512、38 s @1024；生音乐 2 s（任意时长，rtf≈0.2）。

## 构建引擎

宿主机没有开发包且 `sudo` 需要密码，所以在容器里编。两个依赖不加就会失败：
**`mesa-vulkan-drivers`**（没有 RADV ICD 则容器里看不到任何 Vulkan 设备）和
**`spirv-headers`**（`ggml-vulkan.cpp` 条件 include `<spirv/unified1/spirv.hpp>`，
缺了会在 952/956 处报 `'spv' has not been declared`）。
`libglslang-dev` 在 Ubuntu 24.04 **不存在**，别加。

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ca-certificates pkg-config ninja-build \
      libvulkan-dev vulkan-tools mesa-vulkan-drivers glslc glslang-tools \
      spirv-tools spirv-headers python3 python3-pip curl
```
构建为 `audiocpp-builder:vulkan`，compose 直接用它跑两个 server。

```bash
git clone --depth 1 https://github.com/0xShug0/audio.cpp.git
docker run --rm -v $PWD/audio.cpp:/work -w /work audiocpp-builder:vulkan \
  bash scripts/build_linux.sh --backend vulkan --target audiocpp_cli --target audiocpp_server

git clone --recursive --depth 1 https://github.com/leejet/stable-diffusion.cpp.git
docker run --rm -v $PWD/stable-diffusion.cpp:/work -w /work audiocpp-builder:vulkan \
  bash -c 'cmake -B build -DCMAKE_BUILD_TYPE=Release -DSD_VULKAN=ON -G Ninja && cmake --build build -j$(nproc)'
```

容器需要 `--device /dev/dri:/dev/dri --group-add 44 --group-add 992`
（**数字 gid**；`--group-add render` 会失败，因为容器的 group 文件里没有这个名字）。

## 权重

放在仓库外（体积大）。`sdmodels2/` 和 `models/`：

| 文件 | 来源 |
|---|---|
| `flux-2-klein-4b-Q8_0.gguf` (4.3 GB) | `leejet/FLUX.2-klein-4B-GGUF` |
| `flux2-vae.safetensors` (336 MB) | `Comfy-Org/flux2-klein-4B` `split_files/vae/` |
| `qwen_3_4b.safetensors` (8.0 GB) | `Comfy-Org/flux2-klein-4B` `split_files/text_encoders/` |
| `stable-audio-3-small-music-f16.gguf` (2.4 GB) | `audio-cpp/audio.cpp-gguf` |

HF 缓存里 diffusers 格式的权重**不能直接用** —— sd.cpp 要 ComfyUI/BFL 单文件布局，
张量命名不同，且会把 diffusers VAE 误判成 FLUX.1 的 16 通道（FLUX.2 是 32）。

## 两个上限，都是实测值

- **`MAX_IMAGE_SIZE=1024` 是安全上限，正好在边缘。** 512/768/1024 显存都是约 6.7 GB
  （权重占主导），只有耗时在涨。**1280 就撑不住**：显存冲到 14531/16376 MiB 且宿主机内存开始
  下滑。2048 比干净的 OOM 更糟 —— amdgpu 驱动陷入
  `restore_userptr_worker` 颠簸，GPU 利用率掉到 7%，宿主机 30 GB 内存吃光，进程卡在
  不可中断 `D` 状态，`pkill` 杀不掉，只能 `docker kill`。
  **压分辨率必须带看门狗**（超时 + 宿主机可用内存低于 5 GB 即中止）。
- **`MAX_AUDIO_SECONDS=120` 不是安全上限，是诚实上限。** 时长不花钱（显存净增恒定约 1.8 GB，
  耗时恒定 2~7 s，10 s 到 120 s 都一样）。但**引擎在 120 s 处静默截断** ——
  请求 180/240/300/480 全部返回 `audio_duration_ms=120001` 且不报错。
  这个上限的作用是把静默截断变成响应里显式的 `clamped` 字段，让调用方知道自己被截了。
