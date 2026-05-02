#!/usr/bin/env python3
"""
VIP Gateway Configuration Generator
Reads hardware.env and generates docker-compose.yml
"""

import argparse
import os
import sys
from pathlib import Path
from datetime import datetime

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)


def parse_env_file(env_path: str) -> dict:
    """Parse hardware.env into a dictionary."""
    env_vars = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                # Handle quoted values
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                env_vars[key] = value
    return env_vars


def get_gpu_devices_config(env: dict) -> dict:
    """Get GPU device passthrough configuration based on vendor."""
    vendor = env.get('GPU_VENDOR', 'nvidia')

    config = {}

    if vendor == 'amd':
        config['devices'] = [
            '/dev/kfd:/dev/kfd',
            '/dev/dri:/dev/dri',
        ]
        config['group_add'] = ['video', 'render']
    elif vendor == 'nvidia':
        # NVIDIA uses nvidia-container-runtime
        config['deploy'] = {
            'resources': {
                'reservations': {
                    'devices': [
                        {
                            'driver': 'nvidia',
                            'count': 'all',
                            'capabilities': ['gpu']
                        }
                    ]
                }
            }
        }
    # Intel and Apple don't need special device config in Docker

    return config


def generate_llm_command(env: dict) -> str:
    """Generate vLLM serve command for LLM."""
    model = env.get('LLM_MODEL', 'Qwen/Qwen3-14B-GPTQ-Int4')
    gpu_util = env.get('LLM_GPU_UTIL', '0.85')
    max_len = env.get('LLM_MAX_MODEL_LEN', '4096')
    extra_args = env.get('LLM_EXTRA_ARGS', '')

    cmd_parts = [
        'vllm serve', model,
        '--dtype float16',
        f'--max-model-len {max_len}',
        f'--gpu-memory-utilization {gpu_util}',
        '--served-model-name qwen3',
        '--trust-remote-code',
    ]

    if extra_args:
        cmd_parts.append(extra_args)

    return ' '.join(cmd_parts)


def generate_asr_command(env: dict) -> str:
    """Generate vLLM serve command for ASR."""
    model = env.get('ASR_MODEL', 'Qwen/Qwen3-ASR-1.7B')
    gpu_util = env.get('ASR_GPU_UTIL', '0.85')

    # Whisper models use different config
    if 'whisper' in model.lower():
        cmd_parts = [
            'vllm serve', model,
            '--dtype float16',
            '--max-model-len 2048',
            f'--gpu-memory-utilization {gpu_util}',
            '--served-model-name whisper',
            '--trust-remote-code',
        ]
    else:
        cmd_parts = [
            'vllm serve', model,
            '--dtype float16',
            '--max-model-len 8192',
            f'--gpu-memory-utilization {gpu_util}',
            '--max-num-seqs 80',
            '--served-model-name qwen3-asr',
            '--trust-remote-code',
        ]

    return ' '.join(cmd_parts)


def generate_dual_gpu_config(env: dict) -> dict:
    """Generate docker-compose for dual GPU split deployment."""
    vendor = env.get('GPU_VENDOR', 'nvidia')
    gpu_env_var = env.get('GPU_ENV_VAR', 'CUDA_VISIBLE_DEVICES')
    llm_gpu = env.get('LLM_GPU_INDEX', '0')
    asr_gpu = env.get('ASR_GPU_INDEX', '1')
    vllm_image = env.get('VLLM_IMAGE', 'vllm/vllm-openai:latest')
    max_concurrent = env.get('MAX_CONCURRENT_TASKS', '32')

    gpu_devices = get_gpu_devices_config(env)

    config = {
        'services': {
            'gateway': {
                'build': {'context': './gateway'},
                'container_name': 'gateway',
                'ports': ['5000:5000'],
                'environment': [
                    'BRAIN_ENGINE_URL=http://vllm_qwen:8000/v1/chat/completions',
                    'ASR_TRANSCRIBE_URL=http://qwen3_asr:8000/v1/audio/transcriptions',
                    'ASR_ENGINE_URL=http://qwen3_asr:8000/v1/chat/completions',
                    f'MAX_CONCURRENT_TASKS={max_concurrent}',
                ],
                'volumes': ['./gateway/app:/app'],
                'depends_on': ['vllm-qwen', 'qwen3-asr'],
                'restart': 'unless-stopped',
            },
            'vllm-qwen': {
                'image': vllm_image,
                'container_name': 'vllm_qwen',
                'ports': ['8000:8000'],
                'environment': [
                    f'{gpu_env_var}={llm_gpu}',
                    'VLLM_USE_TRITON_AWQ=1',
                    'HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}',
                ],
                'volumes': [
                    '~/.cache/huggingface:/root/.cache/huggingface',
                ],
                'command': generate_llm_command(env),
                'restart': 'unless-stopped',
                **gpu_devices,
            },
            'qwen3-asr': {
                'image': vllm_image,
                'container_name': 'qwen3_asr',
                'ports': ['9000:8000'],
                'environment': [
                    f'{gpu_env_var}={asr_gpu}',
                    'VLLM_USE_TRITON_AWQ=1',
                    'HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}',
                ],
                'volumes': [
                    '~/.cache/huggingface:/root/.cache/huggingface',
                ],
                'command': generate_asr_command(env),
                'restart': 'unless-stopped',
                **gpu_devices,
            },
        },
    }

    return config


def generate_single_gpu_config(env: dict) -> dict:
    """Generate docker-compose for single GPU deployment."""
    vendor = env.get('GPU_VENDOR', 'nvidia')
    gpu_env_var = env.get('GPU_ENV_VAR', 'CUDA_VISIBLE_DEVICES')
    vllm_image = env.get('VLLM_IMAGE', 'vllm/vllm-openai:latest')
    max_concurrent = env.get('MAX_CONCURRENT_TASKS', '16')

    gpu_devices = get_gpu_devices_config(env)

    config = {
        'services': {
            'gateway': {
                'build': {'context': './gateway'},
                'container_name': 'gateway',
                'ports': ['5000:5000'],
                'environment': [
                    'BRAIN_ENGINE_URL=http://vllm_qwen:8000/v1/chat/completions',
                    'ASR_TRANSCRIBE_URL=http://qwen3_asr:8000/v1/audio/transcriptions',
                    'ASR_ENGINE_URL=http://qwen3_asr:8000/v1/chat/completions',
                    f'MAX_CONCURRENT_TASKS={max_concurrent}',
                ],
                'volumes': ['./gateway/app:/app'],
                'depends_on': ['vllm-qwen', 'qwen3-asr'],
                'restart': 'unless-stopped',
            },
            'vllm-qwen': {
                'image': vllm_image,
                'container_name': 'vllm_qwen',
                'ports': ['8000:8000'],
                'environment': [
                    f'{gpu_env_var}=0',
                    'VLLM_USE_TRITON_AWQ=1',
                    'HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}',
                ],
                'volumes': [
                    '~/.cache/huggingface:/root/.cache/huggingface',
                ],
                'command': generate_llm_command(env),
                'restart': 'unless-stopped',
                **gpu_devices,
            },
            'qwen3-asr': {
                'image': vllm_image,
                'container_name': 'qwen3_asr',
                'ports': ['9000:8000'],
                'environment': [
                    f'{gpu_env_var}=0',  # Same GPU
                    'VLLM_USE_TRITON_AWQ=1',
                    'HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}',
                ],
                'volumes': [
                    '~/.cache/huggingface:/root/.cache/huggingface',
                ],
                'command': generate_asr_command(env),
                'restart': 'unless-stopped',
                **gpu_devices,
            },
        },
    }

    return config


def generate_apple_config(env: dict) -> dict:
    """Generate docker-compose for Apple Silicon."""
    # Apple Silicon runs on macOS Docker
    # Metal acceleration needs special handling

    vllm_image = env.get('VLLM_IMAGE', 'vllm/vllm-openai:latest')
    max_concurrent = env.get('MAX_CONCURRENT_TASKS', '16')

    config = {
        'services': {
            'gateway': {
                'build': {'context': './gateway'},
                'container_name': 'gateway',
                'ports': ['5000:5000'],
                'environment': [
                    'BRAIN_ENGINE_URL=http://vllm_qwen:8000/v1/chat/completions',
                    'ASR_TRANSCRIBE_URL=http://qwen3_asr:8000/v1/audio/transcriptions',
                    'ASR_ENGINE_URL=http://qwen3_asr:8000/v1/chat/completions',
                    f'MAX_CONCURRENT_TASKS={max_concurrent}',
                ],
                'volumes': ['./gateway/app:/app'],
                'depends_on': ['vllm-qwen', 'qwen3-asr'],
                'restart': 'unless-stopped',
            },
            'vllm-qwen': {
                'image': vllm_image,
                'container_name': 'vllm_qwen',
                'ports': ['8000:8000'],
                'environment': [
                    'VLLM_USE_TRITON_AWQ=1',
                    'HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}',
                    # Metal is auto-detected on macOS
                ],
                'volumes': [
                    '~/.cache/huggingface:/root/.cache/huggingface',
                ],
                'command': generate_llm_command(env),
                'restart': 'unless-stopped',
            },
            'qwen3-asr': {
                'image': vllm_image,
                'container_name': 'qwen3_asr',
                'ports': ['9000:8000'],
                'environment': [
                    'VLLM_USE_TRITON_AWQ=1',
                    'HUGGING_FACE_HUB_TOKEN=${HF_TOKEN}',
                ],
                'volumes': [
                    '~/.cache/huggingface:/root/.cache/huggingface',
                ],
                'command': generate_asr_command(env),
                'restart': 'unless-stopped',
            },
        },
    }

    return config


def add_cloudflared(config: dict) -> dict:
    """Add cloudflared service if CF_TUNNEL_TOKEN exists in .env."""
    # Check if .env exists and has CF_TUNNEL_TOKEN
    env_file = Path('.env')
    if env_file.exists():
        content = env_file.read_text()
        if 'CF_TUNNEL_TOKEN' in content:
            config['services']['cloudflared'] = {
                'image': 'cloudflare/cloudflared:latest',
                'container_name': 'cloudflared',
                'command': 'tunnel --no-autoupdate run --token ${CF_TUNNEL_TOKEN}',
                'restart': 'unless-stopped',
            }
    return config


def add_mcp_server(config: dict) -> dict:
    """Add MCP server service for Tailscale network access to ASR/OCR."""
    config['services']['mcp-server'] = {
        'build': {'context': './mcp-server'},
        'container_name': 'mcp_server',
        'ports': ['9003:9003'],
        'environment': [
            'ASR_URL=http://qwen3_asr:8000/v1/chat/completions',
            'VLLM_URL=http://vllm_qwen:8000/v1/chat/completions',
            'HF_TOKEN=${HF_TOKEN}',
        ],
        'restart': 'unless-stopped',
    }
    return config


def main():
    parser = argparse.ArgumentParser(description='Generate docker-compose.yml from hardware.env')
    parser.add_argument('--env', required=True, help='Path to hardware.env')
    parser.add_argument('--output', required=True, help='Path to output docker-compose.yml')
    args = parser.parse_args()

    # Parse hardware.env
    env = parse_env_file(args.env)

    strategy = env.get('DEPLOYMENT_STRATEGY', 'single_mid')

    # Generate config based on strategy
    if strategy.startswith('dual') or strategy == 'multi_gpu':
        config = generate_dual_gpu_config(env)
    elif strategy.startswith('single'):
        config = generate_single_gpu_config(env)
    elif strategy == 'apple_metal':
        config = generate_apple_config(env)
    elif strategy == 'intel_arc':
        config = generate_single_gpu_config(env)
    else:
        config = generate_single_gpu_config(env)

    # Add cloudflared if configured
    config = add_cloudflared(config)

    # Always add MCP server for Tailscale network access
    config = add_mcp_server(config)

    # Write output with header comment
    output_path = Path(args.output)

    header = f"""# VIP Gateway Auto-generated Configuration
# DO NOT EDIT MANUALLY - Run ./install.sh to regenerate
#
# Hardware: {env.get('GPU_VENDOR', 'unknown')} | GPUs: {env.get('GPU_COUNT', '1')} | Strategy: {strategy}
# LLM: {env.get('LLM_MODEL', 'unknown')} | ASR: {env.get('ASR_MODEL', 'unknown')}
# Generated: {datetime.now().isoformat()}
#
# Original configuration preserved in: docker-compose.example.yml

"""

    # Convert to YAML
    yaml_content = yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Write with header
    output_path.write_text(header + yaml_content)

    print(f"Generated: {args.output}")
    print(f"Strategy: {strategy}")
    print(f"LLM: {env.get('LLM_MODEL')} on GPU {env.get('LLM_GPU_INDEX')}")
    print(f"ASR: {env.get('ASR_MODEL')} on GPU {env.get('ASR_GPU_INDEX')}")


if __name__ == '__main__':
    main()