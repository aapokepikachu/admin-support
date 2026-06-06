from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import settings
from db import get_db
from services.ban_service import ban_list, ban_user, is_banned, unban_user
from services.captcha_service import captcha_enabled, set_captcha
from services.channel_service import add_channel, list_channels, remove_channel
from services.message_map_service import get_mapping_by_admin_msg
from services.user_service import all_active_user_ids, all_users, get_user, mark_deleted
from utils.tg_helpers import extract_channel_id_from_link, user_mention

logger = logging.getLogger(__name__)
router = Router()

# Only handle messages from the admin group
router.message.filter(F.chat.id == settings.ADMIN_GROUP_ID)


# ── Reply routing: admin → user ───────────────────────────────────────────────

@router.message(F.reply_to_message)
async def admin_reply_to_user(msg: Message, bot: Bot) -> None:
    # Ignore commands — they are handled by dedicated handlers below
    if msg.text and msg.text.startswith("/"):
        return

    reply_target = msg.reply_to_message
    if reply_target is None:
        return

    mapping = await get_mapping_by_admin_msg(reply_target.message_id)
    if mapping is None:
        # The replied-to message wasn't a forwarded user message
        return

    user_id: int = mapping["user_id"]
    try:
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=msg.chat.id,
            message_id=msg.message_id,
        )
        await msg.react([])  # no reaction needed; just silently route
    except Exception as exc:
        err = str(exc)
        if "bot was blocked" in err or "user is deactivated" in err:
            await mark_deleted(user_id)
            await msg.reply(f"⚠️ Could not deliver reply: user {user_id} has blocked the bot or deactivated their account.")
        else:
            logger.error("Failed to route reply to user %d: %s", user_id, exc)
            await msg.reply(f"❌ Delivery failed: {exc}")


# ── /helpa ────────────────────────────────────────────────────────────────────

@router.message(Command("helpa"))
async def cmd_helpa(msg: Message) -> None:
    await msg.answer(
        "🛠 <b>Admin Commands</b>\n\n"
        "<b>User management</b>\n"
        "/ban — Reply to a user message to ban them\n"
        "/unban <code>&lt;id_or_username&gt;</code> — Unban a user\n"
        "/banlist — List all banned users\n"
        "/users — List all users\n\n"
        "<b>Broadcast</b>\n"
        "/broadcast — Reply to a message to broadcast it\n\n"
        "<b>Channels</b>\n"
        "/setchannel — Manage allowed channels for /report\n\n"
        "<b>Reports</b>\n"
        "/reportgen — Create, edit, or delete report links\n\n"
        "<b>Captcha</b>\n"
        "/captcha on | off — Toggle captcha for new users\n\n"
        "<b>System</b>\n"
        "/db — Database health info\n"
        "/helpa — This message"
    )


# ── /ban ──────────────────────────────────────────────────────────────────────

@router.message(Command("ban"))
async def cmd_ban(msg: Message) -> None:
    target_id = await _resolve_target_user_id(msg)
    if target_id is None:
        await msg.reply("⚠️ Reply to a forwarded user message to ban them.")
        return
    if await is_banned(target_id):
        await msg.reply(f"ℹ️ User <code>{target_id}</code> is already banned.")
        return
    await ban_user(target_id, msg.from_user.id)
    await msg.reply(f"🚫 User <code>{target_id}</code> has been banned.")


# ── /unban ────────────────────────────────────────────────────────────────────

@router.message(Command("unban"))
async def cmd_unban(msg: Message) -> None:
    parts = msg.text.split(maxsplit=1)
    target_id: int | None = None

    if len(parts) > 1:
        arg = parts[1].lstrip("@")
        if arg.isdigit():
            target_id = int(arg)
        else:
            # Lookup by username
            doc = await get_db().users.find_one({"username": arg})
            if doc:
                target_id = doc["user_id"]

    if target_id is None:
        # Try reply target
        target_id = await _resolve_target_user_id(msg)

    if target_id is None:
        await msg.reply("⚠️ Provide a user ID/username or reply to their message.")
        return

    if await unban_user(target_id):
        await msg.reply(f"✅ User <code>{target_id}</code> has been unbanned.")
    else:
        await msg.reply(f"ℹ️ User <code>{target_id}</code> was not banned.")


# ── /banlist ──────────────────────────────────────────────────────────────────

@router.message(Command("banlist"))
async def cmd_banlist(msg: Message) -> None:
    bans = await ban_list()
    if not bans:
        await msg.reply("✅ No banned users.")
        return
    lines = [f"• <code>{b['user_id']}</code> — banned by <code>{b['banned_by']}</code>" for b in bans]
    await msg.reply("🚫 <b>Banned users:</b>\n\n" + "\n".join(lines))


# ── /users ────────────────────────────────────────────────────────────────────

@router.message(Command("users"))
async def cmd_users(msg: Message) -> None:
    users = await all_users()
    if not users:
        await msg.reply("No users found.")
        return
    lines = []
    for u in users:
        uname = f"@{u['username']}" if u.get("username") else "—"
        status = u.get("status", "active")
        lines.append(f"• <code>{u['user_id']}</code> {uname} [{status}]")
    text = f"👥 <b>Users ({len(users)}):</b>\n\n" + "\n".join(lines)
    # Telegram message limit guard
    if len(text) > 4000:
        text = text[:3990] + "\n…(truncated)"
    await msg.reply(text)


# ── /broadcast ────────────────────────────────────────────────────────────────

@router.message(Command("broadcast"))
async def cmd_broadcast(msg: Message, bot: Bot) -> None:
    if not msg.reply_to_message:
        await msg.reply("⚠️ Reply to the message you want to broadcast.")
        return

    user_ids = await all_active_user_ids()
    sent = failed = 0
    for uid in user_ids:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=msg.chat.id,
                message_id=msg.reply_to_message.message_id,
            )
            sent += 1
        except Exception as exc:
            if "bot was blocked" in str(exc) or "user is deactivated" in str(exc):
                await mark_deleted(uid)
            failed += 1

    await msg.reply(f"📢 Broadcast complete.\n✅ Sent: {sent}\n❌ Failed: {failed}")


# ── /db ───────────────────────────────────────────────────────────────────────

@router.message(Command("db"))
async def cmd_db(msg: Message) -> None:
    db = get_db()
    stats = await db.command("dbStats")
    data_size_mb = round(stats.get("dataSize", 0) / 1024 / 1024, 2)
    storage_mb = round(stats.get("storageSize", 0) / 1024 / 1024, 2)
    collections = stats.get("collections", 0)

    user_count = await db.users.count_documents({})
    ban_count = await db.bans.count_documents({})
    msg_map_count = await db.message_map.count_documents({})

    await msg.reply(
        "🗄 <b>Database Info</b>\n\n"
        f"<b>Provider:</b> MongoDB Free Tier (512 MB cap)\n"
        f"<b>DB name:</b> <code>{db.name}</code>\n"
        f"<b>Collections:</b> {collections}\n"
        f"<b>Data size:</b> {data_size_mb} MB\n"
        f"<b>Storage used:</b> {storage_mb} MB\n\n"
        f"<b>Users:</b> {user_count}\n"
        f"<b>Bans:</b> {ban_count}\n"
        f"<b>Message mappings:</b> {msg_map_count}"
    )


# ── /setchannel ───────────────────────────────────────────────────────────────

@router.message(Command("setchannel"))
async def cmd_setchannel(msg: Message) -> None:
    parts = msg.text.split(maxsplit=2)
    # Usage: /setchannel add <id_or_link> [title]
    #        /setchannel remove <id>
    #        /setchannel list
    if len(parts) < 2:
        channels = await list_channels()
        if channels:
            lines = "\n".join(f"• {c['title']} (<code>{c['channel_id']}</code>)" for c in channels)
            await msg.reply(
                "📋 <b>Allowed channels:</b>\n\n" + lines + "\n\n"
                "Commands:\n"
                "<code>/setchannel add &lt;id_or_link&gt; [title]</code>\n"
                "<code>/setchannel remove &lt;id&gt;</code>"
            )
        else:
            await msg.reply(
                "No channels set.\n\n"
                "<code>/setchannel add &lt;id_or_link&gt; [title]</code>"
            )
        return

    action = parts[1].lower()

    if action == "list":
        channels = await list_channels()
        if not channels:
            await msg.reply("No allowed channels configured.")
        else:
            lines = "\n".join(f"• {c['title']} (<code>{c['channel_id']}</code>)" for c in channels)
            await msg.reply("📋 <b>Allowed channels:</b>\n\n" + lines)
        return

    if action == "add" and len(parts) >= 3:
        raw = parts[2].split(maxsplit=1)
        id_or_link = raw[0]
        title = raw[1] if len(raw) > 1 else None
        channel_id = extract_channel_id_from_link(id_or_link)
        if channel_id is None:
            await msg.reply("❌ Invalid channel ID or link.")
            return
        await add_channel(channel_id, title)
        await msg.reply(f"✅ Added channel <code>{channel_id}</code>.")
        return

    if action == "remove" and len(parts) >= 3:
        raw_id = parts[2].strip()
        channel_id = extract_channel_id_from_link(raw_id)
        if channel_id is None:
            await msg.reply("❌ Invalid channel ID.")
            return
        if await remove_channel(channel_id):
            await msg.reply(f"✅ Removed channel <code>{channel_id}</code>.")
        else:
            await msg.reply("ℹ️ Channel not found in allowed list.")
        return

    await msg.reply("⚠️ Usage: /setchannel [add|remove|list]")


# ── /captcha ──────────────────────────────────────────────────────────────────

@router.message(Command("captcha"))
async def cmd_captcha(msg: Message) -> None:
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        status = "on" if await captcha_enabled() else "off"
        await msg.reply(f"Current captcha status: <b>{status}</b>\nUsage: /captcha on | off")
        return
    enable = parts[1].lower() == "on"
    await set_captcha(enable)
    await msg.reply(f"✅ Captcha turned <b>{'on' if enable else 'off'}</b>.")


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _resolve_target_user_id(msg: Message) -> int | None:
    """Find the user_id the admin is targeting via reply chain."""
    if not msg.reply_to_message:
        return None

    replied = msg.reply_to_message
    mapping = await get_mapping_by_admin_msg(replied.message_id)
    if mapping:
        return mapping["user_id"]

    # The replied message might itself be an admin reply — try forward_from
    if replied.forward_from:
        return replied.forward_from.id

    return None
