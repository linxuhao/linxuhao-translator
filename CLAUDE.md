# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a self-hosted AI translation gateway (随身翻译官/ShuiShen-Translator) that combines ASR (Qwen3-ASR) with LLM translation (Qwen3.5-27B) for real-time voice translation. It uses a heterogeneous dual-GPU architecture optimized for AMD ROCm.

## Commands

### Development

```bash
# Start all services (first boot downloads models ~30B + 1.7B)
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
- **vllm-qwen**: LLM translation engine (Qwen3.5-27B GPTQ-int4 on GPU 0)
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

## GPU Configuration

AMD ROCm dual-GPU setup:
- GPU 0 (7900 XTX): `HIP_VISIBLE_DEVICES=0` for vllm-qwen
- GPU 1 (7800 XT): `HIP_VISIBLE_DEVICES=1` for qwen3-asr

For NVIDIA, change base images from `vllm/vllm-openai-rocm` to `vllm/vllm-openai`.