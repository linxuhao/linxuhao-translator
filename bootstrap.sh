#!/bin/bash
# VIP Gateway Bootstrap Installer
# One-line install: curl -fsSL https://raw.githubusercontent.com/xxx/vip-gateway/main/bootstrap.sh | bash
#
# This script:
#   1. Clones the vip-gateway repository
#   2. Runs install.sh to setup everything
#
set -e

REPO_URL="https://github.com/linxuhao/vip-gateway.git"
INSTALL_DIR="vip-gateway"

# Color output
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

# ==========================================
# Check if already in vip-gateway directory
# ==========================================

if [ -f "./install.sh" ] && [ -f "./config/hardware_profiles.yml" ]; then
    log_info "Already in vip-gateway directory"
    log_info "Running install.sh..."
    ./install.sh "$@"
    exit 0
fi

# ==========================================
# Check git
# ==========================================

if ! command -v git &>/dev/null; then
    log_error "Git is required but not installed"
    log_info "Install git:"
    echo "  Ubuntu/Debian: sudo apt install git"
    echo "  Fedora: sudo dnf install git"
    echo "  Arch: sudo pacman -S git"
    echo "  macOS: brew install git"
    exit 1
fi

log_ok "Git found: $(git --version)"

# ==========================================
# Clone repository
# ==========================================

log_info "Cloning vip-gateway repository..."

if [ -d "$INSTALL_DIR" ]; then
    log_warn "Directory '$INSTALL_DIR' already exists"
    read -p "$(echo -e ${YELLOW}Remove and re-clone? [Y/n]: ${NC})" -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        rm -rf "$INSTALL_DIR"
    else
        log_info "Using existing directory"
    fi
fi

if [ ! -d "$INSTALL_DIR" ]; then
    git clone "$REPO_URL" "$INSTALL_DIR"
    log_ok "Repository cloned to $INSTALL_DIR"
fi

# ==========================================
# Run install.sh
# ==========================================

cd "$INSTALL_DIR"
log_info "Running install.sh..."

# Pass all arguments to install.sh
./install.sh "$@"