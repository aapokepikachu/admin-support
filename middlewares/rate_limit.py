from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from db import get_db
from services.ban_service import is_banned
from services.captcha_service import captcha_enabled, create_captcha_session, has_passed_captcha
from services.rate_limit_service import check_rate_limit

logger = logging.getLogger(__name__)

_FREE_COMMANDS = {"/start", "/help", "/ping", "/report"}

# Smart captcha thresholds:
# Trigger if user sends >= BURST_TRIGGER messages within BURST_WINDOW seconds.
# Normal users occasionally send 2-3 messages quickly (typo corrections, etc.)
# so we set the bar at 5 rapid messages — clear spam signal.
BURST_TRIGGER = 5   # messages within the window to trigger captcha
BURST_WINDOW  = 10  # seconds


class RateLimitMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.chat.type != "private":
            return await handler(event, data)

        user = event.from_user
        if user is None:
            return

        # Free commands bypass all checks
        if event.text and any(event.text.startswith(cmd) for cmd in _FREE_COMMANDS):
            return await handler(event, data)

        if await is_banned(user.id):
            await event.answer("🚫 You are banned from using this bot.")
            return

        # Rate limit check
        allowed, retry_after = await check_rate_limit(user.id)
        if not allowed:
            mins, secs = divmod(retry_after, 60)
            time_str = f"{mins}m {secs}s" if mins else f"{secs}s"
            await event.answer(
                f"⏳ <b>Slow down!</b> You are sending messages too fast.\n"
                f"Please wait <b>{time_str}</b> before sending the next message."
            )
            return

        # Smart captcha burst detection — only when captcha feature is enabled
        if await captcha_enabled():
            burst_hit = await _record_and_check_burst(user.id)
            if burst_hit and await has_passed_captcha(user.id):
                # Revoke pass and create a fresh captcha session
                await get_db().users.update_one(
                    {"user_id": user.id},
                    {"$unset": {"captcha_passed": ""}},
                )
                await create_captcha_session(user.id)
                # Clear burst so solving captcha starts fresh
                await _reset_burst(user.id)
                logger.info("Smart captcha triggered for user %d", user.id)
                # Block this message — captcha middleware will show the prompt
                # on the NEXT message; here we just drop it silently so the
                # burst message itself doesn't go through either
                await event.answer(
                    "🔐 You are sending messages too fast.\n"
                    "Please solve the captcha to continue."
                )
                return

        return await handler(event, data)


async def _record_and_check_burst(user_id: int) -> bool:
    """
    Record this message timestamp and return True if the user has sent
    >= BURST_TRIGGER messages within BURST_WINDOW seconds.
    """
    db = get_db()
    now = datetime.utcnow()
    window_cutoff = now.timestamp() - BURST_WINDOW

    doc = await db.burst_track.find_one({"user_id": user_id})
    if doc is None:
        await db.burst_track.insert_one({"user_id": user_id, "timestamps": [now]})
        return False

    # Keep only timestamps within the current window, then add now
    recent = [t for t in doc["timestamps"] if t.timestamp() > window_cutoff]
    recent.append(now)

    await db.burst_track.update_one(
        {"user_id": user_id},
        {"$set": {"timestamps": recent[-50:]}},
    )
    return len(recent) >= BURST_TRIGGER


async def _reset_burst(user_id: int) -> None:
    """Clear burst history so captcha-solving starts a clean window."""
    await get_db().burst_track.update_one(
        {"user_id": user_id},
        {"$set": {"timestamps": []}},
    )
