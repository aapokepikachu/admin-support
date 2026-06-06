from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import ChatMemberUpdatedFilter, IS_NOT_MEMBER, IS_MEMBER
from aiogram.types import ChatMemberUpdated, Message

from config import settings

logger = logging.getLogger(__name__)
router = Router()


@router.my_chat_member()
async def on_bot_added(event: ChatMemberUpdated) -> None:
    """Leave any group that is not the configured admin group."""
    chat = event.chat
    if chat.type in ("group", "supergroup") and chat.id != settings.ADMIN_GROUP_ID:
        if event.new_chat_member.status in ("member", "administrator"):
            logger.warning("Added to foreign group %s (%d) — leaving.", chat.title, chat.id)
            try:
                await event.bot.leave_chat(chat.id)
            except Exception as exc:
                logger.error("Could not leave group %d: %s", chat.id, exc)
