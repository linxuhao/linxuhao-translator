#!/bin/bash
# VIP Gateway Hardware-Adaptive Installer
# Auto-detects GPU hardware and selects optimal profile from hardware_profiles.yml
# Auto-installs all dependencies (Docker, Python, venv, requirements)
set -e

VERSION="2.1.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILES_FILE="$SCRIPT_DIR/config/hardware_profiles.yml"
VENV_DIR="$SCRIPT_DIR/venv"

# Color output helpers
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${CYAN}[STEP]${NC} $1"; }

# ==========================================
# Dependency Installation Functions
# ==========================================

check_python() {
    if command -v python3 &>/dev/null; then
        PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
        log_ok "Python $PYTHON_VERSION found"
        return 0
    else
        log_error "Python3 not found"
        return 1
    fi
}

install_python() {
    log_step "Installing Python3..."

    # Detect OS
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS
        if command -v brew &>/dev/null; then
            brew install python3
        else
            log_error "Homebrew not found. Install Python manually."
            log_info "Visit: https://www.python.org/downloads/"
            return 1
        fi
    elif command -v apt-get &>/dev/null; then
        # Debian/Ubuntu
        sudo apt-get update
        sudo apt-get install -y python3 python3-pip python3-venv
    elif command -v yum &>/dev/null; then
        # RHEL/CentOS
        sudo yum install -y python3 python3-pip
    elif command -v dnf &>/dev/null; then
        # Fedora
        sudo dnf install -y python3 python3-pip
    elif command -v pacman &>/dev/null; then
        # Arch Linux
        sudo pacman -S --noconfirm python python-pip
    else
        log_error "Unknown OS. Install Python3 manually."
        return 1
    fi

    log_ok "Python3 installed"
}

setup_venv() {
    log_step "Setting up Python virtual environment..."

    # Check if venv is complete (has activate script)
    if [ -f "$VENV_DIR/bin/activate" ]; then
        log_info "venv already exists and is complete at $VENV_DIR"
    else
        # Remove incomplete venv if exists
        if [ -d "$VENV_DIR" ]; then
            log_warn "Incomplete venv found, recreating..."
            rm -rf "$VENV_DIR"
        fi
        python3 -m venv "$VENV_DIR"
        log_ok "Created venv at $VENV_DIR"
    fi

    # Activate venv
    source "$VENV_DIR/bin/activate"
    log_ok "Activated venv"
}

install_python_requirements() {
    log_step "Installing Python requirements..."

    # Install requirements for installer scripts
    if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
        pip install --upgrade pip
        pip install -r "$SCRIPT_DIR/requirements.txt"
        log_ok "Installed installer script dependencies"
    else
        pip install --upgrade pip pyyaml
        log_ok "Installed pyyaml"
    fi
}

check_docker() {
    if command -v docker &>/dev/null; then
        DOCKER_VERSION=$(docker --version 2>&1 | cut -d' ' -f3 | tr -d ',')
        log_ok "Docker $DOCKER_VERSION found"

        if docker compose version &>/dev/null; then
            log_ok "Docker Compose available"
            return 0
        else
            log_warn "Docker Compose not available"
            return 1
        fi
    else
        log_warn "Docker not found"
        return 1
    fi
}

install_docker() {
    log_step "Installing Docker..."

    # Detect OS
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS - Docker Desktop
        if command -v brew &>/dev/null; then
            brew install --cask docker
            log_ok "Installed Docker Desktop via Homebrew"
            log_info "Please start Docker Desktop from Applications"
        else
            log_error "Homebrew not found. Install Docker Desktop manually."
            log_info "Visit: https://docs.docker.com/desktop/install/mac-install/"
            return 1
        fi
    elif command -v apt-get &>/dev/null; then
        # Debian/Ubuntu
        log_info "Installing Docker via apt..."
        sudo apt-get update
        sudo apt-get install -y ca-certificates curl gnupg

        # Add Docker's official GPG key
        sudo install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        sudo chmod a+r /etc/apt/keyrings/docker.gpg

        # Add Docker repository
        echo \
          "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
          $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
          sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

        sudo apt-get update
        sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

        # Add user to docker group
        sudo usermod -aG docker $USER

        log_ok "Docker installed"
        log_warn "You may need to logout/login for docker group to take effect"

    elif command -v yum &>/dev/null; then
        # RHEL/CentOS
        sudo yum install -y yum-utils
        sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
        sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
        sudo systemctl enable --now docker
        sudo usermod -aG docker $USER
        log_ok "Docker installed"

    elif command -v dnf &>/dev/null; then
        # Fedora
        sudo dnf -y install dnf-plugins-core
        sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
        sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
        sudo systemctl enable --now docker
        sudo usermod -aG docker $USER
        log_ok "Docker installed"

    elif command -v pacman &>/dev/null; then
        # Arch Linux
        sudo pacman -S --noconfirm docker docker-compose
        sudo systemctl enable --now docker
        sudo usermod -aG docker $USER
        log_ok "Docker installed"
    else
        log_error "Unknown OS. Install Docker manually."
        log_info "Visit: https://docs.docker.com/engine/install/"
        return 1
    fi

    return 0
}

start_docker_service() {
    # Check if Docker daemon is running
    if ! docker info &>/dev/null 2>&1; then
        log_step "Starting Docker service..."

        if command -v systemctl &>/dev/null; then
            sudo systemctl start docker
        elif [[ "$(uname)" == "Darwin" ]]; then
            log_warn "On macOS, start Docker Desktop from Applications"
        else
            sudo service docker start
        fi

        sleep 3

        if docker info &>/dev/null 2>&1; then
            log_ok "Docker service started"
        else
            log_warn "Docker may not be running. Start manually if needed."
        fi
    fi
}

# ==========================================
# Hardware Detection Functions
# ==========================================

detect_gpu_vendor() {
    # NVIDIA detection
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null 2>&1; then
        echo "nvidia"
        return 0
    fi

    # AMD ROCm detection
    if [ -d "/sys/class/kfd" ] || command -v rocm-smi &>/dev/null; then
        echo "amd"
        return 0
    fi

    # Apple Silicon detection
    if [[ "$(uname)" == "Darwin" ]]; then
        cpu_brand=$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "")
        if [[ "$cpu_brand" =~ "Apple" ]]; then
            echo "apple"
            return 0
        fi
    fi

    # Intel detection
    if command -v lspci &>/dev/null; then
        if lspci 2>/dev/null | grep -qiE "intel.*(gpu|graphics|arc)"; then
            echo "intel"
            return 0
        fi
    fi

    echo "none"
}

detect_nvidia_gpus() {
    local gpu_info
    gpu_info=$(nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader,nounits 2>/dev/null)

    GPU_COUNT=0
    TOTAL_VRAM_MB=0
    declare -ga GPU_NAMES
    declare -ga GPU_VRAMS

    while IFS=', ' read -r idx name vram; do
        if [ -n "$idx" ]; then
            GPU_NAMES[$idx]="$name"
            GPU_VRAMS[$idx]=$vram
            TOTAL_VRAM_MB=$((TOTAL_VRAM_MB + vram))
            GPU_COUNT=$((GPU_COUNT + 1))
        fi
    done <<< "$gpu_info"

    export GPU_NAMES GPU_VRAMS GPU_COUNT TOTAL_VRAM_MB
}

detect_amd_gpus() {
    GPU_COUNT=0
    TOTAL_VRAM_MB=0
    declare -ga GPU_NAMES
    declare -ga GPU_VRAMS

    # Try rocm-smi
    if command -v rocm-smi &>/dev/null; then
        local idx=0
        while IFS=',' read -r card vram rest; do
            if [[ "$card" =~ ^card ]]; then
                local vram_mb=$((vram / 1024 / 1024))
                if [ "$vram_mb" -gt 0 ]; then
                    GPU_NAMES[$idx]="AMD GPU $idx"
                    GPU_VRAMS[$idx]=$vram_mb
                    TOTAL_VRAM_MB=$((TOTAL_VRAM_MB + vram_mb))
                    GPU_COUNT=$((GPU_COUNT + 1))
                    idx=$((idx + 1))
                fi
            fi
        done <<< "$(rocm-smi --showmeminfo vram --csv 2>/dev/null || echo '')"
    fi

    # Fallback: sysfs
    if [ "$GPU_COUNT" -eq 0 ] && [ -d "/sys/class/kfd/kfd/topology/nodes" ]; then
        local idx=0
        for node_path in /sys/class/kfd/kfd/topology/nodes/*/; do
            if [ -f "$node_path/name" ]; then
                local name=$(cat "$node_path/name" 2>/dev/null || echo "AMD GPU")
                local vram_bytes=$(cat "$node_path/mem_banks/0/size" 2>/dev/null || echo "0")
                local vram_mb=$((vram_bytes / 1024 / 1024))

                if [ "$vram_mb" -gt 0 ]; then
                    GPU_NAMES[$idx]="$name"
                    GPU_VRAMS[$idx]=$vram_mb
                    TOTAL_VRAM_MB=$((TOTAL_VRAM_MB + vram_mb))
                    GPU_COUNT=$((GPU_COUNT + 1))
                    idx=$((idx + 1))
                fi
            fi
        done
    fi

    export GPU_NAMES GPU_VRAMS GPU_COUNT TOTAL_VRAM_MB
}

detect_apple_gpu() {
    local mem_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
    TOTAL_VRAM_MB=$((mem_bytes / 1024 / 1024))
    GPU_COUNT=1
    GPU_NAMES[0]="Apple Silicon Unified Memory"
    GPU_VRAMS[0]=$TOTAL_VRAM_MB
    export GPU_NAMES GPU_VRAMS GPU_COUNT TOTAL_VRAM_MB
}

detect_intel_gpus() {
    GPU_COUNT=0
    TOTAL_VRAM_MB=0
    declare -ga GPU_NAMES
    declare -ga GPU_VRAMS

    if command -v lspci &>/dev/null; then
        local idx=0
        while IFS= read -r line; do
            if [[ "$line" =~ Intel.*(Arc|A770|A750|A380) ]]; then
                if [[ "$line" =~ A770 ]]; then
                    GPU_VRAMS[$idx]=16384
                    GPU_NAMES[$idx]="Intel Arc A770"
                elif [[ "$line" =~ A750 ]]; then
                    GPU_VRAMS[$idx]=8192
                    GPU_NAMES[$idx]="Intel Arc A750"
                elif [[ "$line" =~ A380 ]]; then
                    GPU_VRAMS[$idx]=6144
                    GPU_NAMES[$idx]="Intel Arc A380"
                else
                    GPU_VRAMS[$idx]=4096
                    GPU_NAMES[$idx]="Intel Integrated GPU"
                fi
                TOTAL_VRAM_MB=$((TOTAL_VRAM_MB + GPU_VRAMS[$idx]))
                GPU_COUNT=$((GPU_COUNT + 1))
                idx=$((idx + 1))
            fi
        done <<< "$(lspci 2>/dev/null)"
    fi

    export GPU_NAMES GPU_VRAMS GPU_COUNT TOTAL_VRAM_MB
}

# ==========================================
# Profile Selection (via Python)
# ==========================================

select_profile() {
    # Use Python to parse YAML and select profile
    if ! command -v python3 &>/dev/null; then
        log_error "Python3 is required to parse hardware_profiles.yml"
        exit 1
    fi

    local profile_script="$SCRIPT_DIR/scripts/select_profile.py"

    if [ -n "$SELECTED_PROFILE" ]; then
        # User specified profile
        SELECTED_PROFILE_DATA=$(python3 "$profile_script" \
            --profiles "$PROFILES_FILE" \
            --profile "$SELECTED_PROFILE" \
            --vendor "$GPU_VENDOR" \
            --gpu-count "$GPU_COUNT" \
            --total-vram "$TOTAL_VRAM_MB" \
            --gpu-vrams "${GPU_VRAMS[*]}" \
            2>&1)
    else
        # Auto-select
        SELECTED_PROFILE_DATA=$(python3 "$profile_script" \
            --profiles "$PROFILES_FILE" \
            --vendor "$GPU_VENDOR" \
            --gpu-count "$GPU_COUNT" \
            --total-vram "$TOTAL_VRAM_MB" \
            --gpu-vrams "${GPU_VRAMS[*]}" \
            2>&1)
    fi

    if [[ "$SELECTED_PROFILE_DATA" =~ ^ERROR: ]]; then
        log_error "${SELECTED_PROFILE_DATA#ERROR: }"
        exit 1
    fi

    # Parse returned data into environment variables
    eval "$SELECTED_PROFILE_DATA"
}

# ==========================================
# Configuration Generation
# ==========================================

generate_hardware_env() {
    local env_file="$SCRIPT_DIR/config/generated/hardware.env"

    mkdir -p "$SCRIPT_DIR/config/generated"

    # Find best GPU indices for dual setup
    local llm_gpu=0
    local asr_gpu=0

    if [ "$GPU_COUNT" -ge 2 ]; then
        # Find GPU with most VRAM for LLM
        local best_vram=${GPU_VRAMS[0]}
        llm_gpu=0
        for i in "${!GPU_VRAMS[@]}"; do
            if [ "${GPU_VRAMS[$i]}" -gt "$best_vram" ]; then
                best_vram="${GPU_VRAMS[$i]}"
                llm_gpu=$i
            fi
        done
        # Use another GPU for ASR
        for i in "${!GPU_VRAMS[@]}"; do
            if [ "$i" -ne "$llm_gpu" ]; then
                asr_gpu=$i
                break
            fi
        done
    fi

    cat > "$env_file" << EOF
# Auto-generated hardware profile - DO NOT EDIT MANUALLY
# Generated: $(date -Iseconds)
# Installer version: $VERSION

PROFILE_ID=$PROFILE_ID
PROFILE_NAME=$PROFILE_NAME

GPU_VENDOR=$GPU_VENDOR
GPU_COUNT=$GPU_COUNT
TOTAL_VRAM_MB=$TOTAL_VRAM_MB
DEPLOYMENT_STRATEGY=$STRATEGY

# GPU Details
$(for i in "${!GPU_NAMES[@]}"; do echo "GPU_${i}_NAME=\"${GPU_NAMES[$i]}\""; echo "GPU_${i}_VRAM=${GPU_VRAMS[$i]}"; done)

# Model Configuration
LLM_MODEL=$LLM_MODEL
LLM_GPU_INDEX=$llm_gpu
LLM_GPU_UTIL=$LLM_GPU_UTIL
LLM_MAX_MODEL_LEN=$MAX_MODEL_LEN

ASR_MODEL=$ASR_MODEL
ASR_GPU_INDEX=$asr_gpu
ASR_GPU_UTIL=$ASR_GPU_UTIL

# Container Configuration
VLLM_IMAGE=$VLLM_IMAGE
GPU_ENV_VAR=$GPU_ENV_VAR
MAX_CONCURRENT_TASKS=$MAX_CONCURRENT

# Device Passthrough (AMD specific)
DEVICE_KFD=$([ "$GPU_VENDOR" == "amd" ] && echo "true" || echo "false")
DEVICE_DRI=$([ "$GPU_VENDOR" == "amd" ] && echo "true" || echo "false")
EOF

    log_ok "Generated hardware.env"
}

generate_docker_compose() {
    local output_file="$SCRIPT_DIR/docker-compose.yml"

    python3 "$SCRIPT_DIR/scripts/generate_config.py" \
        --env "$SCRIPT_DIR/config/generated/hardware.env" \
        --output "$output_file"

    log_ok "Generated docker-compose.yml"
}

# ==========================================
# Verification Functions
# ==========================================

verify_docker() {
    if check_docker; then
        start_docker_service
        return 0
    fi

    log_warn "Docker is required for this project"
    read -p "$(echo -e ${YELLOW}Install Docker now? [Y/n]: ${NC})" -n 1 -r
    echo ""

    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        install_docker
        start_docker_service
        return 0
    else
        log_error "Docker is required. Cannot continue."
        return 1
    fi
}

verify_gpu_driver() {
    case $GPU_VENDOR in
        nvidia)
            if ! nvidia-smi &>/dev/null; then
                log_error "NVIDIA driver not working"
                log_info "Install NVIDIA driver: https://www.nvidia.com/Download/"
                exit 1
            fi
            ;;
        amd)
            if [ ! -d "/sys/class/kfd" ]; then
                log_error "ROCm driver not installed"
                log_info "Install ROCm: https://rocm.docs.amd.com/"
                exit 1
            fi
            ;;
        intel)
            log_warn "Intel Arc requires OpenCL/SYCL drivers"
            ;;
        apple)
            log_info "Apple Silicon - Metal acceleration"
            ;;
    esac
    log_ok "GPU driver verified for $GPU_VENDOR"
}

display_summary() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║              Hardware Detection Summary                  ║${NC}"
    echo -e "${CYAN}╠══════════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║ GPU Vendor:    ${GREEN}$GPU_VENDOR${NC}"
    echo -e "${CYAN}║ GPU Count:     ${GREEN}$GPU_COUNT${NC}"
    echo -e "${CYAN}║ Total VRAM:    ${GREEN}${TOTAL_VRAM_MB}MB${NC}"
    for i in "${!GPU_NAMES[@]}"; do
        printf "${CYAN}║ GPU %d:         ${GREEN}%s (%dMB)${NC}\n" "$i" "${GPU_NAMES[$i]}" "${GPU_VRAMS[$i]}"
    done
    echo -e "${CYAN}╠══════════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║              Selected Profile                             ║${NC}"
    echo -e "${CYAN}╠══════════════════════════════════════════════════════════╣${NC}"
    echo -e "${CYAN}║ Profile:       ${GREEN}$PROFILE_ID${NC}"
    echo -e "${CYAN}║ Name:          ${GREEN}$PROFILE_NAME${NC}"
    echo -e "${CYAN}║ LLM Model:     ${GREEN}$LLM_MODEL${NC}"
    echo -e "${CYAN}║ ASR Model:     ${GREEN}$ASR_MODEL${NC}"
    echo -e "${CYAN}║ Max Concurrent:${GREEN}$MAX_CONCURRENT requests${NC}"
    echo -e "${CYAN}║ vLLM Image:    ${GREEN}$VLLM_IMAGE${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

list_profiles() {
    python3 "$SCRIPT_DIR/scripts/select_profile.py" --list --profiles "$PROFILES_FILE"
}

# ==========================================
# Installation Functions
# ==========================================

pull_images() {
    log_step "Pulling Docker images..."
    cd "$SCRIPT_DIR"
    docker compose pull || true
    log_ok "Images pulled"
}

start_services() {
    log_step "Starting services..."
    cd "$SCRIPT_DIR"
    docker compose up -d
    log_ok "Services started"
}

wait_for_services() {
    log_info "Waiting for services..."
    local max_wait=120
    local waited=0

    while [ $waited -lt $max_wait ]; do
        if curl -s http://localhost:5000/ >/dev/null 2>&1; then
            log_ok "Gateway ready"
            break
        fi
        sleep 5
        waited=$((waited + 5))
        echo -n "."
    done
    echo ""

    if [ $waited -ge $max_wait ]; then
        log_warn "Services may need more time"
        log_info "Check: docker compose ps"
    fi
}

# ==========================================
# CLI Arguments
# ==========================================

parse_args() {
    SELECTED_PROFILE=""
    DRY_RUN=false
    NO_START=false
    SKIP_DEPS=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            --profile|-p)
                SELECTED_PROFILE="$2"
                shift 2
                ;;
            --list-profiles|--list)
                list_profiles
                exit 0
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --no-start)
                NO_START=true
                shift
                ;;
            --skip-deps)
                SKIP_DEPS=true
                shift
                ;;
            --reconfigure)
                shift
                ;;
            --help|-h)
                echo "VIP Gateway Hardware-Adaptive Installer v${VERSION}"
                echo ""
                echo "Usage: ./install.sh [options]"
                echo ""
                echo "Automatic Installation Phases:"
                echo "  Phase 0 - Check/install Python3, Docker, venv, dependencies"
                echo "  Phase 1 - Detect GPU vendor and VRAM"
                echo "  Phase 2 - Select optimal hardware profile"
                echo "  Phase 3 - Generate docker-compose.yml"
                echo "  Phase 4 - Deploy services"
                echo ""
                echo "Options:"
                echo "  --profile NAME     Use specific profile (see --list-profiles)"
                echo "  --list-profiles    Show all available hardware profiles"
                echo "  --dry-run          Stop after Phase 2 (show detection only)"
                echo "  --no-start         Stop after Phase 3 (don't deploy)"
                echo "  --skip-deps        Skip Phase 0 (assume dependencies installed)"
                echo "  --reconfigure      Re-run detection and regenerate configs"
                echo "  --help             Show this help"
                echo ""
                echo "Example profiles:"
                echo "  nvidia_single_24gb    - RTX 3090/4090"
                echo "  nvidia_dual_40gb      - RTX 4090 + RTX 4080"
                echo "  amd_dual_40gb         - RX 7900 XTX + RX 7800 XT"
                echo "  apple_16gb            - M1/M2 Pro with 16GB"
                echo "  intel_single_16gb     - Intel Arc A770"
                echo ""
                echo "Supported OS: Ubuntu/Debian, Fedora/RHEL/CentOS, Arch Linux, macOS"
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
}

# ==========================================
# Main Execution
# ==========================================

main() {
    parse_args "$@"

    log_info "VIP Gateway Hardware-Adaptive Installer v${VERSION}"
    echo ""

    # ==========================================
    # Phase 0: Dependencies Installation
    # ==========================================
    if [ "$SKIP_DEPS" != "true" ]; then
        log_step "Phase 0: Dependency Check & Installation"

        # Check Python
        if ! check_python; then
            log_warn "Python3 is required"
            read -p "$(echo -e ${YELLOW}Install Python3 now? [Y/n]: ${NC})" -n 1 -r
            echo ""
            if [[ ! $REPLY =~ ^[Nn]$ ]]; then
                install_python
            else
                log_error "Python3 is required. Cannot continue."
                exit 1
            fi
        fi

        # Setup venv and install requirements
        setup_venv
        install_python_requirements

        # Check Docker
        verify_docker
    else
        log_info "Skipping dependency installation (--skip-deps)"
        # Still need to activate venv if it exists, or just use system Python
        if [ -f "$VENV_DIR/bin/activate" ]; then
            source "$VENV_DIR/bin/activate"
        else
            log_warn "venv not found or incomplete, using system Python"
        fi
    fi

    # ==========================================
    # Phase 1: Hardware Detection
    # ==========================================
    log_step "Phase 1: Hardware Detection"

    GPU_VENDOR=$(detect_gpu_vendor)
    log_info "Detected GPU vendor: $GPU_VENDOR"

    case $GPU_VENDOR in
        nvidia) detect_nvidia_gpus ;;
        amd)    detect_amd_gpus ;;
        apple)  detect_apple_gpu ;;
        intel)  detect_intel_gpus ;;
        none)
            log_error "No supported GPU detected"
            log_info "Supported: NVIDIA, AMD ROCm, Apple Silicon, Intel Arc"
            exit 1
            ;;
    esac

    verify_gpu_driver
    log_info "Found $GPU_COUNT GPU(s) with ${TOTAL_VRAM_MB}MB total VRAM"

    # ==========================================
    # Phase 2: Profile Selection
    # ==========================================
    log_step "Phase 2: Profile Selection"
    select_profile

    display_summary

    if [ "$DRY_RUN" == "true" ]; then
        log_info "Dry run complete."
        exit 0
    fi

    # ==========================================
    # Phase 3: Configuration Generation
    # ==========================================
    log_step "Phase 3: Configuration Generation"

    if [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
        if [ ! -f "$SCRIPT_DIR/docker-compose.example.yml" ]; then
            cp "$SCRIPT_DIR/docker-compose.yml" "$SCRIPT_DIR/docker-compose.example.yml"
            log_ok "Preserved original config"
        fi
    fi

    generate_hardware_env
    generate_docker_compose

    if [ "$NO_START" != "true" ]; then
        log_step "Phase 4: Deployment"

        read -p "$(echo -e ${YELLOW}Deploy now? [Y/n]: ${NC})" -n 1 -r
        echo ""

        if [[ $REPLY =~ ^[Nn]$ ]]; then
            log_info "Skipped. Run: docker compose up -d"
            exit 0
        fi

        pull_images
        start_services
        wait_for_services

        echo ""
        log_ok "Installation complete!"
        echo ""
        echo -e "${CYAN}Access: http://localhost:5000/${NC}"
        echo -e "${CYAN}Admin:  http://localhost:5000/admin${NC}"
    else
        log_ok "Config generated. Run: docker compose up -d"
    fi
}

main "$@"