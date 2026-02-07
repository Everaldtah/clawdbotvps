#!/usr/bin/env python3
"""
ClawDBot - AI-Powered Telegram Bot with Remote LLM Support
===========================================================
VPS: Orchestration-only (≤512MB RAM, ≤1 CPU)
LLM: Remote (User's local machine via secure tunnel)
"""

import os
import sys
import json
import time
import logging
import asyncio
import aiohttp
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

@dataclass
class Config:
    """Bot configuration from environment variables"""
    # Telegram
    TELEGRAM_BOT_TOKEN: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    TELEGRAM_ALLOWED_IDS: List[str] = field(default_factory=lambda: os.getenv("TELEGRAM_ALLOWED_IDS", "").split(","))
    
    # Local LLM (Remote - User's machine)
    LOCAL_LLM_API_BASE: str = field(default_factory=lambda: os.getenv("LOCAL_LLM_API_BASE", ""))
    LOCAL_LLM_MODEL: str = field(default_factory=lambda: os.getenv("LOCAL_LLM_MODEL", ""))
    LOCAL_LLM_TIMEOUT: int = field(default_factory=lambda: int(os.getenv("LOCAL_LLM_TIMEOUT", "60")))
    
    # Fallback APIs
    OPENAI_API_KEY: Optional[str] = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    ANTHROPIC_API_KEY: Optional[str] = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY"))
    
    def validate(self) -> bool:
        """Validate required configuration"""
        if not self.TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN not set")
            return False
        if not self.TELEGRAM_ALLOWED_IDS or self.TELEGRAM_ALLOWED_IDS == ['']:
            logger.error("TELEGRAM_ALLOWED_IDS not set")
            return False
        if not self.LOCAL_LLM_API_BASE:
            logger.error("LOCAL_LLM_API_BASE not set")
            return False
        return True

# =============================================================================
# LLM PROVIDER MANAGEMENT
# =============================================================================

@dataclass
class LLMProvider:
    """LLM provider configuration"""
    name: str
    api_base: str
    model: str
    api_key: Optional[str] = None
    timeout: int = 60
    healthy: bool = True
    last_error: Optional[str] = None
    latency_ms: float = 0.0

class LLMManager:
    """Manages LLM providers with automatic fallback"""
    
    def __init__(self, config: Config):
        self.config = config
        self.providers: List[LLMProvider] = []
        self.current_provider_index = 0
        self._setup_providers()
    
    def _setup_providers(self):
        """Initialize provider priority list"""
        # Priority 1: Local LLM (User's machine)
        self.providers.append(LLMProvider(
            name="LOCAL",
            api_base=self.config.LOCAL_LLM_API_BASE,
            model=self.config.LOCAL_LLM_MODEL,
            timeout=self.config.LOCAL_LLM_TIMEOUT
        ))
        
        # Priority 2: OpenAI
        if self.config.OPENAI_API_KEY:
            self.providers.append(LLMProvider(
                name="OPENAI",
                api_base="https://api.openai.com/v1",
                model="gpt-4o-mini",
                api_key=self.config.OPENAI_API_KEY,
                timeout=30
            ))
        
        logger.info(f"Initialized {len(self.providers)} LLM providers")
    
    @property
    def current_provider(self) -> LLMProvider:
        """Get current active provider"""
        return self.providers[self.current_provider_index]
    
    def switch_to_next_provider(self):
        """Switch to next available provider"""
        old_provider = self.current_provider.name
        self.current_provider_index = (self.current_provider_index + 1) % len(self.providers)
        new_provider = self.current_provider.name
        logger.warning(f"Switched LLM provider: {old_provider} -> {new_provider}")
        return old_provider, new_provider
    
    async def health_check(self, provider: Optional[LLMProvider] = None) -> bool:
        """Check if a provider is healthy"""
        prov = provider or self.current_provider
        
        try:
            start = time.time()
            async with aiohttp.ClientSession() as session:
                # Test with minimal prompt
                payload = {
                    "model": prov.model,
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "max_tokens": 10,
                    "temperature": 0.1
                }
                
                headers = {"Content-Type": "application/json"}
                if prov.api_key:
                    headers["Authorization"] = f"Bearer {prov.api_key}"
                
                async with session.post(
                    f"{prov.api_base}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=prov.timeout)
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
    
    async def generate(self, messages: List[Dict[str, str]], max_tokens: int = 1024) -> Dict[str, Any]:
        """Generate response with automatic fallback"""
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
                        "temperature": 0.7
                    }
                    
                    headers = {"Content-Type": "application/json"}
                    if provider.api_key:
                        headers["Authorization"] = f"Bearer {provider.api_key}"
                    
                    async with session.post(
                        f"{provider.api_base}/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=provider.timeout)
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
                                "latency_ms": provider.latency_ms
                            }
                        else:
                            raise Exception(f"HTTP {resp.status}")
                            
            except Exception as e:
                provider.healthy = False
                provider.last_error = str(e)
                logger.warning(f"Generation failed with {provider.name}: {e}")
                
                # Try next provider
                if attempts < max_attempts - 1:
                    old, new = self.switch_to_next_provider()
                    logger.info(f"Falling back: {old} -> {new}")
                
                attempts += 1
        
        return {
            "success": False,
            "error": "All providers failed",
            "provider": "NONE"
        }

# =============================================================================
# BOT STATE
# =============================================================================

class BotState:
    """Bot runtime state"""
    def __init__(self):
        self.start_time = datetime.now()
        self.message_count = 0
        self.error_count = 0
        self.llm_manager: Optional[LLMManager] = None
    
    @property
    def uptime(self) -> str:
        """Get formatted uptime"""
        delta = datetime.now() - self.start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"

# Global state
bot_state = BotState()

# =============================================================================
# TELEGRAM COMMAND HANDLERS
# =============================================================================

def is_authorized(user_id: int, config: Config) -> bool:
    """Check if user is authorized"""
    return str(user_id) in config.TELEGRAM_ALLOWED_IDS

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_user.id, config):
        await update.message.reply_text("⛔ Unauthorized access.")
        return
    
    await update.message.reply_text(
        "🤖 *ClawDBot* - AI Assistant\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Send me any message and I'll respond using AI.\n\n"
        "📋 *Commands:*\n"
        "/status - Bot status\n"
        "/health - LLM health check\n"
        "/model - Active model info\n"
        "/restart - Restart bot\n"
        "/shutdown - Shutdown bot",
        parse_mode="Markdown"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_user.id, config):
        await update.message.reply_text("⛔ Unauthorized access.")
        return
    
    llm_mgr = bot_state.llm_manager
    current = llm_mgr.current_provider if llm_mgr else None
    
    status_text = (
        "📊 *Bot Status*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 State: Running\n"
        f"⏱️ Uptime: {bot_state.uptime}\n"
        f"💬 Messages: {bot_state.message_count}\n"
        f"⚠️ Errors: {bot_state.error_count}\n"
        f"🧠 Active LLM: {current.name if current else 'N/A'}\n"
        f"📦 Model: `{current.model if current else 'N/A'}`"
    )
    
    await update.message.reply_text(status_text, parse_mode="Markdown")

async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /health command"""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_user.id, config):
        await update.message.reply_text("⛔ Unauthorized access.")
        return
    
    llm_mgr = bot_state.llm_manager
    if not llm_mgr:
        await update.message.reply_text("❌ LLM Manager not initialized")
        return
    
    # Check all providers
    await update.message.reply_text("🔍 Running health checks...")
    
    health_report = ["🩺 *LLM Health Report*\n━━━━━━━━━━━━━━━━━━━━━"]
    
    for provider in llm_mgr.providers:
        is_healthy = await llm_mgr.health_check(provider)
        status = "🟢 Healthy" if is_healthy else "🔴 Unhealthy"
        latency = f"{provider.latency_ms:.0f}ms" if provider.latency_ms > 0 else "N/A"
        
        health_report.append(
            f"\n*{provider.name}*\n"
            f"Status: {status}\n"
            f"Model: `{provider.model}`\n"
            f"Latency: {latency}"
        )
        if provider.last_error and not is_healthy:
            health_report.append(f"Error: `{provider.last_error[:50]}...`")
    
    await update.message.reply_text("\n".join(health_report), parse_mode="Markdown")

async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /model command"""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_user.id, config):
        await update.message.reply_text("⛔ Unauthorized access.")
        return
    
    llm_mgr = bot_state.llm_manager
    if not llm_mgr:
        await update.message.reply_text("❌ LLM Manager not initialized")
        return
    
    current = llm_mgr.current_provider
    tunnel_type = "Cloudflare" if "trycloudflare" in config.LOCAL_LLM_API_BASE else "Unknown"
    
    model_info = (
        "🧠 *Active Model Information*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Source:* {current.name}\n"
        f"*Model:* `{current.model}`\n"
        f"*Endpoint:* `{current.api_base[:40]}...`\n"
        f"*Latency:* {current.latency_ms:.0f}ms\n"
        f"*Health:* {'🟢' if current.healthy else '🔴'}\n"
    )
    
    if current.name == "LOCAL":
        model_info += (
            f"\n*Tunnel:* {tunnel_type}\n"
            f"*Hardware:* User Local Machine (≥32GB RAM)\n"
        )
    
    # List fallbacks
    fallbacks = [p.name for p in llm_mgr.providers if p.name != current.name]
    model_info += f"\n*Fallbacks:* {', '.join(fallbacks) if fallbacks else 'None'}"
    
    await update.message.reply_text(model_info, parse_mode="Markdown")

async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /restart command"""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_user.id, config):
        await update.message.reply_text("⛔ Unauthorized access.")
        return
    
    await update.message.reply_text("🔄 Restarting ClawDBot...")
    logger.info("Restart requested via Telegram")
    
    # Graceful shutdown and restart
    asyncio.get_event_loop().call_later(2, lambda: os._exit(0))

async def shutdown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /shutdown command"""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_user.id, config):
        await update.message.reply_text("⛔ Unauthorized access.")
        return
    
    await update.message.reply_text("🛑 Shutting down ClawDBot...")
    logger.info("Shutdown requested via Telegram")
    
    # Graceful shutdown
    asyncio.get_event_loop().call_later(2, lambda: sys.exit(0))

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages"""
    config = context.bot_data.get("config")
    if not is_authorized(update.effective_user.id, config):
        await update.message.reply_text("⛔ Unauthorized access.")
        return
    
    user_message = update.message.text
    bot_state.message_count += 1
    
    llm_mgr = bot_state.llm_manager
    if not llm_mgr:
        await update.message.reply_text("❌ LLM Manager not initialized")
        return
    
    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action="typing"
    )
    
    # Generate response
    messages = [{"role": "user", "content": user_message}]
    result = await llm_mgr.generate(messages)
    
    if result["success"]:
        response = result["content"]
        # Add provider indicator for transparency
        if result["provider"] != "LOCAL":
            response += f"\n\n_(via {result['provider']})_"
        await update.message.reply_text(response, parse_mode="Markdown")
    else:
        bot_state.error_count += 1
        await update.message.reply_text(
            "❌ Failed to generate response. All LLM providers unavailable.\n"
            "Check /health for details."
        )

# =============================================================================
# MAIN
# =============================================================================

async def post_init(application: Application):
    """Post-initialization setup"""
    config = application.bot_data["config"]
    
    # Initialize LLM Manager
    bot_state.llm_manager = LLMManager(config)
    
    # Initial health check
    logger.info("Running initial LLM health check...")
    healthy = await bot_state.llm_manager.health_check()
    
    if healthy:
        logger.info(f"✅ Local LLM healthy: {bot_state.llm_manager.current_provider.model}")
    else:
        logger.warning("⚠️ Local LLM unhealthy, will use fallbacks")
        bot_state.llm_manager.switch_to_next_provider()
    
    logger.info("ClawDBot initialized and ready")

def main():
    """Main entry point"""
    # Load configuration
    config = Config()
    if not config.validate():
        logger.error("Configuration validation failed")
        sys.exit(1)
    
    logger.info("Starting ClawDBot...")
    logger.info(f"Allowed users: {config.TELEGRAM_ALLOWED_IDS}")
    logger.info(f"Local LLM: {config.LOCAL_LLM_MODEL}")
    
    # Build application
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    application.bot_data["config"] = config
    
    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("health", health_command))
    application.add_handler(CommandHandler("model", model_command))
    application.add_handler(CommandHandler("restart", restart_command))
    application.add_handler(CommandHandler("shutdown", shutdown_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    
    # Run with post-init
    application.post_init = post_init
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
