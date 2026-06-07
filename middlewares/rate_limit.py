from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from db import get_db
from services.ban_service import is_banned
from services.captcha_service import (
    captcha_enabled, create_captcha_session, has_passed_captcha,
)
from services.rate_limit_service import check_rate_limit

logger = logging.getLogger(__name__)

_FREE_COMMANDS = {"/start", "/help", "/ping", "/report"}

# Smart captcha: if user sends >= BURST_COUNT messages within BURST_WINDOW seconds,
# revoke their captcha pass and require them to re-solve.
BURST_COUNT  = 2
BURST_WINDOW = 10  # seconds


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

        # Free commands — bypass everything
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

        # Smart captcha: track burst and revoke pass if spamming fast
        if await captcha_enabled():
            triggered = await _check_burst(user.id)
            if triggered:
                # Revoke captcha pass so middleware blocks next message
                await get_db().users.update_one(
                    {"user_id": user.id},
                    {"$unset": {"captcha_passed": ""}},
                )
                await create_captcha_session(user.id)
                logger.info("Smart captcha triggered for user %d", user.id)
                # Let the captcha middleware handle it on next message;
                # still allow this message through to avoid false-positive on first burst
            elif not await has_passed_captcha(user.id):
                # captcha_enabled but user hasn't passed — captcha middleware handles it
                pass

        return await handler(event, data)


async def _check_burst(user_id: int) -> bool:
    """
    Track recent message timestamps. Return True if the user sent
    BURST_COUNT or more messages within BURST_WINDOW seconds.
    Stores a rolling window of timestamps in a 'burst_track' collection.
    """
    db = get_db()
    now = datetime.utcnow()

    doc = await db.burst_track.find_one({"user_id": user_id})
    if doc is None:
        await db.burst_track.insert_one({"user_id": user_id, "timestamps": [now]})
        return False

    # Keep only timestamps within the window
    window_start = now.timestamp() - BURST_WINDOW
    recent = [t for t in doc["timestamps"] if t.timestamp() > window_start]
    recent.append(now)

    await db.burst_track.update_one(
        {"user_id": user_id},
        {"$set": {"timestamps": recent[-20:]}},  # cap at 20 entries
    )

    return len(recent) >= BURST_COUNT
