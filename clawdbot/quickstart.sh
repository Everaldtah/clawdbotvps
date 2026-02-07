#!/bin/bash
# ClawDBot Quick Start Script
# ============================

set -e

echo "🤖 ClawDBot Quick Start"
echo "========================"

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not installed"
    echo "Install from: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose not installed"
    exit 1
fi

echo "✅ Docker found"

# Check .env file
if [[ ! -f .env ]]; then
    echo "⚠️  .env file not found"
    echo "Creating from template..."
    cp .env.example .env
    echo "❌ Please edit .env with your configuration"
    exit 1
fi

echo "✅ .env file found"

# Validate required vars
source .env

missing=()
[[ -z "$TELEGRAM_BOT_TOKEN" ]] && missing+=("TELEGRAM_BOT_TOKEN")
[[ -z "$TELEGRAM_ALLOWED_IDS" ]] && missing+=("TELEGRAM_ALLOWED_IDS")
[[ -z "$LOCAL_LLM_API_BASE" ]] && missing+=("LOCAL_LLM_API_BASE")
[[ -z "$LOCAL_LLM_MODEL" ]] && missing+=("LOCAL_LLM_MODEL")

if [[ ${#missing[@]} -gt 0 ]]; then
    echo "❌ Missing required variables in .env:"
    printf '  - %s\n' "${missing[@]}"
    exit 1
fi

echo "✅ Environment variables set"

# Test local LLM connectivity
echo ""
echo "🔍 Testing Local LLM connectivity..."
if curl -s "$LOCAL_LLM_API_BASE/models" -m 10 > /dev/null 2>&1; then
    echo "✅ Local LLM reachable"
else
    echo "⚠️  Local LLM not reachable"
    echo "   Make sure your tunnel is active:"
    echo "   cloudflared tunnel --url http://localhost:11434"
fi

# Build and start
echo ""
echo "🚀 Building and starting ClawDBot..."
docker-compose down 2>/dev/null || true
docker-compose build --no-cache
docker-compose up -d

echo ""
echo "✅ ClawDBot started!"
echo ""
echo "📋 Useful commands:"
echo "  View logs:    docker-compose logs -f"
echo "  Stop:         docker-compose down"
echo "  Restart:      docker-compose restart"
echo ""
echo "💬 Message your bot on Telegram to test!"
