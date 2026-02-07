# ClawDBot - Lightweight Telegram Bot Container
# Optimized for: ≤512MB RAM, ≤1 CPU (orchestration-only)
# ================================================

FROM python:3.11-slim

# Security: Run as non-root
RUN groupadd -r clawdbot && useradd -r -g clawdbot clawdbot

# Set working directory
WORKDIR /app

# Install dependencies first (for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY bot.py .

# Set ownership
RUN chown -R clawdbot:clawdbot /app

# Switch to non-root user
USER clawdbot

# Environment defaults
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Run bot
CMD ["python", "bot.py"]
