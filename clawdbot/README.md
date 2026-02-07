# 🤖 ClawDBot

AI-powered Telegram bot with remote LLM support. Runs on low-resource VPS while using your local machine (≥32GB RAM) for inference via secure tunnel.

## Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   Telegram      │◄───────►│   VPS (Vercel)   │◄───────►│  Your Local PC  │
│   Users         │         │   ClawDBot       │  Tunnel │  LLM (32GB+)    │
│                 │         │   ≤512MB RAM     │         │  Ollama/LMStudio│
└─────────────────┘         └──────────────────┘         └─────────────────┘
                                    │
                                    ▼ (fallback)
                            ┌──────────────────┐
                            │   OpenAI/Claude  │
                            │   API (backup)   │
                            └──────────────────┘
```

## Features

- ✅ **Remote LLM**: Uses your local machine via secure tunnel (Cloudflare/Tailscale)
- ✅ **Automatic Fallback**: Switches to OpenAI if local LLM fails
- ✅ **Telegram Control**: `/status`, `/health`, `/model`, `/restart`, `/shutdown`
- ✅ **Low Resource**: Runs on ≤512MB RAM, ≤1 CPU
- ✅ **Security**: Non-root user, SSH key auth only

## Prerequisites

### 1. Local LLM Setup (Your Machine)

**Option A: Ollama**
```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Start server (listens on all interfaces)
OLLAMA_HOST=0.0.0.0:11434 ollama serve

# Pull model
ollama pull qwen2.5:14b
```

**Option B: LM Studio**
1. Open LM Studio
2. Start local server (Settings → Server → Start Server)
3. Note the endpoint URL

### 2. Secure Tunnel Setup

**Cloudflare Tunnel (Recommended)**
```bash
# Install cloudflared
brew install cloudflared  # macOS
# or
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64

# Create tunnel
cloudflared tunnel --url http://localhost:11434
# Copy the HTTPS URL (e.g., https://xxx.trycloudflare.com)
```

**Tailscale Funnel**
```bash
# Install Tailscale
# Enable funnel
tailscale funnel 11434
```

### 3. Telegram Bot

1. Message [@BotFather](https://t.me/BotFather)
2. Create new bot: `/newbot`
3. Copy the token
4. Get your user ID from [@userinfobot](https://t.me/userinfobot)

### 4. Fallback API (Required)

Get an OpenAI API key: https://platform.openai.com/api-keys

## Deployment

### Option 1: Oracle Cloud (Always Free)

```bash
# 1. Create free tier instance (Ubuntu 22.04, ARM)
# 2. SSH into instance
ssh ubuntu@YOUR_INSTANCE_IP

# 3. Clone and deploy
git clone https://github.com/yourusername/clawdbot.git
cd clawdbot

# 4. Set environment variables
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_ALLOWED_IDS="your_user_id"
export LOCAL_LLM_API_BASE="https://your-tunnel.trycloudflare.com/v1"
export LOCAL_LLM_MODEL="qwen2.5:14b"
export OPENAI_API_KEY="sk-..."

# 5. Run deployment
chmod +x deploy.sh
./deploy.sh oracle
```

### Option 2: Fly.io

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Set secrets
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_ALLOWED_IDS="..."
export LOCAL_LLM_API_BASE="..."
export LOCAL_LLM_MODEL="..."
export OPENAI_API_KEY="..."

# Deploy
./deploy.sh fly
```

### Option 3: Railway

```bash
# Install Railway CLI
npm install -g @railway/cli

# Deploy
./deploy.sh railway
```

### Option 4: Docker (Any VPS)

```bash
# Clone repository
git clone https://github.com/yourusername/clawdbot.git
cd clawdbot

# Create .env file
cp .env.example .env
# Edit .env with your values

# Deploy with Docker Compose
docker-compose up -d

# View logs
docker-compose logs -f
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Show welcome message |
| `/status` | Bot uptime, messages, errors |
| `/health` | LLM provider health check |
| `/model` | Active model and source info |
| `/restart` | Restart the bot |
| `/shutdown` | Graceful shutdown |

## Health Check Output Example

```
🩺 LLM Health Report
━━━━━━━━━━━━━━━━━━━━━

LOCAL
Status: 🟢 Healthy
Model: qwen2.5:14b
Latency: 480ms

OPENAI
Status: 🟢 Healthy
Model: gpt-4o-mini
Latency: 245ms
```

## Troubleshooting

### Local LLM Unreachable

```bash
# Test your tunnel
curl https://your-tunnel.trycloudflare.com/v1/models

# If fails, restart tunnel
cloudflared tunnel --url http://localhost:11434
```

### Bot Not Responding

```bash
# Check logs
docker-compose logs -f

# Restart
docker-compose restart
```

### Fallback Not Working

- Verify `OPENAI_API_KEY` is set
- Check key has available credits
- View `/health` in Telegram

## Security

- ✅ SSH key authentication only
- ✅ No root login
- ✅ No password authentication
- ✅ Read-only container filesystem
- ✅ Non-root container user
- ✅ Secrets never logged

## Resource Limits

| Resource | Limit |
|----------|-------|
| RAM | 512 MB |
| CPU | 1 core |
| Disk | 10 GB |
| Network | Outbound only |

## License

MIT License - See LICENSE file
