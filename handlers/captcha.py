from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery

from services.captcha_service import (
    get_pending_captcha,
    mark_captcha_passed,
    resolve_captcha,
)
from services.user_service import upsert_user

router = Router()


@router.callback_query(lambda c: c.data and c.data.startswith("captcha:"))
async def captcha_answer(callback: CallbackQuery) -> None:
    user = callback.from_user
    answer = callback.data.split(":", 1)[1]

    session = await get_pending_captcha(user.id)
    if session is None:
        await callback.answer("Session expired. Please send a message again.", show_alert=True)
        return

    if answer == session["answer"]:
        await resolve_captcha(user.id)
        await mark_captcha_passed(user.id)
        await upsert_user(user)
        await callback.message.edit_text("✅ <b>Captcha passed!</b> You can now send messages.")
        await callback.answer("Verified!")
    else:
        await callback.answer("❌ Wrong answer. Try again.", show_alert=True)
