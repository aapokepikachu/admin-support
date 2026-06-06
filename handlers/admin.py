from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import settings
from db import get_db
from services.ban_service import ban_list, ban_user, is_banned, unban_user
from services.captcha_service import captcha_enabled, set_captcha
from services.channel_service import add_channel, list_channels, remove_channel
from services.message_map_service import get_mapping_by_admin_msg
from services.user_service import all_active_user_ids, all_users, mark_deleted
from utils.helpers import parse_channel_id

logger = logging.getLogger(__name__)
router = Router()

# Scope to the admin group only
router.message.filter(F.chat.id == settings.ADMIN_GROUP_ID)


# ── /helpa ────────────────────────────────────────────────────────────────────

@router.message(Command("helpa"))
async def cmd_helpa(msg: Message) -> None:
    await msg.answer(
        "🛠 <b>Admin Commands</b>\n\n"
        "<b>Moderation</b>\n"
        "/ban — Reply to a user message to ban them\n"
        "/unban &lt;id or @username&gt; — Unban a user\n"
        "/banlist — List all banned users\n"
        "/users — List all registered users\n\n"
        "<b>Broadcast</b>\n"
        "/broadcast — Reply to a message to send it to all users\n\n"
        "<b>Channels</b>\n"
        "/setchannel [add|remove|list] — Manage allowed channels for /report\n\n"
        "<b>Reports</b>\n"
        "/reportgen — Create, edit, or delete report deep-links\n\n"
        "<b>Captcha</b>\n"
        "/captcha on|off — Toggle captcha for new users\n\n"
        "<b>System</b>\n"
        "/db — Database health info\n"
        "/helpa — This message"
    )


# ── /ban ──────────────────────────────────────────────────────────────────────

@router.message(Command("ban"))
async def cmd_ban(msg: Message) -> None:
    target_id = await _resolve_target(msg)
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
        arg = parts[1].lstrip("@").strip()
        if arg.isdigit():
            target_id = int(arg)
        else:
            doc = await get_db().users.find_one({"username": arg})
            if doc:
                target_id = doc["user_id"]

    if target_id is None:
        target_id = await _resolve_target(msg)

    if target_id is None:
        await msg.reply("⚠️ Usage: /unban &lt;id or @username&gt;, or reply to their message.")
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
    lines = [
        f"• <code>{b['user_id']}</code> — banned by <code>{b['banned_by']}</code>"
        for b in bans
    ]
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
        lines.append(f"• <code>{u['user_id']}</code> {uname} [{u.get('status', 'active')}]")
    text = f"👥 <b>Users ({len(users)}):</b>\n\n" + "\n".join(lines)
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
            if "bot was blocked" in str(exc).lower() or "user is deactivated" in str(exc).lower():
                await mark_deleted(uid)
            failed += 1

    await msg.reply(f"📢 Broadcast complete.\n✅ Sent: {sent}\n❌ Failed: {failed}")


# ── /db ───────────────────────────────────────────────────────────────────────

@router.message(Command("db"))
async def cmd_db(msg: Message) -> None:
    db = get_db()
    stats = await db.command("dbStats")
    data_mb = round(stats.get("dataSize", 0) / 1024 / 1024, 2)
    storage_mb = round(stats.get("storageSize", 0) / 1024 / 1024, 2)

    user_count = await db.users.count_documents({})
    ban_count = await db.bans.count_documents({})
    map_count = await db.message_map.count_documents({})
    template_count = await db.report_templates.count_documents({})

    await msg.reply(
        "🗄 <b>Database Info</b>\n\n"
        "Provider: MongoDB Atlas Free Tier (512 MB cap)\n"
        f"Database: <code>{db.name}</code>\n"
        f"Data size: {data_mb} MB\n"
        f"Storage used: {storage_mb} MB\n\n"
        f"Users: {user_count}\n"
        f"Bans: {ban_count}\n"
        f"Message mappings: {map_count}\n"
        f"Report templates: {template_count}"
    )


# ── /setchannel ───────────────────────────────────────────────────────────────

@router.message(Command("setchannel"))
async def cmd_setchannel(msg: Message) -> None:
    parts = msg.text.split(maxsplit=2)

    async def _show_list() -> None:
        channels = await list_channels()
        if channels:
            lines = "\n".join(
                f"• {c['title']} (<code>{c['channel_id']}</code>)" for c in channels
            )
            await msg.reply(
                f"📋 <b>Allowed channels:</b>\n\n{lines}\n\n"
                "<code>/setchannel add &lt;numeric_id&gt; [title]</code>\n"
                "<code>/setchannel remove &lt;numeric_id&gt;</code>"
            )
        else:
            await msg.reply(
                "No channels set.\n\n"
                "<code>/setchannel add &lt;numeric_id&gt; [title]</code>"
            )

    if len(parts) < 2:
        await _show_list()
        return

    action = parts[1].lower()

    if action == "list":
        await _show_list()
        return

    if action == "add" and len(parts) >= 3:
        tokens = parts[2].split(maxsplit=1)
        raw_id = tokens[0]
        title = tokens[1] if len(tokens) > 1 else None
        channel_id = parse_channel_id(raw_id)
        if channel_id is None:
            await msg.reply(
                "❌ Invalid ID. Use the numeric channel ID (e.g. <code>-1001234567890</code>)."
            )
            return
        await add_channel(channel_id, title)
        await msg.reply(f"✅ Added channel <code>{channel_id}</code>.")
        return

    if action == "remove" and len(parts) >= 3:
        channel_id = parse_channel_id(parts[2].strip())
        if channel_id is None:
            await msg.reply("❌ Invalid ID.")
            return
        if await remove_channel(channel_id):
            await msg.reply(f"✅ Removed channel <code>{channel_id}</code>.")
        else:
            await msg.reply("ℹ️ Channel not found in the allowed list.")
        return

    await msg.reply("⚠️ Usage: /setchannel [add|remove|list]")


# ── /captcha ──────────────────────────────────────────────────────────────────

@router.message(Command("captcha"))
async def cmd_captcha(msg: Message) -> None:
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        status = "on" if await captcha_enabled() else "off"
        await msg.reply(
            f"Current captcha status: <b>{status}</b>\n"
            "Usage: /captcha on | off"
        )
        return
    enable = parts[1].lower() == "on"
    await set_captcha(enable)
    await msg.reply(f"✅ Captcha turned <b>{'on' if enable else 'off'}</b>.")


# ── Reply routing: admin → user ───────────────────────────────────────────────
# IMPORTANT: registered LAST so all command handlers above take priority.
# Uses explicit ~F.text.startswith("/") filter to never match commands.

@router.message(F.reply_to_message & ~F.text.startswith("/"))
async def admin_reply_to_user(msg: Message, bot: Bot) -> None:
    replied = msg.reply_to_message
    mapping = await get_mapping_by_admin_msg(replied.message_id)
    if mapping is None:
        return  # Not a forwarded user message — ignore silently

    user_id: int = mapping["user_id"]
    try:
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=msg.chat.id,
            message_id=msg.message_id,
        )
    except Exception as exc:
        err = str(exc).lower()
        if "bot was blocked" in err or "user is deactivated" in err:
            await mark_deleted(user_id)
            await msg.reply(
                f"⚠️ Could not deliver: user <code>{user_id}</code> has blocked "
                "the bot or deleted their account."
            )
        else:
            logger.error("Reply delivery failed for user %d: %s", user_id, exc)
            await msg.reply(f"❌ Delivery failed: {exc}")


# ── Helper ────────────────────────────────────────────────────────────────────

async def _resolve_target(msg: Message) -> int | None:
    if not msg.reply_to_message:
        return None
    mapping = await get_mapping_by_admin_msg(msg.reply_to_message.message_id)
    if mapping:
        return mapping["user_id"]
    if msg.reply_to_message.forward_from:
        return msg.reply_to_message.forward_from.id
    return None
