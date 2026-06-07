from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

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
router.message.filter(F.chat.id == settings.ADMIN_GROUP_ID)

_IN_ADMIN_CB = F.message.chat.id == settings.ADMIN_GROUP_ID


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
        "/setchannel [add|remove|list] — Manage allowed channels\n\n"
        "<b>Reports</b>\n"
        "/reportgen — Create, edit, or delete report deep-links\n\n"
        "<b>Captcha</b>\n"
        "/captcha on|off — Toggle captcha for new users\n\n"
        "<b>System</b>\n"
        "/db — Database health + management actions\n"
        "/setreportcount &lt;n&gt; — Set max /report submissions per user\n"
        "/reportlist — View all active link reports\n"
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
    lines = [f"• <code>{b['user_id']}</code> — banned by <code>{b['banned_by']}</code>" for b in bans]
    await msg.reply("🚫 <b>Banned users:</b>\n\n" + "\n".join(lines))


# ── /users ────────────────────────────────────────────────────────────────────

@router.message(Command("users"))
async def cmd_users(msg: Message) -> None:
    users = await all_users()
    if not users:
        await msg.reply("No users found.")
        return
    lines = [
        f"• <code>{u['user_id']}</code> {'@' + u['username'] if u.get('username') else '—'} [{u.get('status', 'active')}]"
        for u in users
    ]
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
            await bot.copy_message(chat_id=uid, from_chat_id=msg.chat.id, message_id=msg.reply_to_message.message_id)
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
    data_mb    = round(stats.get("dataSize", 0) / 1024 / 1024, 2)
    storage_mb = round(stats.get("storageSize", 0) / 1024 / 1024, 2)
    user_count     = await db.users.count_documents({})
    ban_count      = await db.bans.count_documents({})
    map_count      = await db.message_map.count_documents({})
    template_count = await db.report_templates.count_documents({})
    cap_status = "on" if await captcha_enabled() else "off"

    await msg.reply(
        "🗄 <b>Database Info</b>\n\n"
        "Provider: MongoDB Atlas Free Tier (512 MB cap)\n"
        f"Database: <code>{db.name}</code>\n"
        f"Data size: {data_mb} MB\n"
        f"Storage used: {storage_mb} MB\n\n"
        f"👥 Users: {user_count}\n"
        f"🚫 Bans: {ban_count}\n"
        f"💬 Message mappings: {map_count}\n"
        f"📋 Report templates: {template_count}\n"
        f"🔐 Captcha: {cap_status}\n\n"
        "⚠️ <b>Danger Zone:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Delete all report templates", callback_data="db:del_templates")],
            [InlineKeyboardButton(text="💬 Clear message map",           callback_data="db:del_msgmap")],
            [InlineKeyboardButton(text="🔐 Reset all captcha passes",    callback_data="db:reset_captcha")],
            [InlineKeyboardButton(text="🗑 Wipe entire database",        callback_data="db:wipe_all")],
        ]),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("db:"), _IN_ADMIN_CB)
async def db_action(cb: CallbackQuery) -> None:
    action = cb.data.split(":", 1)[1]

    if action == "del_templates":
        await cb.message.edit_text(
            "⚠️ Delete ALL report templates and their states?",
            reply_markup=_confirm_kb("db_confirm:del_templates"),
        )
    elif action == "del_msgmap":
        await cb.message.edit_text(
            "⚠️ Clear all message mappings?\n(Admin replies to old forwarded messages will stop routing.)",
            reply_markup=_confirm_kb("db_confirm:del_msgmap"),
        )
    elif action == "reset_captcha":
        await cb.message.edit_text(
            "⚠️ Reset captcha for ALL users?\n(Everyone will need to solve captcha again if it is enabled.)",
            reply_markup=_confirm_kb("db_confirm:reset_captcha"),
        )
    elif action == "wipe_all":
        await cb.message.edit_text(
            "🚨 <b>WIPE ENTIRE DATABASE?</b>\n\nThis deletes users, bans, messages, reports, everything. Cannot be undone.",
            reply_markup=_confirm_kb("db_confirm:wipe_all"),
        )
    await cb.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("db_confirm:"), _IN_ADMIN_CB)
async def db_confirm(cb: CallbackQuery) -> None:
    action = cb.data.split(":", 1)[1]
    db = get_db()
    admin = cb.from_user.first_name

    if action == "del_templates":
        await db.report_templates.delete_many({})
        await db.report_states.delete_many({})
        await cb.message.edit_text(f"✅ All report templates and states deleted by {admin}.")

    elif action == "del_msgmap":
        await db.message_map.delete_many({})
        await cb.message.edit_text(f"✅ Message map cleared by {admin}.")

    elif action == "reset_captcha":
        await db.users.update_many({}, {"$unset": {"captcha_passed": ""}})
        await db.captcha_sessions.delete_many({})
        await cb.message.edit_text(f"✅ Captcha reset for all users by {admin}.")

    elif action == "wipe_all":
        for col in ["users", "bans", "message_map", "report_templates", "report_states",
                    "allowed_channels", "rate_limit", "captcha_sessions", "link_reports", "burst_track", "fsm_states"]:
            await db[col].delete_many({})
        await cb.message.edit_text(f"💥 Database wiped by {admin}.")

    await cb.answer("Done")


@router.callback_query(lambda c: c.data == "db_cancel", _IN_ADMIN_CB)
async def db_cancel(cb: CallbackQuery) -> None:
    await cb.message.edit_text("❌ Action cancelled.")
    await cb.answer()


def _confirm_kb(confirm_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yes, do it", callback_data=confirm_data),
        InlineKeyboardButton(text="❌ Cancel",     callback_data="db_cancel"),
    ]])


# ── /setchannel ───────────────────────────────────────────────────────────────

@router.message(Command("setchannel"))
async def cmd_setchannel(msg: Message) -> None:
    parts = msg.text.split(maxsplit=2)

    async def _show_list() -> None:
        channels = await list_channels()
        if channels:
            lines = "\n".join(f"• {c['title']} (<code>{c['channel_id']}</code>)" for c in channels)
            await msg.reply(
                f"📋 <b>Allowed channels:</b>\n\n{lines}\n\n"
                "<code>/setchannel add &lt;numeric_id&gt; [title]</code>\n"
                "<code>/setchannel remove &lt;numeric_id&gt;</code>"
            )
        else:
            await msg.reply("No channels set.\n\n<code>/setchannel add &lt;numeric_id&gt; [title]</code>")

    if len(parts) < 2:
        await _show_list(); return

    action = parts[1].lower()
    if action == "list":
        await _show_list(); return

    if action == "add" and len(parts) >= 3:
        tokens = parts[2].split(maxsplit=1)
        channel_id = parse_channel_id(tokens[0])
        if channel_id is None:
            await msg.reply("❌ Invalid ID. Use the numeric channel ID (e.g. <code>-1001234567890</code>).")
            return
        title = tokens[1] if len(tokens) > 1 else None
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
            await msg.reply("ℹ️ Channel not found.")
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


# ── Reply routing: admin → user (registered LAST) ─────────────────────────────

@router.message(F.reply_to_message & ~F.text.startswith("/"))
async def admin_reply_to_user(msg: Message, bot: Bot) -> None:
    mapping = await get_mapping_by_admin_msg(msg.reply_to_message.message_id)
    if mapping is None:
        return
    user_id: int = mapping["user_id"]
    try:
        await bot.copy_message(chat_id=user_id, from_chat_id=msg.chat.id, message_id=msg.message_id)
    except Exception as exc:
        err = str(exc).lower()
        if "bot was blocked" in err or "user is deactivated" in err:
            await mark_deleted(user_id)
            await msg.reply(f"⚠️ Could not deliver: user <code>{user_id}</code> has blocked the bot.")
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


# ── /setreportcount ───────────────────────────────────────────────────────────

@router.message(Command("setreportcount"))
async def cmd_setreportcount(msg: Message) -> None:
    from services.link_report_service import get_report_limit, set_report_limit
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        current = await get_report_limit()
        await msg.reply(
            f"Current report limit: <b>{current}</b> per user\n\n"
            "Usage: <code>/setreportcount &lt;number&gt;</code>\n"
            "Example: <code>/setreportcount 5</code>"
        )
        return
    n = int(parts[1].strip())
    if n < 1 or n > 50:
        await msg.reply("❌ Value must be between 1 and 50.")
        return
    await set_report_limit(n)
    await msg.reply(f"✅ Report limit set to <b>{n}</b> per user.")


# ── /reportlist (admin view) ──────────────────────────────────────────────────

@router.message(Command("reportlist"))
async def cmd_reportlist_admin(msg: Message) -> None:
    from services.link_report_service import get_all_pending_reports, get_report_limit
    reports = await get_all_pending_reports()
    limit = await get_report_limit()
    if not reports:
        await msg.reply("✅ No active link reports.")
        return
    lines = [
        f"• <code>{r['user_id']}</code> — <code>{r['link']}</code>"
        for r in reports
    ]
    text = f"📋 <b>Active link reports ({len(reports)}) — limit: {limit}/user:</b>\n\n" + "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…(truncated)"
    await msg.reply(text)
