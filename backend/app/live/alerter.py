"""Telegram alerter for critical trading events."""
from __future__ import annotations

import asyncio

import httpx
import structlog

log = structlog.get_logger(__name__)

_TELEGRAM_API = "https://api.telegram.org"


class TelegramAlerter:
    """Send Telegram messages. Falls back to log-only if not configured."""

    def __init__(self, bot_token: str | None, chat_id: str | None) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)

    async def send(self, message: str, *, parse_mode: str = "HTML") -> None:
        log.info("alert", message=message[:200])
        if not self._enabled:
            return
        url = f"{_TELEGRAM_API}/bot{self._token}/sendMessage"
        payload = {"chat_id": self._chat_id, "text": message, "parse_mode": parse_mode}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
        except Exception as exc:
            log.error("telegram_send_error", error=str(exc))

    async def critical(self, message: str) -> None:
        await self.send(f"🚨 <b>CRITICAL</b>\n{message}")

    async def warning(self, message: str) -> None:
        await self.send(f"⚠️ <b>WARNING</b>\n{message}")

    async def info(self, message: str) -> None:
        await self.send(f"ℹ️ {message}")
