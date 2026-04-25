# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a self-hosted AI translation gateway (随身翻译官/ShuiShen-Translator) that combines ASR with LLM translation for real-time voice translation. It features **hardware-adaptive deployment** with named profiles in `config/hardware_profiles.yml`.

## Installation

### One-Line Install (New Machine)

```bash
# Clone and install everything automatically
curl -fsSL https://raw.githubusercontent.com/linxuhao/vip-gateway/main/bootstrap.sh | bash

# Or with options
curl -fsSL https://raw.githubusercontent.com/linxuhao/vip-gateway/main/bootstrap.sh | bash -s -- --profile nvidia_single_24gb
curl -fsSL https://raw.githubusercontent.com/linxuhao/vip-gateway/main/bootstrap.sh | bash -s -- --dry-run
```

This will:
1. Clone the repository to `./vip-gateway/`
2. Run `install.sh` with all its phases

### Manual Install (After Clone)

```bash
git clone https://github.com/linxuhao/vip-gateway.git
cd vip-gateway
./install.sh
```

### Install Phases

The installer automatically handles:
- **Phase 0**: Python3, venv, dependencies (PyYAML), Docker check/install
- **Phase 1**: GPU hardware detection (vendor, count, VRAM)
- **Phase 2**: Profile selection from `config/hardware_profiles.yml`
- **Phase 3**: Configuration generation (docker-compose.yml)
- **Phase 4**: Service deployment (pull images, build gateway, start)

### Options

```bash
# View all available hardware profiles
./install.sh --list-profiles

# Use specific profile (skip auto-detection)
./install.sh --profile nvidia_single_24gb
./install.sh --profile amd_dual_40gb

# Skip dependency installation (assume already installed)
./install.sh --skip-deps

# Dry run (show detection without deploying)
./install.sh --dry-run

# Generate config but don't start services
./install.sh --no-start
```

### Supported OS

| OS | Docker Install | Python Install |
|----|----------------|----------------|
| Ubuntu/Debian | apt + docker repo | apt |
| Fedora/RHEL | dnf + docker repo | dnf |
| Arch Linux | pacman | pacman |
| macOS | Homebrew (Docker Desktop) | Homebrew |

### Hardware Profiles

All configurations are defined in `config/hardware_profiles.yml`. Profiles are named by vendor and VRAM:

| Vendor | Single GPU | Dual GPU |
|--------|-----------|----------|
| **NVIDIA** | `nvidia_single_6gb`, `8gb`, `12gb`, `16gb`, `24gb`, `32gb_plus` | `nvidia_dual_16gb`, `24gb`, `40gb`, `48gb_plus` |
| **AMD** | `amd_single_8gb`, `12gb`, `16gb`, `20gb`, `24gb` | `amd_dual_24gb`, `32gb`, `40gb`, `48gb_plus` |
| **Apple** | `apple_8gb`, `16gb`, `24gb`, `32gb_plus` | (single only) |
| **Intel** | `intel_single_6gb`, `8gb`, `16gb` | (single only) |

### Model Selection per Profile

Each profile specifies:
- `llm_model`: LLM for translation (Qwen3.x variants)
- `asr_model`: ASR engine (Qwen3-ASR or Whisper)
- `llm_gpu_util`, `asr_gpu_util`: GPU memory allocation
- `max_concurrent`: Concurrent request limit
- `max_model_len`: Context length

### Customizing Profiles

Edit `config/hardware_profiles.yml` to add or modify profiles:

```yaml
profiles:
  my_custom_profile:
    name: "My Custom Setup"
    vendor: nvidia
    gpu_count: 1
    min_vram_mb: 18000
    max_vram_mb: 22000
    llm_model: Qwen/Qwen3-14B-GPTQ-Int4
    asr_model: Qwen/Qwen3-ASR-1.7B
    llm_gpu_util: 0.60
    asr_gpu_util: 0.30
    max_concurrent: 16
```

## Commands

### Development

```bash
# Start all services
docker compose up -d

# Rebuild gateway after code changes
docker compose up -d --build gateway

# View logs
docker compose logs -f gateway

# Stop all services
docker compose down
```

### Local Development (without Docker)

```bash
# Run gateway directly (requires FFmpeg installed)
cd gateway/app
pip install fastapi uvicorn httpx python-multipart
uvicorn gateway:app --host 0.0.0.0 --port 5000
```

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Mobile UI  │────▶│  FastAPI Gateway │────▶│  Qwen3-ASR     │
│  (Web HTML) │     │  (Port 5000)     │     │  (GPU 1)       │
└─────────────┘     │                  │     │  Port 9000     │
                    │  ┌────────────┐  │     └─────────────────┘
                    │  │ SQLite DB  │  │              │
                    │  │ User/VIP   │  │              ▼
                    │  └────────────┘  │     ┌─────────────────┐
                    │                  │────▶│  vLLM Qwen3.5   │
                    │  FFmpeg WAV      │     │  (GPU 0)       │
                    │  16kHz mono      │     │  Port 8000     │
                    └──────────────────┘     └─────────────────┘
```

### Key Services (docker-compose.yml)

- **gateway**: FastAPI routing + FFmpeg audio normalization
- **vllm-qwen**: LLM translation engine (Qwen3.6-27B GPTQ-int4 on GPU 0)
- **qwen3-asr**: ASR engine (Qwen3-ASR-1.7B on GPU 1)
- **cloudflared**: Cloudflare tunnel for public access

### API Routes

| Route | File | Purpose |
|-------|------|---------|
| `/api/stream_voice` | `routers/translation.py` | Real-time translation (SSE streaming) |
| `/api/tutor/stream` | `routers/tutor.py` | Tutor mode with chat history |
| `/api/record` | `routers/record.py` | Meeting recording (non-streaming) |
| `/api/me` | `routers/user.py` | User profile |
| `/api/admin/*` | `routers/user.py` | Admin panel (VIP management) |

### Frontend Pages

| Path | File | Purpose |
|------|------|---------|
| `/` | `web/index.html` | Main translation UI |
| `/tutor` | `web/tutor.html` | Tutor mode UI |
| `/record` | `web/record.html` | Meeting recording UI |
| `/admin` | `web/admin.html` | Admin panel (requires auth) |

## Code Patterns

### Audio Pipeline

All routes use FFmpeg to convert WebM/MP4 to 16kHz mono WAV:
```python
proc = await asyncio.create_subprocess_exec(
    "ffmpeg", "-y", "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1",
    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
)
```

### Worker Pool Pattern

Each route uses a priority queue + worker pool for concurrent request handling:
- `translation.py`: 64 workers (`MAX_CONCURRENT_TASKS`)
- `tutor.py`: 4 workers (`TUTOR_MAX_CONCURRENT`)
- Workers pull from `asyncio.PriorityQueue`, execute pipeline, stream SSE results

### Environment Variables

Set in `.env`:
- `CF_TUNNEL_TOKEN`: Cloudflare tunnel token
- `HF_TOKEN`: Hugging Face token (for gated models)

### LLM Response Parsing

Responses use XML-like tags: `<language>`, `<original>`, `<translation>`. Parsing in `record.py` handles truncated/incomplete tags.

### Qwen3.6 Thinking Modes

Qwen3.6-27B supports three operation modes controlled via API:

| Mode | `enable_thinking` | Behavior |
|------|-------------------|----------|
| **Thinking** (default) | `true` | Model outputs `<think>...</think>` reasoning block before response |
| **Instruct** | `true` + `preserve_thinking` | Keeps historical reasoning context |
| **Non-thinking** | `false` | Direct response, no reasoning block |

**Per-route configuration:**
- `/api/stream_voice` (translation): Uses `enable_thinking: False` for low-latency direct translation
- `/api/tutor/stream` (tutor): Uses `enable_thinking: True` to show AI reasoning process
- `/api/record` (meeting): Uses `enable_thinking: True` for full analysis with reasoning

## GPU Configuration

GPU configuration is managed via **named profiles** in `config/hardware_profiles.yml`:

- Run `./install.sh` to auto-select the best profile for your hardware
- Run `./install.sh --list-profiles` to see all available profiles
- Run `./install.sh --profile <name>` to use a specific profile

Generated configuration is stored in `config/generated/hardware.env`.

### Configuration Files

| File | Purpose |
|------|---------|
| `config/hardware_profiles.yml` | All hardware profile definitions |
| `config/generated/hardware.env` | Auto-generated hardware config |
| `docker-compose.yml` | Auto-generated deployment config |
| `docker-compose.example.yml` | Original hardcoded config (reference) |

### Manual Override

```bash
# Select specific profile
./install.sh --profile nvidia_single_24gb

# Or edit hardware.env and regenerate
vim config/generated/hardware.env
python3 scripts/generate_config.py \
    --env config/generated/hardware.env \
    --output docker-compose.yml
```