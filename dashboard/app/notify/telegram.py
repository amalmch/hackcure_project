"""Envoi Telegram (httpx). Désactivé sans TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID."""

from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger("hackcure.telegram")


async def send_telegram(text: str) -> bool:
    from .. import privacy

    text = privacy.outbound("telegram", text)  # V3 : jamais de nom de patient hors de la plateforme
    if not settings.telegram_enabled:
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.post(url, json={"chat_id": settings.telegram_chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
            if r.status_code >= 400:
                logger.warning("Telegram %s: %s", r.status_code, r.text[:200])
                return False
        return True
    except Exception as exc:
        logger.warning("Telegram injoignable: %s", exc.__class__.__name__)
        return False
