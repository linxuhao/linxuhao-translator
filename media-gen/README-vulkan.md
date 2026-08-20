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
                                                              Qwen3-TTS 1.7B VoiceDesign
```

两个引擎常驻，模型不重载。权重是 mmap 的（`sd_server` RSS 约 340 MiB，12.6 GB 走 page cache），
内核可在内存压力下回收。

实测：生图 12 s @512、38 s @1024；生音乐 2 s（任意时长，rtf≈0.08）；配音 3 s（rtf≈0.29）。

一个 audiocpp_server 同时挂音乐和 TTS 两个模型（配置里两条 `models` 记录），不用起第二个容器。

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
| `Qwen3-TTS-12Hz-1.7B-VoiceDesign-GGUF/qwen3-tts-12hz-1.7b-voicedesign-q8_0.gguf` (2.7 GB) | `audio-cpp/audio.cpp-gguf` |

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

## 配音（Qwen3-TTS VoiceDesign）

选 VoiceDesign 而不是 Base，是因为 Base 靠 3 秒参考音频克隆真人嗓子，而游戏里的虚构角色
根本没有录音；VoiceDesign 从一句自然语言描述直接设计声音，而生成管线本来就在写人设。

验证不是"听着像人话"，是 **ASR 回环**：合成 → Qwen3-ASR 转录 → 比对原文。

```
原文: 这位小兄弟，武功根基不错，只是内力尚浅。老夫指点你一二。
ASR : 这位小兄弟，武功根基不错，只是内力尚浅，老夫指点你一二。
```

`voice` 描述确实在起作用，不是安慰剂 —— 同一句台词、同一个 seed，只改描述：

| voice | 基频中位数 | 时长 |
|---|---|---|
| `An elderly Chinese man, very deep hoarse voice, slow and weary` | 96 Hz | 4.88 s |
| `A young cheerful girl, bright high voice, fast and energetic` | 281 Hz | 3.04 s |

许可证是 Apache-2.0（对比之下 Audio8-TTS-0.1B 是 CC BY-NC，且它那个 120M 神经音频
codec 解码器正好是 ROCm 上算错的那一类算子，等于把今天刚逃掉的坑再踩一遍）。

## 配音的长度上限，是护栏

| 输入 | 音频时长 | ≈tokens (12 Hz) | 生成耗时 | 结果 |
|---|---|---|---|---|
| 201 字 | 45.7 s | 548 | 16 s | OK（ASR 回环逐字正确）|
| 402 字 | 90.3 s | 1084 | 42 s | OK |
| 600 字 | ~135 s | ~1620 | ~63 s | **GPU 挂死** |

600 字那次触发 `amdgpu: GPU reset(6)` + `device wedged`，连带 GPU0 上的 vllm SIGSEGV。
和音乐的 `steps x 秒数 <= 500` 是同一类问题：单次 Vulkan 提交扛不住这么长的持续计算。
引擎默认的 `max_tokens=2048`（约 170 s 音频）**拦不住**它 —— 任务在预算之内跑挂了 GPU。

两道护栏：

- `MAX_SPEECH_CHARS=200` —— 已知安全值 (402) 的一半。200 字已经是 45 秒旁白，
  而游戏里一句 NPC 台词通常 10~40 字，正常用不会碰到。更长的文本请分多次调用。
- 按字数推 `max_tokens`（实测 ~2.7 token/字，取 4.0 留余量，封顶 900）。字数上限只挡
  "输入长"，挡不住"输出跑飞" —— 一句短台词退化成循环照样能生成几分钟。实测
  `max_tokens=120` 出 9.52 s 音频（自然长度 11.92 s），旋钮确实生效。

## Actor：把音色钉在一段参考音上

VoiceDesign 的 `voice` 描述只圈定一个大致的音色区间，**区间内每句台词各漂各的**：

| 做法 | 同一角色四句台词的基频极差 |
|---|---|
| VoiceDesign 直出（默认采样）| 125 Hz |
| VoiceDesign + `do_sample=false` 贪心 | **242 Hz**（更差）|
| **Actor（Base 克隆）** | **5 Hz**（`guo_jing`）/ 52 Hz（`洪七公`，铸砸的那次）|

关键一点：贪心解码下 seed 已经完全失效（三个 seed 同一个 sha256），随机性被彻底消除，
**可它照样漂 242 Hz**。所以音色是**文本的函数**，不是采样随机性 ——
`temperature=0` / `top_k=1` 这条路是死的，唯一的修法是换模型。

流程：`create_actor` 用 VoiceDesign 铸一句参考音存进 `/actors/<name>.wav`，
之后 `actor_tts` 交给 Base 以 `voice_ref` + `reference_text` 克隆。参考音的文字是我们
自己生成的，所以 `reference_text` 不用调用方操心。

**铸完必须先听。** `洪七公` 那次铸出来是 229~264 Hz —— 对"苍老沙哑"完全不对，而且
之后每一句都错得很一致。`create_actor` 因此返回试音 URL，重铸要显式 `force=true`。

参考音挂在**独立的 `./actors` 卷**上，不在 `./generated` 里：后者有 30 天清理，
那个清理眼下不递归、也只删文件，子目录"碰巧"安全 —— 但那是意外不是设计。

## Subject：把"长什么样"钉在一张定妆图上

和 actor 同一个病、同一个解法的视觉版。`generate_image` 每次给的是"长得不一样的东西"：
同一个角色的头像 / 战斗立绘 / 地图小人是三个人；同一个宝箱换个角度也是另一个箱子。

`create_character` / `create_object` 定妆一张参考图存进 `/subjects/<name>.png`，
之后 `subject_image` 把它作为 `ref_images` 走图生图，外观与场景描述解耦。

**角色和道具是一套存储、一个 runner**，差别只在 `kind` 选的取景 prompt —— 复制两份
一样的代码只为了换一句 suffix 是不值得的：

| kind | 取景 |
|---|---|
| `character` | 正面全身、中性站姿、干净背景 |
| `object` | 四分之三视角、居中、隔离、无场景（正投影看不出体积，换角度就没有可对齐的信息）|

验收用 GPU0 上的 VLM 当判官（和用 ASR 判配音一个道理），同一组场景做有/无定妆图对照，
每边判三次：

| | 三次评分 | 中位数 |
|---|---|---|
| 角色 · 带定妆图 | 9 / 9 / 9 | **9** |
| 角色 · 无定妆图 | 7 / 6 / 9 | 7 |
| 宝箱四视角 · 带定妆图 | 9 / 9 / 7 | **9** |
| 宝箱四视角 · 无定妆图 | 8 / 6 / 6 | 6 |

角色那组三次全是 9，判官没有分歧。宝箱这组有一次掉到 7 —— 新视角（背面 / 正俯视）
仍会漂一点，参考图里没有的信息模型只能自己编。**它把问题显著缩小了，不是消灭了。**

定妆图同样**必须先看**：定砸了会把整个 subject 锁死在错的外观上，之后每一张都错得
很一致。`/subjects` 是独立的卷，同样不进仓库、同样不可复现。

## 同一时刻只留一个音频模型

三个音频模型（音乐 / VoiceDesign / Base）全常驻时实测峰值 **15.70/16.00 GB**，
再叠一张 1024 生图就把 GPU 挤挂了（当天第三次 device lost）。它们的显存是"用过就留着"的：

| 状态 | GPU1 |
|---|---|
| 三个都推理过 | 11.09 GB |
| 卸掉音乐 + VoiceDesign | 7.90 GB |
| 全卸掉 | 3.62 GB |

`media_gen` 本来就是单 worker 串行，同一时刻只需要一个模型，所以每个音频任务开跑前
先 `unload_models` 掉另外两个。重载实测 **4.3 s**（权重在 page cache 里），只在
音乐/配音/铸声之间切换时才付。三个模型都改成 `lazy`，开机基线 3.61 GB。

**峰值 15.70 → 11.28 GB**（全流程：铸声 → 角色台词 → 音乐 → 1024 生图 → 角色台词）。

## 已知缺口：GPU 复位后引擎不自愈

`sd_server` / `audiocpp_server` 在 GPU 复位后**进程不退出**，但 Vulkan 上下文已死，
之后每个请求都返回 `vk::Queue::submit: ErrorDeviceLost`，而 `/v1/models` 照样 200、
`docker ps` 照样显示 `Up`。`restart: unless-stopped` 救不了它。
目前只能人工 `docker restart`。

## 显存预算（16 GB 卡，四个使用者共享）

两个模型都开了 `mem_saver`，请求做完就释放各自的 step graph。这不是拿质量换显存：
固定 seed 下音乐输出 **sha256 逐位相同**，而且反而更快（1.68 s vs 2.38 s）。

| 配置 | 全流程峰值 |
|---|---|
| 无 TTS + ASR `0.30` | 12.5 GB |
| 加 TTS，两处 `mem_saver`，ASR `0.30` | 15.2 GB ← 只剩 0.8 GB，太紧 |
| 同上但 ASR `0.25` | **14.4 GB** ← 现状 |
| 同上但 ASR `0.20` | vLLM 起不来 |

`0.20` 起不来是个顺序陷阱：vLLM 按*卡上剩余*显存算 KV cache，历史上它能用 `0.20`
是因为那时它先启动。现在两个引擎已经常驻，同样的 `0.20` 只剩 0.27 GiB 给 KV
（需要 0.44 GiB），于是崩溃重启循环。

峰值出在生图（瞬时 +6.5 GB），而 media_gen 是单 worker 串行的，生图/音乐/配音
不会同时占显存。真撞上限也是 Vulkan 的干净分配失败（任务报错），不是今天那种
mode1 reset —— 那些是计算/队列挂死，不是分配失败。
