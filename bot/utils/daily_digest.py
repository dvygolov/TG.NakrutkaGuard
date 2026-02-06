import asyncio
import html
import logging
import time
from datetime import datetime
from typing import List

from aiogram import Bot

from bot.config import ADMIN_IDS
from bot.database import db

logger = logging.getLogger(__name__)


def _format_chat_ref(item: dict) -> str:
    username = item.get("username")
    if username:
        return html.escape(f"@{username}")
    title = item.get("title")
    if title:
        return html.escape(title)
    return html.escape(str(item.get("chat_id")))


def _build_digest_chunks(events: List[dict], since_ts: int) -> List[str]:
    if not events:
        return []

    period_start = datetime.fromtimestamp(since_ts).strftime("%d.%m %H:%M")
    header = (
        "Ежедневный дайджест по чатам\n"
        f"Период: с {period_start} (последние 24 часа)\n"
        f"Чатов с событиями: {len(events)}\n"
    )

    chunks: List[str] = []
    current = header
    max_len = 3500

    for item in events:
        lines = [f"\n<b>{_format_chat_ref(item)}</b>"]
        if item.get("attacks_started", 0):
            lines.append(f"• Атак начато: {item['attacks_started']}")
        if item.get("attacks_ended", 0):
            lines.append(f"• Атак завершено: {item['attacks_ended']}")
        if item.get("attack_kicks", 0):
            lines.append(f"• Киков в атаке: {item['attack_kicks']}")
        if item.get("scoring_kicks", 0):
            lines.append(f"• Киков скорингом: {item['scoring_kicks']}")
        if item.get("captcha_failed", 0):
            lines.append(f"• Провалов капчи: {item['captcha_failed']}")
        if item.get("verified", 0):
            lines.append(f"• Успешных верификаций: {item['verified']}")
        if item.get("auto_adjustments", 0):
            lines.append(f"• Автокорректировок: {item['auto_adjustments']}")

        block = "\n".join(lines)
        if len(current) + len(block) + 1 > max_len:
            chunks.append(current)
            current = header + block
        else:
            current += block

    if current:
        chunks.append(current)

    return chunks


async def send_daily_digest(bot: Bot) -> bool:
    """Сформировать и отправить дайджест по всем чатам за последние 24 часа."""
    since_ts = int(time.time()) - 24 * 60 * 60
    events = await db.get_daily_digest_events(since_ts)
    if not events:
        return False

    chunks = _build_digest_chunks(events, since_ts)
    if not chunks:
        return False

    for admin_id in ADMIN_IDS:
        for chunk in chunks:
            try:
                await bot.send_message(admin_id, chunk, parse_mode="HTML")
            except Exception as exc:
                logger.warning("Не удалось отправить дайджест admin_id=%s: %s", admin_id, exc)
                break

    return True


async def daily_digest_loop(bot: Bot):
    """Фоновый цикл: отправляет дайджест раз в сутки в указанное время."""
    last_sent_date = None
    while True:
        try:
            settings = await db.get_daily_digest_settings()
            if not settings.get("enabled", False):
                await asyncio.sleep(20)
                continue

            now = datetime.now()
            hour = settings.get("hour", 9)
            minute = settings.get("minute", 0)

            if now.hour == hour and now.minute == minute and last_sent_date != now.date():
                sent = await send_daily_digest(bot)
                last_sent_date = now.date()
                logger.info(
                    "Daily digest run at %02d:%02d, sent=%s",
                    hour,
                    minute,
                    sent,
                )
                await asyncio.sleep(61)
                continue
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Ошибка в цикле daily digest: %s", exc, exc_info=True)

        await asyncio.sleep(20)
