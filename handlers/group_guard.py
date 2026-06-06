from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import ChatMemberUpdated

from config import settings

logger = logging.getLogger(__name__)
router = Router()


@router.my_chat_member()
async def on_bot_added(event: ChatMemberUpdated) -> None:
    """Leave immediately if added to any group that is not the admin group."""
    chat = event.chat
    if chat.type not in ("group", "supergroup"):
        return
    if chat.id == settings.ADMIN_GROUP_ID:
        return
    if event.new_chat_member.status in ("member", "administrator"):
        logger.warning("Added to foreign group %s (%d) — leaving.", chat.title, chat.id)
        try:
            await event.bot.leave_chat(chat.id)
        except Exception as exc:
            logger.error("Could not leave group %d: %s", chat.id, exc)
