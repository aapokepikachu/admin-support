from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject

from services.captcha_service import (
    captcha_enabled,
    create_captcha_session,
    get_pending_captcha,
    has_passed_captcha,
)

logger = logging.getLogger(__name__)

# Commands that bypass captcha entirely
_BYPASS_COMMANDS = {"/start", "/help", "/ping"}


class CaptchaMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or event.chat.type != "private":
            return await handler(event, data)

        if event.text and any(event.text.startswith(cmd) for cmd in _BYPASS_COMMANDS):
            return await handler(event, data)

        user = event.from_user
        if user is None:
            return

        if not await captcha_enabled():
            return await handler(event, data)

        if await has_passed_captcha(user.id):
            return await handler(event, data)

        session = await get_pending_captcha(user.id)
        if session is None:
            session = await create_captcha_session(user.id)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=opt, callback_data=f"captcha:{opt}")]
                for opt in session["options"]
            ]
        )
        await event.answer(
            f"🔐 <b>Captcha required</b>\n\n{session['question']}\n\n"
            "Select the correct answer to continue:",
            reply_markup=kb,
        )
        # Block the message — do NOT call handler
