# ClawDBot Deployment Checklist

## ✅ Pre-Deployment (COMPLETED)

- [x] SSH public key provided
- [x] TELEGRAM_BOT_TOKEN confirmed set
- [x] TELEGRAM_ALLOWED_IDS confirmed set
- [x] LOCAL_LLM_ENDPOINT reachable
- [x] LOCAL_LLM health check PASSED
- [x] API fallback LLM configured

## 🚀 Deployment Steps

### Step 1: Choose VPS Provider

**Recommended: Oracle Cloud Always Free**
- 2x ARM Ampere cores
- 24GB RAM (free tier)
- No credit card required

### Step 2: Provision VPS

```bash
# Create instance (Ubuntu 22.04 ARM)
# Add your SSH key during creation
# Note the public IP
```

### Step 3: Deploy ClawDBot

```bash
# SSH into VPS
ssh ubuntu@YOUR_VPS_IP

# Install git and clone
git clone <your-repo-url>
cd clawdbot

# Set environment variables
export TELEGRAM_BOT_TOKEN="8215402085:AAGRcj73pjlSNSOte0p6-ZLhaPIHMYwuDTw"
export TELEGRAM_ALLOWED_IDS="5836707779"
export LOCAL_LLM_API_BASE="https://saint-intent-cigarette-listening.trycloudflare.com/v1"
export LOCAL_LLM_MODEL="openai/gpt-oss-20b"
export LOCAL_LLM_TIMEOUT="60"
export OPENAI_API_KEY="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"

# Run deployment
chmod +x deploy.sh
./deploy.sh oracle
```

### Step 4: Verify Deployment

```bash
# Check container status
docker-compose ps

# View logs
docker-compose logs -f

# Test bot
# Message @Veraldo_bot on Telegram
```

### Step 5: Telegram Commands Test

| Command | Expected Result |
|---------|-----------------|
| `/start` | Welcome message |
| `/status` | Uptime, message count |
| `/health` | Both LLMs healthy |
| `/model` | LOCAL active, gpt-oss-20b |
| Send text | AI response via local LLM |

## 🔧 Post-Deployment

### Persistent Tunnel (Recommended)

The quick tunnel expires when stopped. For production:

```bash
# On your local machine:
cloudflared tunnel create clawdbot
cloudflared tunnel route dns clawdbot llm.yourdomain.com
cloudflared tunnel run clawdbot
```

Update `LOCAL_LLM_API_BASE` to your persistent domain.

### systemd Service (Auto-start)

```bash
# On VPS
sudo cp clawdbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable clawdbot
sudo systemctl start clawdbot
```

### Monitoring

```bash
# View logs
sudo journalctl -u clawdbot -f

# Or Docker logs
docker-compose logs -f --tail=100
```

## 📋 Safe Output Summary (For Documentation)

```
VPS Provider:    Oracle Cloud (recommended) / Fly.io / Railway
SSH Access:      ssh clawdbot@<vps-ip> (key auth only)
Local LLM:       ✅ CONNECTED (2838ms latency)
Active Model:    openai/gpt-oss-20b
Source:          User Local Machine (≥32GB RAM)
Tunnel:          Cloudflare (quick)
Fallbacks:       1 (OpenAI gpt-4o-mini)
Telegram Bot:    @Veraldo_bot
Control:         Telegram commands (/status, /health, /restart)
Logs:            docker-compose logs -f
Restart:         docker-compose restart
```

## ⚠️ Security Notes

- SSH key authentication only (no passwords)
- Root login disabled
- Non-root container user
- Secrets in environment variables only
- No secrets in logs

## 🆘 Troubleshooting

| Issue | Solution |
|-------|----------|
| Bot not responding | Check `/health` in Telegram |
| Local LLM unhealthy | Restart tunnel on local machine |
| Fallback not working | Verify OPENAI_API_KEY |
| High latency | Check local machine resources |
