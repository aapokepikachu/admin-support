from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from config import settings
from services.message_map_service import save_mapping
from services.report_service import get_report_state, get_template_by_slug
from services.user_service import upsert_user
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)
router = Router()

router.message.filter(F.chat.type == "private")


@router.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    user = msg.from_user
    await upsert_user(user)

    args = msg.text.split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("report_"):
        slug = args[1][len("report_"):]
        await _handle_report_deeplink(msg, slug)
        return

    await msg.answer(
        f"👋 <b>Welcome, {user.first_name}!</b>\n\n"
        "This bot connects you with the support team.\n\n"
        "📨 <b>How it works</b>\n"
        "Send any message here and it will be forwarded directly to admins. "
        "Wait for a reply — they will respond as soon as possible.\n\n"
        "⚠️ <b>Anti-spam rules</b>\n"
        f"• Max <b>{settings.RATE_LIMIT_MESSAGES} messages</b> per {settings.RATE_LIMIT_WINDOW}s\n"
        f"• Exceeding this triggers a <b>{settings.RATE_LIMIT_COOLDOWN // 60}-minute cooldown</b>\n"
        "• Abuse results in a <b>permanent ban</b>\n\n"
        "🔐 A <b>captcha</b> may be required before your first message.\n\n"
        "Use /help to see available commands."
    )


@router.message(Command("help"))
async def cmd_help(msg: Message) -> None:
    await msg.answer(
        "📖 <b>Commands</b>\n\n"
        "/start — Welcome message\n"
        "/help — This help message\n"
        "/report — Report a broken link from an authorised channel\n"
        "/ping — Check bot latency"
    )


@router.message(Command("ping"))
async def cmd_ping(msg: Message) -> None:
    t = time.monotonic()
    reply = await msg.answer("🏓 Pong!")
    ms = int((time.monotonic() - t) * 1000)
    await reply.edit_text(f"🏓 <b>Pong!</b>  <code>{ms} ms</code>")


# ── Block forwarded messages ──────────────────────────────────────────────────

@router.message(F.forward_origin | F.forward_from | F.forward_from_chat)
async def block_forwards(msg: Message) -> None:
    await msg.answer(
        "⚠️ Forwarded messages are not accepted.\n"
        "Please type your message directly."
    )


# ── Message forwarding ────────────────────────────────────────────────────────

@router.message(F.text | F.photo | F.video | F.document | F.audio | F.voice | F.sticker | F.animation)
async def forward_to_admin(msg: Message) -> None:
    user = msg.from_user
    await upsert_user(user)

    try:
        forwarded = await msg.forward(chat_id=settings.ADMIN_GROUP_ID)
        await save_mapping(
            user_id=user.id,
            user_msg_id=msg.message_id,
            admin_msg_id=forwarded.message_id,
        )
        await msg.answer(
            "✅ Your message has been forwarded to the support team.\n"
            "Please wait for a reply."
        )
    except Exception as exc:
        logger.error("Failed to forward from user %d: %s", user.id, exc)
        await msg.answer("❌ Could not forward your message. Please try again later.")


# ── Report deep-link handler ──────────────────────────────────────────────────

async def _handle_report_deeplink(msg: Message, slug: str) -> None:
    template = await get_template_by_slug(slug)
    if not template:
        await msg.answer("❌ This report link is invalid or has been deleted.")
        return

    tid = str(template["_id"])
    state = await get_report_state(msg.from_user.id, tid)
    if state and state["status"] == "pending":
        await msg.answer(
            "⏳ You already have a pending report for this item.\n"
            "Please wait for an admin to resolve it."
        )
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Proceed", callback_data=f"rpt_proceed:{tid}"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="rpt_cancel"),
            ]
        ]
    )
    await msg.answer(
        f"📋 <b>Report</b>\n\n{template['prompt_msg']}",
        reply_markup=kb,
    )
