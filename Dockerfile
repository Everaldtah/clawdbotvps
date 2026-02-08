# ClawDBot - Lightweight Telegram Bot Container
# Optimized for low-resource VPS / Fly.io

FROM python:3.11-slim

# Security: non-root user
RUN groupadd -r clawdbot && useradd -r -g clawdbot clawdbot

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY bot.py .

# Ownership
RUN chown -R clawdbot:clawdbot /app

USER clawdbot

# Unbuffered output for logging
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check via the built-in web server
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

EXPOSE 8080

CMD ["python", "bot.py"]
