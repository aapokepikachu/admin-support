from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from services.ban_service import is_banned
from services.rate_limit_service import check_rate_limit

logger = logging.getLogger(__name__)

# These commands are never rate-limited or ban-blocked
_FREE_COMMANDS = {"/start", "/help", "/ping", "/report"}


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

        # Always allow free commands through — no ban check, no rate limit
        if event.text and any(event.text.startswith(cmd) for cmd in _FREE_COMMANDS):
            return await handler(event, data)

        if await is_banned(user.id):
            await event.answer("🚫 You are banned from using this bot.")
            return

        allowed, retry_after = await check_rate_limit(user.id)
        if not allowed:
            mins, secs = divmod(retry_after, 60)
            time_str = f"{mins}m {secs}s" if mins else f"{secs}s"
            await event.answer(
                f"⏳ <b>Slow down!</b> You are sending messages too fast.\n"
                f"Please wait <b>{time_str}</b> before sending the next message."
            )
            return

        return await handler(event, data)
