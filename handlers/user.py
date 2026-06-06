from __future__ import annotations

import logging
import time

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import settings
from services.ban_service import is_banned
from services.channel_service import is_allowed_channel, list_channels
from services.message_map_service import save_mapping
from services.report_service import get_template_by_slug
from services.user_service import upsert_user
from utils.tg_helpers import extract_channel_id_from_link, user_mention

logger = logging.getLogger(__name__)
router = Router()

# Only handle private chats in this router
router.message.filter(F.chat.type == "private")


@router.message(CommandStart())
async def cmd_start(msg: Message) -> None:
    user = msg.from_user
    await upsert_user(user)

    # Handle deep-link for report: /start report_<slug>
    args = msg.text.split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("report_"):
        slug = args[1][len("report_"):]
        await _handle_report_deeplink(msg, slug)
        return

    await msg.answer(
        f"👋 <b>Welcome, {user.first_name}!</b>\n\n"
        "This bot connects you with our support team.\n\n"
        "📨 <b>How it works:</b>\n"
        "Simply send any message here and it will be forwarded to our admins. "
        "Wait patiently for a reply — they will respond as soon as possible.\n\n"
        "⚠️ <b>Anti-spam rules:</b>\n"
        f"• Max <b>{settings.RATE_LIMIT_MESSAGES} messages</b> per "
        f"{settings.RATE_LIMIT_WINDOW}s\n"
        f"• Exceeding this triggers a <b>{settings.RATE_LIMIT_COOLDOWN // 60}-minute cooldown</b>\n"
        "• Abuse will result in a <b>permanent ban</b>\n\n"
        "🔐 A <b>captcha</b> may be required before your first message.\n\n"
        "Use /help to see available commands."
    )


@router.message(Command("help"))
async def cmd_help(msg: Message) -> None:
    await msg.answer(
        "📖 <b>User Commands</b>\n\n"
        "/start — Welcome message & bot info\n"
        "/help — This help message\n"
        "/report — Report a broken link\n"
        "/ping — Check bot latency"
    )


@router.message(Command("ping"))
async def cmd_ping(msg: Message) -> None:
    sent_time = time.monotonic()
    reply = await msg.answer("🏓 Pong!")
    latency_ms = int((time.monotonic() - sent_time) * 1000)
    await reply.edit_text(f"🏓 <b>Pong!</b>  <code>{latency_ms} ms</code>")


@router.message(Command("report"))
async def cmd_report(msg: Message) -> None:
    await msg.answer(
        "🔗 <b>Report a broken link</b>\n\n"
        "Please send the link you want to report.\n"
        "Only links from authorised channels/groups are accepted."
    )
    # Further flow is handled by the next message handler below
    # We store a temporary state in-memory isn't needed; the report deeplink flow
    # handles everything. This command just gives instructions.
    channels = await list_channels()
    if channels:
        ch_lines = "\n".join(f"• {c['title']} (<code>{c['channel_id']}</code>)" for c in channels)
        await msg.answer(f"✅ <b>Authorised channels:</b>\n{ch_lines}")
    else:
        await msg.answer("ℹ️ No authorised channels configured yet. Ask an admin to use /setchannel.")


# ── Message forwarding ────────────────────────────────────────────────────────

@router.message(F.text | F.photo | F.video | F.document | F.audio | F.voice | F.sticker)
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
        await msg.answer("✅ Your message has been forwarded to the support team. Please wait for a reply.")
    except Exception as exc:
        logger.error("Failed to forward message from %d: %s", user.id, exc)
        await msg.answer("❌ Failed to forward your message. Please try again later.")


# ── Report deep-link ──────────────────────────────────────────────────────────

async def _handle_report_deeplink(msg: Message, slug: str) -> None:
    template = await get_template_by_slug(slug)
    if not template:
        await msg.answer("❌ This report link is invalid or has been deleted.")
        return

    from services.report_service import get_report_state

    tid = str(template["_id"])
    state = await get_report_state(msg.from_user.id, tid)
    if state and state["status"] == "pending":
        await msg.answer(
            "⏳ You already have a pending report for this item. "
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
