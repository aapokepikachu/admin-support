from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import settings
from services.channel_service import (
    find_channel_by_username,
    is_allowed_channel,
    list_channels,
)
from services.message_map_service import save_mapping
from services.report_service import (
    count_templates,
    create_report_state,
    create_template,
    delete_template,
    get_report_state,
    get_template,
    get_template_by_slug,
    list_templates,
    resolve_report_state,
    save_report_admin_msg,
    update_template,
)
from services.user_service import upsert_user
from db import get_db

logger = logging.getLogger(__name__)
router = Router()

PAGE_SIZE = 5
_IN_ADMIN = F.chat.id == settings.ADMIN_GROUP_ID


# ── FSM States ────────────────────────────────────────────────────────────────

class CreateReport(StatesGroup):
    title = State()
    prompt_msg = State()
    invalid_msg = State()
    done_msg = State()


class EditReport(StatesGroup):
    new_value = State()


class UserReport(StatesGroup):
    waiting_link = State()


# ── /report user flow ─────────────────────────────────────────────────────────

@router.message(Command("report"), F.chat.type == "private")
async def cmd_report(msg: Message, state: FSMContext) -> None:
    channels = await list_channels()
    if not channels:
        await msg.answer(
            "ℹ️ No authorised channels configured yet.\n"
            "Ask an admin to add channels using /setchannel."
        )
        return

    lines = "\n".join(_channel_line(c) for c in channels)
    await state.set_state(UserReport.waiting_link)
    await msg.answer(
        "🔗 <b>Report a broken link</b>\n\n"
        f"Send the link from one of these channels:\n{lines}\n\n"
        "Only links from these channels are accepted.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="report_cancel")]
        ]),
        disable_web_page_preview=True,
    )


def _channel_line(c: dict) -> str:
    cid = str(c["channel_id"])
    title = c["title"]
    # Build a t.me link for private channels (strip -100 prefix)
    if cid.startswith("-100"):
        pure_id = cid[4:]  # remove -100
        return f"• <a href='https://t.me/c/{pure_id}/1'>{title}</a>"
    # Public channel stored as username (no -100 prefix numeric)
    return f"• <b>{title}</b>"


@router.callback_query(F.data == "report_cancel", F.message.chat.type == "private")
async def report_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.message.edit_text("❌ Report cancelled.")
    await cb.answer()


@router.message(UserReport.waiting_link, F.chat.type == "private", F.text)
async def report_got_link(msg: Message, state: FSMContext) -> None:
    link = msg.text.strip()
    user = msg.from_user

    # Parse the link to extract channel identifier
    channel_id, username = _parse_tme_link(link)

    allowed = False
    resolved_id = None

    if channel_id is not None:
        # Private channel link: t.me/c/XXXXXXXXX/msg
        allowed = await is_allowed_channel(channel_id)
        resolved_id = channel_id
    elif username is not None:
        # Public channel link: t.me/ChannelName/msg
        doc = await find_channel_by_username(username)
        if doc:
            allowed = True
            resolved_id = doc["channel_id"]

    if channel_id is None and username is None:
        # Not a recognisable Telegram post link at all
        await msg.answer(
            "❌ That doesn't look like a valid Telegram post link.\n"
            "Please send a link like:\n"
            "<code>https://t.me/ChannelName/123</code>\n"
            "or <code>https://t.me/c/1234567890/123</code>"
        )
        return

    if not allowed:
        await msg.answer(
            "⛔ <b>This channel is not supported.</b>\n\n"
            "We only accept reports for links from our authorised channels.\n"
            "Use /report to see the supported channels.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Cancel", callback_data="report_cancel")]
            ]),
        )
        return

    # Valid link from allowed channel — submit report
    await state.clear()
    uname = f"@{user.username}" if user.username else "no username"

    await msg.answer(
        "✅ <b>Report submitted!</b>\n\n"
        f"The link has been reported as not working.\n"
        "Admins have been notified and will fix it soon."
    )

    # Store link in DB keyed by a short token to avoid callback_data length issues
    token = await _store_link(link)

    try:
        await msg.bot.send_message(
            chat_id=settings.ADMIN_GROUP_ID,
            text=(
                f"🔴 <b>Broken Link Report</b>\n\n"
                f"<b>Link:</b> {link}\n"
                f"<b>Status:</b> Not working\n\n"
                f"<b>Reported by:</b> {user.first_name} ({uname})\n"
                f"<b>User ID:</b> <code>{user.id}</code>"
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Fixed",
                        callback_data=f"lrpt:fixed:{user.id}:{token}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Invalid",
                        callback_data=f"lrpt:invalid:{user.id}:{token}",
                    ),
                ]
            ]),
        )
    except Exception as exc:
        logger.error("Failed to send link report to admin group: %s", exc)


@router.callback_query(
    lambda c: c.data and c.data.startswith("lrpt:"),
    _IN_ADMIN,
)
async def link_report_action(cb: CallbackQuery) -> None:
    parts = cb.data.split(":", 3)
    if len(parts) != 4:
        await cb.answer("Malformed data.", show_alert=True)
        return

    _, action, user_id_str, token = parts
    user_id = int(user_id_str)
    link = await _retrieve_link(token)
    link_display = link if link else "(link unavailable)"

    if action == "fixed":
        user_msg = (
            f"✅ <b>Link Fixed!</b>\n\n"
            f"The link you reported has been fixed:\n{link_display}"
        )
        label = "✅ Fixed"
    else:
        user_msg = (
            f"ℹ️ <b>Link Still Working</b>\n\n"
            f"The link you reported is actually working fine:\n{link_display}"
        )
        label = "❌ Invalid"

    try:
        await cb.bot.send_message(chat_id=user_id, text=user_msg)
    except Exception as exc:
        logger.warning("Could not notify user %d: %s", user_id, exc)

    admin_name = cb.from_user.first_name
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.edit_text(
            cb.message.text + f"\n\n<i>Marked as {label} by {admin_name}</i>"
        )
    except Exception:
        pass

    await cb.answer(f"Marked as {label}")


# ── /reportgen ────────────────────────────────────────────────────────────────

@router.message(Command("reportgen"), _IN_ADMIN)
async def cmd_reportgen(msg: Message) -> None:
    await msg.answer(
        "🛠 <b>Report Link Generator</b>\n\nChoose an action:",
        reply_markup=_main_kb(),
    )


def _main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Create", callback_data="rgen:create"),
                InlineKeyboardButton(text="✏️ Edit", callback_data="rgen:edit:0"),
                InlineKeyboardButton(text="🗑 Delete", callback_data="rgen:delete:0"),
            ]
        ]
    )


# ── Create ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "rgen:create", F.message.chat.id == settings.ADMIN_GROUP_ID)
async def rgen_create_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateReport.title)
    await cb.message.edit_text(
        "➕ <b>Create Report Link — Step 1/4</b>\n\n"
        "Send the <b>title</b> for this report link.\n"
        "Example: <i>Hoppa link</i>"
    )
    await cb.answer()


@router.message(CreateReport.title, _IN_ADMIN, F.text)
async def rgen_got_title(msg: Message, state: FSMContext) -> None:
    await state.update_data(title=msg.text.strip())
    await state.set_state(CreateReport.prompt_msg)
    await msg.answer(
        "<b>Step 2/4</b> — Send the <b>report prompt message</b>.\n"
        "Shown to users when they open the report link.\n"
        "Example: <i>Do you want to report that Movie Hoppa is not working?</i>"
    )


@router.message(CreateReport.prompt_msg, _IN_ADMIN, F.text)
async def rgen_got_prompt(msg: Message, state: FSMContext) -> None:
    await state.update_data(prompt_msg=msg.text.strip())
    await state.set_state(CreateReport.invalid_msg)
    await msg.answer(
        "<b>Step 3/4</b> — Send the <b>invalid/resolved message</b>.\n"
        "Sent to users when an admin marks the report as Invalid.\n"
        "Example: <i>The Movie Hoppa link is working fine, there is no issue.</i>"
    )


@router.message(CreateReport.invalid_msg, _IN_ADMIN, F.text)
async def rgen_got_invalid(msg: Message, state: FSMContext) -> None:
    await state.update_data(invalid_msg=msg.text.strip())
    await state.set_state(CreateReport.done_msg)
    await msg.answer(
        "<b>Step 4/4</b> — Send the <b>done/fixed message</b>.\n"
        "Sent to users when an admin marks the report as Done.\n"
        "Example: <i>The movie link has been fixed.</i>"
    )


@router.message(CreateReport.done_msg, _IN_ADMIN, F.text)
async def rgen_got_done(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    # msg.text IS the done_msg — use directly, do NOT read from state data
    done_msg_text = msg.text.strip()
    try:
        template = await create_template(
            title=data["title"],
            prompt_msg=data["prompt_msg"],
            invalid_msg=data["invalid_msg"],
            done_msg=done_msg_text,
        )
        bot_info = await msg.bot.get_me()
        deep_link = f"https://t.me/{bot_info.username}?start=report_{template['slug']}"
        await msg.answer(
            f"✅ <b>Report link created!</b>\n\n"
            f"<b>Title:</b> {template['title']}\n\n"
            f"<b>Deep link:</b>\n<code>{deep_link}</code>\n\n"
            "Share this link with users to let them submit reports."
        )
    except KeyError as exc:
        logger.error("FSM data missing key %s — data: %s", exc, data)
        await msg.answer(
            f"❌ Setup incomplete — missing field {exc}.\n"
            "Please start over with /reportgen → Create."
        )
    except Exception as exc:
        logger.error("Failed to create report template: %s", exc)
        await msg.answer(f"❌ Failed to save: {exc}")


# ── Delete ────────────────────────────────────────────────────────────────────

@router.callback_query(
    lambda c: c.data and c.data.startswith("rgen:delete:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rgen_delete_list(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[2])
    templates = await list_templates(page, PAGE_SIZE)
    total = await count_templates()
    if not templates:
        await cb.message.edit_text("ℹ️ No report links found.")
        await cb.answer()
        return
    buttons = [
        [InlineKeyboardButton(text=t["title"], callback_data=f"rgen:del_confirm:{t['_id']}")]
        for t in templates
    ]
    nav = _nav_buttons("rgen:delete", page, total)
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="« Back", callback_data="rgen:back")])
    await cb.message.edit_text(
        "🗑 <b>Delete — select a link:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await cb.answer()


@router.callback_query(
    lambda c: c.data and c.data.startswith("rgen:del_confirm:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rgen_delete_confirm(cb: CallbackQuery) -> None:
    tid = cb.data.split(":", 2)[2]
    template = await get_template(tid)
    if not template:
        await cb.message.edit_text("❌ Template not found.")
        await cb.answer()
        return
    await cb.message.edit_text(
        f"⚠️ Delete <b>{template['title']}</b>?\nThis cannot be undone.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm", callback_data=f"rgen:del_do:{tid}"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="rgen:delete:0"),
            ]
        ]),
    )
    await cb.answer()


@router.callback_query(
    lambda c: c.data and c.data.startswith("rgen:del_do:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rgen_delete_do(cb: CallbackQuery) -> None:
    tid = cb.data.split(":", 2)[2]
    template = await get_template(tid)
    title = template["title"] if template else tid
    if await delete_template(tid):
        await cb.message.edit_text(f"✅ <b>{title}</b> deleted.")
    else:
        await cb.message.edit_text("❌ Deletion failed.")
    await cb.answer()


# ── Edit ──────────────────────────────────────────────────────────────────────

@router.callback_query(
    lambda c: c.data and c.data.startswith("rgen:edit:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rgen_edit_list(cb: CallbackQuery) -> None:
    page = int(cb.data.split(":")[2])
    templates = await list_templates(page, PAGE_SIZE)
    total = await count_templates()
    if not templates:
        await cb.message.edit_text("ℹ️ No report links found.")
        await cb.answer()
        return
    buttons = [
        [InlineKeyboardButton(text=t["title"], callback_data=f"rgen:edit_fields:{t['_id']}")]
        for t in templates
    ]
    nav = _nav_buttons("rgen:edit", page, total)
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="« Back", callback_data="rgen:back")])
    await cb.message.edit_text(
        "✏️ <b>Edit — select a link:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await cb.answer()


@router.callback_query(
    lambda c: c.data and c.data.startswith("rgen:edit_fields:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rgen_edit_fields(cb: CallbackQuery) -> None:
    tid = cb.data.split(":", 2)[2]
    template = await get_template(tid)
    if not template:
        await cb.message.edit_text("❌ Template not found.")
        await cb.answer()
        return
    await cb.message.edit_text(
        f"✏️ Editing: <b>{template['title']}</b>\n\nChoose a field:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Title", callback_data=f"rgen:edit_field:{tid}:title")],
            [InlineKeyboardButton(text="Prompt message", callback_data=f"rgen:edit_field:{tid}:prompt_msg")],
            [InlineKeyboardButton(text="Invalid message", callback_data=f"rgen:edit_field:{tid}:invalid_msg")],
            [InlineKeyboardButton(text="Done message", callback_data=f"rgen:edit_field:{tid}:done_msg")],
            [InlineKeyboardButton(text="« Back", callback_data="rgen:edit:0")],
        ]),
    )
    await cb.answer()


@router.callback_query(
    lambda c: c.data and c.data.startswith("rgen:edit_field:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rgen_edit_field_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    parts = cb.data.split(":", 3)
    tid, field = parts[2], parts[3]
    await state.set_state(EditReport.new_value)
    await state.update_data(edit_tid=tid, edit_field=field)
    labels = {
        "title": "Title", "prompt_msg": "Prompt message",
        "invalid_msg": "Invalid message", "done_msg": "Done message",
    }
    await cb.message.edit_text(
        f"✏️ Send the new value for <b>{labels.get(field, field)}</b>:"
    )
    await cb.answer()


@router.message(EditReport.new_value, _IN_ADMIN, F.text)
async def rgen_edit_save(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    try:
        if await update_template(data["edit_tid"], {data["edit_field"]: msg.text.strip()}):
            await msg.answer("✅ Field updated.")
        else:
            await msg.answer("❌ Update failed — template not found.")
    except Exception as exc:
        logger.error("Failed to update template: %s", exc)
        await msg.answer(f"❌ Error: {exc}")


# ── Back ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "rgen:back", F.message.chat.id == settings.ADMIN_GROUP_ID)
async def rgen_back(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        "🛠 <b>Report Link Generator</b>\n\nChoose an action:",
        reply_markup=_main_kb(),
    )
    await cb.answer()


# ── Deep-link report (Proceed / Cancel) ──────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("rpt_proceed:"))
async def rpt_proceed(cb: CallbackQuery) -> None:
    tid = cb.data.split(":", 1)[1]
    user = cb.from_user
    await upsert_user(user)

    template = await get_template(tid)
    if not template:
        await cb.answer("❌ This report link no longer exists.", show_alert=True)
        return

    state = await get_report_state(user.id, tid)
    if state and state["status"] == "pending":
        await cb.answer("⏳ You already have a pending report. Wait for admin resolution.", show_alert=True)
        return

    await create_report_state(user.id, tid)
    uname = f"@{user.username}" if user.username else "no username"

    try:
        sent = await cb.bot.send_message(
            chat_id=settings.ADMIN_GROUP_ID,
            text=(
                f"🚨 <b>New Report</b>\n\n"
                f"{template['prompt_msg']}\n\n"
                f"<b>Reported by:</b> {user.first_name} ({uname})\n"
                f"<b>User ID:</b> <code>{user.id}</code>"
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Done", callback_data=f"rpt_admin:done:{user.id}:{tid}"),
                    InlineKeyboardButton(text="❌ Invalid", callback_data=f"rpt_admin:invalid:{user.id}:{tid}"),
                ]
            ]),
        )
        await save_report_admin_msg(user.id, tid, sent.message_id)
    except Exception as exc:
        logger.error("Failed to send report to admin group: %s", exc)
        await cb.answer("❌ Failed to submit. Try again.", show_alert=True)
        return

    await cb.message.edit_text(
        "✅ <b>Report submitted!</b>\n\n"
        "Admins have been notified. You will receive a message once resolved."
    )
    await cb.answer("Report sent!")


@router.callback_query(lambda c: c.data == "rpt_cancel")
async def rpt_cancel(cb: CallbackQuery) -> None:
    await cb.message.edit_text("❌ Report cancelled.")
    await cb.answer()


# ── Admin: Done / Invalid on deep-link reports ────────────────────────────────

@router.callback_query(
    lambda c: c.data and c.data.startswith("rpt_admin:"),
    _IN_ADMIN,
)
async def rpt_admin_action(cb: CallbackQuery) -> None:
    parts = cb.data.split(":")
    if len(parts) != 4:
        await cb.answer("Malformed data.", show_alert=True)
        return

    _, action, user_id_str, tid = parts
    user_id = int(user_id_str)

    template = await get_template(tid)
    if not template:
        await cb.answer("Template no longer exists.", show_alert=True)
        return

    state = await get_report_state(user_id, tid)
    if not state or state["status"] != "pending":
        await cb.answer("Already resolved.", show_alert=True)
        return

    if action == "done":
        reply_text, status, label = template["done_msg"], "done", "✅ Done"
    else:
        reply_text, status, label = template["invalid_msg"], "invalid", "❌ Invalid"

    await resolve_report_state(user_id, tid, status)

    try:
        await cb.bot.send_message(chat_id=user_id, text=reply_text)
    except Exception as exc:
        logger.warning("Could not notify user %d: %s", user_id, exc)

    admin_name = cb.from_user.first_name
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
        await cb.message.edit_text(
            cb.message.text + f"\n\n<i>Resolved as {label} by {admin_name}</i>"
        )
    except Exception:
        pass

    await cb.answer(f"Marked as {label}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_tme_link(link: str) -> tuple[int | None, str | None]:
    """
    Parse a t.me link and return (channel_id, username).
    Exactly one of the two will be non-None, or both None if not a valid link.

    Private:  t.me/c/1234567890/45  -> (-1001234567890, None)
    Public:   t.me/PkmnMovie/45     -> (None, "PkmnMovie")
    """
    # Private channel: /c/<pure_id>/<msg>
    m = re.search(r"t\.me/c/(\d+)/\d+", link)
    if m:
        return (-int("100" + m.group(1)), None)

    # Public channel: /username/<msg>  (username = letters/digits/underscore, min 4 chars)
    m = re.search(r"t\.me/([A-Za-z][A-Za-z0-9_]{3,})/(\d+)", link)
    if m:
        return (None, m.group(1))

    return (None, None)


async def _store_link(link: str) -> str:
    """Store a link in MongoDB and return its short token (ObjectId hex string)."""
    from datetime import datetime
    result = await get_db().link_tokens.insert_one({
        "link": link,
        "created_at": datetime.utcnow(),
    })
    return str(result.inserted_id)


async def _retrieve_link(token: str) -> str | None:
    """Retrieve a stored link by its token."""
    from bson import ObjectId
    try:
        doc = await get_db().link_tokens.find_one({"_id": ObjectId(token)})
        return doc["link"] if doc else None
    except Exception:
        return None


def _nav_buttons(prefix: str, page: int, total: int) -> list[InlineKeyboardButton] | None:
    btns = []
    if page > 0:
        btns.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"{prefix}:{page - 1}"))
    if (page + 1) * PAGE_SIZE < total:
        btns.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"{prefix}:{page + 1}"))
    return btns or None
