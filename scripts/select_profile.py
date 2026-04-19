#!/usr/bin/env python3
"""
VIP Gateway Profile Selector
Reads hardware_profiles.yml and selects the best matching profile
"""

import argparse
import sys
import os

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required. Install: pip install pyyaml")
    sys.exit(1)


def load_profiles(path: str) -> dict:
    """Load hardware_profiles.yml"""
    with open(path) as f:
        return yaml.safe_load(f)


def get_vendor_config(profiles: dict, vendor: str) -> dict:
    """Get vendor-specific configuration"""
    vendors = profiles.get('vendors', {})
    return vendors.get(vendor, vendors.get('nvidia', {}))


def match_single_gpu_profile(profiles: dict, vendor: str, vram_mb: int) -> tuple:
    """Match profile for single GPU based on VRAM"""
    candidates = []

    for profile_id, profile in profiles.get('profiles', {}).items():
        if profile.get('vendor') != vendor:
            continue
        if profile.get('gpu_count', 1) != 1:
            continue

        min_vram = profile.get('min_vram_mb', 0)
        max_vram = profile.get('max_vram_mb')  # Can be None

        if vram_mb >= min_vram:
            if max_vram is None or vram_mb <= max_vram:
                candidates.append((profile_id, profile, min_vram))

    # Sort by min_vram descending (prefer higher spec profiles)
    candidates.sort(key=lambda x: x[2], reverse=True)

    if candidates:
        profile_id, profile, _ = candidates[0]
        return (profile_id, profile)
    return None


def match_dual_gpu_profile(profiles: dict, vendor: str, total_vram_mb: int, gpu_vrams: list) -> tuple:
    """Match profile for dual GPU based on total VRAM"""
    candidates = []

    for profile_id, profile in profiles.get('profiles', {}).items():
        if profile.get('vendor') != vendor:
            continue
        if profile.get('gpu_count', 1) != 2:
            continue

        min_total = profile.get('min_total_vram_mb', 0)
        max_total = profile.get('max_total_vram_mb')  # Can be None

        if total_vram_mb >= min_total:
            if max_total is None or total_vram_mb <= max_total:
                candidates.append((profile_id, profile, min_total))

    # Sort by min_total descending
    candidates.sort(key=lambda x: x[2], reverse=True)

    if candidates:
        profile_id, profile, _ = candidates[0]
        return (profile_id, profile)
    return None


def get_fallback_profile(profiles: dict, vendor: str) -> dict:
    """Get fallback profile for vendor"""
    # Try to find smallest profile for vendor
    for profile_id, profile in profiles.get('profiles', {}).items():
        if profile.get('vendor') == vendor:
            return (profile_id, profile)

    # Ultimate fallback
    fallback_id = profiles.get('matching', {}).get('fallback', 'nvidia_single_6gb')
    return (fallback_id, profiles['profiles'].get(fallback_id, {}))


def select_profile(profiles: dict, vendor: str, gpu_count: int, total_vram_mb: int,
                   gpu_vrams: list, specified_profile: str = None) -> tuple:
    """Select the best matching profile"""

    # If user specified profile, validate and use it
    if specified_profile:
        profile = profiles.get('profiles', {}).get(specified_profile)
        if not profile:
            print(f"ERROR: Profile '{specified_profile}' not found")
            sys.exit(1)
        if profile.get('vendor') != vendor:
            print(f"ERROR: Profile '{specified_profile}' is for {profile.get('vendor')}, not {vendor}")
            sys.exit(1)
        return (specified_profile, profile)

    # Auto-select based on hardware
    if gpu_count >= 2:
        match = match_dual_gpu_profile(profiles, vendor, total_vram_mb, gpu_vrams)
    else:
        match = match_single_gpu_profile(profiles, vendor, gpu_vrams[0] if gpu_vrams else total_vram_mb)

    if match:
        return match

    # Fallback
    return get_fallback_profile(profiles, vendor)


def output_env_vars(profile_id: str, profile: dict, vendor_config: dict):
    """Output profile data as shell environment variables"""
    print(f"PROFILE_ID={profile_id}")
    print(f"PROFILE_NAME=\"{profile.get('name', profile_id)}\"")
    print(f"STRATEGY={profile.get('strategy', 'single_mid')}")

    # Model configuration
    print(f"LLM_MODEL={profile.get('llm_model', 'Qwen/Qwen3-14B-GPTQ-Int4')}")
    print(f"ASR_MODEL={profile.get('asr_model', 'Qwen/Qwen3-ASR-1.7B')}")
    print(f"LLM_GPU_UTIL={profile.get('llm_gpu_util', 0.85)}")
    print(f"ASR_GPU_UTIL={profile.get('asr_gpu_util', 0.85)}")
    print(f"MAX_MODEL_LEN={profile.get('max_model_len', 4096)}")
    print(f"MAX_CONCURRENT={profile.get('max_concurrent', 16)}")

    # Vendor configuration
    print(f"VLLM_IMAGE={vendor_config.get('image', 'vllm/vllm-openai:latest')}")
    print(f"GPU_ENV_VAR={vendor_config.get('env_var', 'CUDA_VISIBLE_DEVICES')}")


def list_profiles(profiles: dict):
    """List all available profiles"""
    print("\nAvailable Hardware Profiles:")
    print("=" * 60)

    vendors = profiles.get('vendors', {})

    # Group by vendor
    for vendor_id, vendor_info in vendors.items():
        vendor_name = vendor_info.get('name', vendor_id)
        print(f"\n{vendor_name}:")
        print("-" * 40)

        for profile_id, profile in profiles.get('profiles', {}).items():
            if profile.get('vendor') == vendor_id:
                name = profile.get('name', profile_id)
                desc = profile.get('description', '')
                gpu_count = profile.get('gpu_count', 1)

                if gpu_count == 1:
                    vram = f"{profile.get('min_vram_mb', 0)//1000}-{profile.get('max_vram_mb', 999)//1000}GB"
                else:
                    vram = f"{profile.get('min_total_vram_mb', 0)//1000}GB+"

                print(f"  {profile_id}")
                print(f"    Name: {name}")
                print(f"    VRAM: {vram}")
                print(f"    LLM:  {profile.get('llm_model', 'default')}")
                print(f"    ASR:  {profile.get('asr_model', 'default')}")
                print()

    print("\nUsage: ./install.sh --profile <profile_id>")
    print("Example: ./install.sh --profile nvidia_single_24gb")


def main():
    parser = argparse.ArgumentParser(description='Select hardware profile')
    parser.add_argument('--profiles', required=True, help='Path to hardware_profiles.yml')
    parser.add_argument('--profile', help='Specific profile to use')
    parser.add_argument('--vendor', help='GPU vendor (nvidia/amd/apple/intel)')
    parser.add_argument('--gpu-count', type=int, default=1, help='Number of GPUs')
    parser.add_argument('--total-vram', type=int, help='Total VRAM in MB')
    parser.add_argument('--gpu-vrams', help='VRAM per GPU (space-separated)')
    parser.add_argument('--list', action='store_true', help='List all profiles')
    args = parser.parse_args()

    profiles = load_profiles(args.profiles)

    if args.list:
        list_profiles(profiles)
        return

    if not args.vendor:
        print("ERROR: --vendor required when not listing")
        sys.exit(1)

    gpu_vrams = []
    if args.gpu_vrams:
        gpu_vrams = [int(x) for x in args.gpu_vrams.split()]
    elif args.total_vram:
        gpu_vrams = [args.total_vram // args.gpu_count] * args.gpu_count

    total_vram = args.total_vram or sum(gpu_vrams)

    profile_id, profile = select_profile(
        profiles,
        args.vendor,
        args.gpu_count,
        total_vram,
        gpu_vrams,
        args.profile
    )

    vendor_config = get_vendor_config(profiles, args.vendor)
    output_env_vars(profile_id, profile, vendor_config)


if __name__ == '__main__':
    main()