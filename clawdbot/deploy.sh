#!/bin/bash
# ClawDBot Deployment Script
# ==========================
# Usage: ./deploy.sh [oracle|fly|railway|render|github]

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/yourusername/clawdbot.git"
DEPLOY_DIR="/opt/clawdbot"
SSH_KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHywOCtH3Ov/UmGzYDxrxC79TrIw79nPn/+nVDsV0086 clawdbot-deploy"

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check environment variables
check_env() {
    log_info "Checking environment variables..."
    
    local missing=()
    
    [[ -z "$TELEGRAM_BOT_TOKEN" ]] && missing+=("TELEGRAM_BOT_TOKEN")
    [[ -z "$TELEGRAM_ALLOWED_IDS" ]] && missing+=("TELEGRAM_ALLOWED_IDS")
    [[ -z "$LOCAL_LLM_API_BASE" ]] && missing+=("LOCAL_LLM_API_BASE")
    [[ -z "$LOCAL_LLM_MODEL" ]] && missing+=("LOCAL_LLM_MODEL")
    
    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required environment variables:"
        printf '%s\n' "${missing[@]}"
        exit 1
    fi
    
    log_info "Environment variables OK"
}

# VPS hardening
harden_vps() {
    log_info "Applying VPS security hardening..."
    
    # Create non-root user
    if ! id -u clawdbot &>/dev/null; then
        sudo useradd -m -s /bin/bash clawdbot
        log_info "Created user: clawdbot"
    fi
    
    # Add SSH key
    sudo mkdir -p /home/clawdbot/.ssh
    echo "$SSH_KEY" | sudo tee /home/clawdbot/.ssh/authorized_keys > /dev/null
    sudo chmod 700 /home/clawdbot/.ssh
    sudo chmod 600 /home/clawdbot/.ssh/authorized_keys
    sudo chown -R clawdbot:clawdbot /home/clawdbot/.ssh
    log_info "SSH key added for clawdbot user"
    
    # Configure SSH (disable root, password auth)
    if [[ -f /etc/ssh/sshd_config ]]; then
        sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
        sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
        sudo systemctl restart sshd 2>/dev/null || true
        log_info "SSH hardening applied"
    fi
}

# Install Docker
install_docker() {
    if command -v docker &> /dev/null; then
        log_info "Docker already installed"
        return
    fi
    
    log_info "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker clawdbot
    log_info "Docker installed"
}

# Deploy application
deploy_app() {
    log_info "Deploying ClawDBot..."
    
    # Create deployment directory
    sudo mkdir -p "$DEPLOY_DIR"
    
    # Copy files
    sudo cp docker-compose.yml Dockerfile bot.py requirements.txt "$DEPLOY_DIR/"
    
    # Create .env file
    sudo tee "$DEPLOY_DIR/.env" > /dev/null <<EOF
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_ALLOWED_IDS=${TELEGRAM_ALLOWED_IDS}
LOCAL_LLM_API_BASE=${LOCAL_LLM_API_BASE}
LOCAL_LLM_MODEL=${LOCAL_LLM_MODEL}
LOCAL_LLM_TIMEOUT=${LOCAL_LLM_TIMEOUT:-60}
OPENAI_API_KEY=${OPENAI_API_KEY:-}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
EOF
    
    sudo chown -R clawdbot:clawdbot "$DEPLOY_DIR"
    
    # Build and start
    cd "$DEPLOY_DIR"
    sudo docker-compose down 2>/dev/null || true
    sudo docker-compose build --no-cache
    sudo docker-compose up -d
    
    log_info "ClawDBot deployed successfully!"
}

# Oracle Cloud specific setup
setup_oracle() {
    log_info "Setting up for Oracle Cloud..."
    
    # Open firewall for SSH (if needed)
    sudo firewall-cmd --permanent --add-service=ssh 2>/dev/null || true
    sudo firewall-cmd --reload 2>/dev/null || true
    
    harden_vps
    install_docker
    deploy_app
}

# Fly.io deployment
setup_fly() {
    log_info "Deploying to Fly.io..."
    
    if ! command -v flyctl &> /dev/null; then
        log_error "flyctl not installed. Install from https://fly.io/docs/hands-on/install-flyctl/"
        exit 1
    fi
    
    # Create fly.toml
    cat > fly.toml <<'EOF'
app = "clawdbot"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"

[env]
  LOCAL_LLM_TIMEOUT = "60"

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 512
EOF
    
    # Set secrets
    flyctl secrets set TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN"
    flyctl secrets set TELEGRAM_ALLOWED_IDS="$TELEGRAM_ALLOWED_IDS"
    flyctl secrets set LOCAL_LLM_API_BASE="$LOCAL_LLM_API_BASE"
    flyctl secrets set LOCAL_LLM_MODEL="$LOCAL_LLM_MODEL"
    [[ -n "$OPENAI_API_KEY" ]] && flyctl secrets set OPENAI_API_KEY="$OPENAI_API_KEY"
    
    # Deploy
    flyctl deploy
    
    log_info "ClawDBot deployed to Fly.io!"
}

# Railway deployment
setup_railway() {
    log_info "Deploying to Railway..."
    
    if ! command -v railway &> /dev/null; then
        log_error "Railway CLI not installed. Install from https://docs.railway.app/develop/cli"
        exit 1
    fi
    
    # Login and deploy
    railway login
    railway init
    
    # Set variables
    railway variables set TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN"
    railway variables set TELEGRAM_ALLOWED_IDS="$TELEGRAM_ALLOWED_IDS"
    railway variables set LOCAL_LLM_API_BASE="$LOCAL_LLM_API_BASE"
    railway variables set LOCAL_LLM_MODEL="$LOCAL_LLM_MODEL"
    railway variables set LOCAL_LLM_TIMEOUT="60"
    [[ -n "$OPENAI_API_KEY" ]] && railway variables set OPENAI_API_KEY="$OPENAI_API_KEY"
    
    railway up
    
    log_info "ClawDBot deployed to Railway!"
}

# Render deployment
setup_render() {
    log_info "Deploying to Render..."
    log_warn "For Render, use the web dashboard:"
    log_warn "1. Create a new Web Service"
    log_warn "2. Connect your GitHub repo"
    log_warn "3. Set environment variables in dashboard"
    log_warn "4. Deploy"
}

# GitHub Codespaces
codespaces_setup() {
    log_info "GitHub Codespaces detected"
    log_warn "For Codespaces, use devcontainer configuration"
    log_warn "See: .devcontainer/devcontainer.json"
}

# Main
main() {
    local provider="${1:-oracle}"
    
    log_info "ClawDBot Deployment"
    log_info "Provider: $provider"
    
    check_env
    
    case "$provider" in
        oracle)
            setup_oracle
            ;;
        fly)
            setup_fly
            ;;
        railway)
            setup_railway
            ;;
        render)
            setup_render
            ;;
        github|codespaces)
            codespaces_setup
            ;;
        *)
            log_error "Unknown provider: $provider"
            echo "Usage: $0 [oracle|fly|railway|render|github]"
            exit 1
            ;;
    esac
    
    log_info "Deployment complete!"
}

main "$@"
