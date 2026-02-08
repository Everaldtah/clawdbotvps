#!/usr/bin/env python3
"""
ClawDBot - AI-Powered Telegram Bot with Remote LLM Support
===========================================================
VPS/Fly.io: Orchestration-only (lightweight)
LLM: Remote (User's local machine via secure tunnel) with API fallback

Run: python bot.py
"""

import os
import sys
import time
import signal
import logging
import asyncio
import aiohttp
import aiohttp.web
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("clawdbot")

# =============================================================================
# CONFIGURATION
# =============================================================================


@dataclass
class Config:
    """Bot configuration from environment variables."""

    # Telegram
    TELEGRAM_BOT_TOKEN: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "")
    )
    TELEGRAM_ALLOWED_IDS: List[str] = field(
        default_factory=lambda: [
            x.strip()
            for x in os.getenv("TELEGRAM_ALLOWED_IDS", "").split(",")
            if x.strip()
        ]
    )

    # Local LLM (Remote via tunnel)
    LOCAL_LLM_API_BASE: str = field(
        default_factory=lambda: os.getenv("LOCAL_LLM_API_BASE", "")
    )
    LOCAL_LLM_MODEL: str = field(
        default_factory=lambda: os.getenv("LOCAL_LLM_MODEL", "")
    )
    LOCAL_LLM_TIMEOUT: int = field(
        default_factory=lambda: int(os.getenv("LOCAL_LLM_TIMEOUT", "60"))
    )

    # Fallback APIs
    OPENAI_API_KEY: Optional[str] = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY")
    )

    # Web server port for health checks (Fly.io)
    PORT: int = field(
        default_factory=lambda: int(os.getenv("PORT", "8080"))
    )

    def validate(self) -> bool:
        """Validate required configuration. Returns True if valid."""
        ok = True
        if not self.TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN is not set")
            ok = False
        if not self.TELEGRAM_ALLOWED_IDS:
            logger.error("TELEGRAM_ALLOWED_IDS is not set")
            ok = False
        if not self.LOCAL_LLM_API_BASE:
            logger.warning(
                "LOCAL_LLM_API_BASE not set - only fallback APIs will be available"
            )
        return ok


# =============================================================================
# LLM PROVIDER MANAGEMENT
# =============================================================================


@dataclass
class LLMProvider:
    """Single LLM provider."""

    name: str
    api_base: str
    model: str
    api_key: Optional[str] = None
    timeout: int = 60
    healthy: bool = True
    last_error: Optional[str] = None
    latency_ms: float = 0.0


class LLMManager:
    """Manages LLM providers with automatic fallback."""

    def __init__(self, config: Config):
        self.config = config
        self.providers: List[LLMProvider] = []
        self.current_provider_index = 0
        self._setup_providers()

    def _setup_providers(self):
        # Priority 1: Local LLM via tunnel
        if self.config.LOCAL_LLM_API_BASE:
            self.providers.append(
                LLMProvider(
                    name="LOCAL",
                    api_base=self.config.LOCAL_LLM_API_BASE,
                    model=self.config.LOCAL_LLM_MODEL or "default",
                    timeout=self.config.LOCAL_LLM_TIMEOUT,
                )
            )

        # Priority 2: OpenAI fallback
        if self.config.OPENAI_API_KEY:
            self.providers.append(
                LLMProvider(
                    name="OPENAI",
                    api_base="https://api.openai.com/v1",
                    model="gpt-4o-mini",
                    api_key=self.config.OPENAI_API_KEY,
                    timeout=30,
                )
            )

        if not self.providers:
            logger.error("No LLM providers configured! Bot will not be able to respond.")
        else:
            logger.info(f"Initialized {len(self.providers)} LLM provider(s): "
                        f"{', '.join(p.name for p in self.providers)}")

    @property
    def current_provider(self) -> Optional[LLMProvider]:
        if not self.providers:
            return None
        return self.providers[self.current_provider_index]

    def switch_to_next_provider(self):
        if len(self.providers) <= 1:
            return
        old = self.current_provider.name
        self.current_provider_index = (self.current_provider_index + 1) % len(
            self.providers
        )
        new = self.current_provider.name
        logger.warning(f"Switched LLM provider: {old} -> {new}")

    async def health_check(self, provider: Optional[LLMProvider] = None) -> bool:
        prov = provider or self.current_provider
        if prov is None:
            return False

        try:
            start = time.time()
            async with aiohttp.ClientSession() as session:
                payload = {
                    "model": prov.model,
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "max_tokens": 10,
                    "temperature": 0.1,
                }
                headers = {"Content-Type": "application/json"}
                if prov.api_key:
                    headers["Authorization"] = f"Bearer {prov.api_key}"

                async with session.post(
                    f"{prov.api_base}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=prov.timeout),
                ) as resp:
                    prov.latency_ms = (time.time() - start) * 1000
                    prov.healthy = resp.status == 200
                    if not prov.healthy:
                        prov.last_error = f"HTTP {resp.status}"
                    return prov.healthy
        except Exception as e:
            prov.healthy = False
            prov.last_error = str(e)
            logger.warning(f"Health check failed for {prov.name}: {e}")
            return False

    async def generate(
        self, messages: List[Dict[str, str]], max_tokens: int = 1024
    ) -> Dict[str, Any]:
        """Generate response with automatic fallback across providers."""
        if not self.providers:
            return {"success": False, "error": "No LLM providers configured", "provider": "NONE"}

        attempts = 0
        max_attempts = len(self.providers)

        while attempts < max_attempts:
            provider = self.current_provider

            try:
                start = time.time()
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "model": provider.model,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": 0.7,
                    }
                    headers = {"Content-Type": "application/json"}
                    if provider.api_key:
                        headers["Authorization"] = f"Bearer {provider.api_key}"

                    async with session.post(
                        f"{provider.api_base}/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=provider.timeout),
                    ) as resp:
                        if resp.status == 200:
                            provider.latency_ms = (time.time() - start) * 1000
                            provider.healthy = True
                            result = await resp.json()
                            return {
                                "success": True,
                                "provider": provider.name,
                                "model": provider.model,
                                "content": result["choices"][0]["message"]["content"],
                                "latency_ms": provider.latency_ms,
                            }
                        else:
                            body = await resp.text()
                            raise Exception(f"HTTP {resp.status}: {body[:200]}")

            except Exception as e:
                provider.healthy = False
                provider.last_error = str(e)
                logger.warning(f"Generation failed with {provider.name}: {e}")

                if attempts < max_attempts - 1:
                    self.switch_to_next_provider()

                attempts += 1

        return {
            "success": False,
            "error": "All providers failed",
            "provider": "NONE",
        }


# =============================================================================
# BOT STATE
# =============================================================================


class BotState:
    def __init__(self):
        self.start_time = datetime.now()
        self.message_count = 0
        self.error_count = 0
        self.llm_manager: Optional[LLMManager] = None

    @property
    def uptime(self) -> str:
        delta = datetime.now() - self.start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"


bot_state = BotState()

# =============================================================================
# TELEGRAM HANDLERS
# =============================================================================


def is_authorized(user_id: int, config: Config) -> bool:
    return str(user_id) in config.TELEGRAM_ALLOWED_IDS


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config: Config = context.bot_data["config"]
    if not is_authorized(update.effective_user.id, config):
        await update.message.reply_text("Unauthorized.")
        return

    await update.message.reply_text(
        "ClawDBot - AI Assistant\n"
        "=======================\n"
        "Send me any message and I'll respond using AI.\n\n"
        "Commands:\n"
        "/status - Bot status\n"
        "/health - LLM health check\n"
        "/model  - Active model info\n"
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config: Config = context.bot_data["config"]
    if not is_authorized(update.effective_user.id, config):
        await update.message.reply_text("Unauthorized.")
        return

    llm_mgr = bot_state.llm_manager
    current = llm_mgr.current_provider if llm_mgr else None

    status_text = (
        "Bot Status\n"
        "==========\n"
        f"State: Running\n"
        f"Uptime: {bot_state.uptime}\n"
        f"Messages: {bot_state.message_count}\n"
        f"Errors: {bot_state.error_count}\n"
        f"Active LLM: {current.name if current else 'N/A'}\n"
        f"Model: {current.model if current else 'N/A'}"
    )

    await update.message.reply_text(status_text)


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config: Config = context.bot_data["config"]
    if not is_authorized(update.effective_user.id, config):
        await update.message.reply_text("Unauthorized.")
        return

    llm_mgr = bot_state.llm_manager
    if not llm_mgr or not llm_mgr.providers:
        await update.message.reply_text("No LLM providers configured.")
        return

    await update.message.reply_text("Running health checks...")

    lines = ["LLM Health Report\n=================="]
    for provider in llm_mgr.providers:
        is_healthy = await llm_mgr.health_check(provider)
        status = "HEALTHY" if is_healthy else "UNHEALTHY"
        latency = f"{provider.latency_ms:.0f}ms" if provider.latency_ms > 0 else "N/A"
        lines.append(
            f"\n{provider.name}\n"
            f"  Status: {status}\n"
            f"  Model: {provider.model}\n"
            f"  Latency: {latency}"
        )
        if provider.last_error and not is_healthy:
            lines.append(f"  Error: {provider.last_error[:80]}")

    await update.message.reply_text("\n".join(lines))


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config: Config = context.bot_data["config"]
    if not is_authorized(update.effective_user.id, config):
        await update.message.reply_text("Unauthorized.")
        return

    llm_mgr = bot_state.llm_manager
    if not llm_mgr or not llm_mgr.current_provider:
        await update.message.reply_text("No LLM providers configured.")
        return

    current = llm_mgr.current_provider
    fallbacks = [p.name for p in llm_mgr.providers if p.name != current.name]

    model_info = (
        "Active Model\n"
        "============\n"
        f"Source: {current.name}\n"
        f"Model: {current.model}\n"
        f"Endpoint: {current.api_base[:50]}...\n"
        f"Latency: {current.latency_ms:.0f}ms\n"
        f"Health: {'OK' if current.healthy else 'DOWN'}\n"
        f"Fallbacks: {', '.join(fallbacks) if fallbacks else 'None'}"
    )

    await update.message.reply_text(model_info)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    config: Config = context.bot_data["config"]
    if not is_authorized(update.effective_user.id, config):
        await update.message.reply_text("Unauthorized.")
        return

    user_message = update.message.text
    if not user_message:
        return

    bot_state.message_count += 1

    llm_mgr = bot_state.llm_manager
    if not llm_mgr or not llm_mgr.providers:
        await update.message.reply_text(
            "No LLM providers are configured. Check bot environment variables."
        )
        return

    # Show typing indicator
    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing"
        )
    except Exception:
        pass

    # Generate response
    messages = [{"role": "user", "content": user_message}]
    result = await llm_mgr.generate(messages)

    if result["success"]:
        response = result["content"]
        if result["provider"] != "LOCAL":
            response += f"\n\n(via {result['provider']})"
        # Try Markdown first, fall back to plain text
        try:
            await update.message.reply_text(response, parse_mode="Markdown")
        except Exception:
            await update.message.reply_text(response)
    else:
        bot_state.error_count += 1
        await update.message.reply_text(
            "Failed to generate response. All LLM providers unavailable.\n"
            "Use /health to check provider status."
        )


# =============================================================================
# HEALTH CHECK WEB SERVER (for Fly.io / monitoring)
# =============================================================================


async def web_health_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """HTTP health endpoint for Fly.io and monitoring."""
    llm_mgr = bot_state.llm_manager
    current = llm_mgr.current_provider if llm_mgr else None

    data = {
        "status": "ok",
        "uptime": bot_state.uptime,
        "messages": bot_state.message_count,
        "errors": bot_state.error_count,
        "llm_provider": current.name if current else "none",
        "llm_model": current.model if current else "none",
        "llm_healthy": current.healthy if current else False,
    }
    return aiohttp.web.json_response(data)


async def web_root_handler(request: aiohttp.web.Request) -> aiohttp.web.Response:
    return aiohttp.web.Response(
        text="ClawDBot is running. GET /health for status.",
        content_type="text/plain",
    )


# =============================================================================
# MAIN
# =============================================================================


async def run():
    """Main async entry point — runs Telegram bot + health web server."""
    config = Config()
    if not config.validate():
        logger.error("Configuration validation failed. Exiting.")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("ClawDBot starting up")
    logger.info("=" * 50)
    logger.info(f"Allowed Telegram users: {config.TELEGRAM_ALLOWED_IDS}")
    if config.LOCAL_LLM_API_BASE:
        logger.info(f"Local LLM endpoint: {config.LOCAL_LLM_API_BASE}")
        logger.info(f"Local LLM model: {config.LOCAL_LLM_MODEL}")
    if config.OPENAI_API_KEY:
        logger.info("OpenAI fallback: configured")

    # --- Initialize LLM manager ---
    bot_state.llm_manager = LLMManager(config)

    # Initial health check
    if bot_state.llm_manager.providers:
        logger.info("Running initial LLM health check...")
        healthy = await bot_state.llm_manager.health_check()
        if healthy:
            logger.info(
                f"Primary LLM healthy: {bot_state.llm_manager.current_provider.name} "
                f"({bot_state.llm_manager.current_provider.latency_ms:.0f}ms)"
            )
        else:
            logger.warning("Primary LLM unhealthy — will try fallbacks on first message")
            if len(bot_state.llm_manager.providers) > 1:
                bot_state.llm_manager.switch_to_next_provider()

    # --- Build Telegram application ---
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    application.bot_data["config"] = config

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("health", health_command))
    application.add_handler(CommandHandler("model", model_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )

    # --- Start health-check web server ---
    web_app = aiohttp.web.Application()
    web_app.router.add_get("/", web_root_handler)
    web_app.router.add_get("/health", web_health_handler)

    runner = aiohttp.web.AppRunner(web_app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    logger.info(f"Health-check web server listening on port {config.PORT}")

    # --- Start Telegram polling ---
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Telegram bot polling started")
    logger.info("=" * 50)
    logger.info("ClawDBot is READY")
    logger.info("=" * 50)

    # --- Keep running until shutdown signal ---
    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass

    # --- Graceful shutdown ---
    logger.info("Shutting down...")
    await application.updater.stop()
    await application.stop()
    await application.shutdown()
    await runner.cleanup()
    logger.info("ClawDBot stopped.")


def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
