from __future__ import annotations

import logging
from typing import Any

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
from services.report_service import (
    count_templates,
    create_report_state,
    create_template,
    delete_template,
    get_report_by_admin_msg,
    get_report_state,
    get_template,
    get_template_by_slug,
    list_templates,
    resolve_report_state,
    save_report_admin_msg,
    update_template,
)
from services.user_service import get_user
from utils.tg_helpers import user_mention

logger = logging.getLogger(__name__)
router = Router()

PAGE_SIZE = 5


# ── FSM States ────────────────────────────────────────────────────────────────

class CreateReport(StatesGroup):
    title = State()
    prompt_msg = State()
    invalid_msg = State()
    done_msg = State()


class EditReport(StatesGroup):
    choose_field = State()
    new_value = State()


# ── /reportgen (admin group only) ────────────────────────────────────────────

@router.message(Command("reportgen"), F.chat.id == settings.ADMIN_GROUP_ID)
async def cmd_reportgen(msg: Message) -> None:
    await msg.answer(
        "🛠 <b>Report Link Generator</b>\n\nChoose an action:",
        reply_markup=_reportgen_main_kb(),
    )


def _reportgen_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Create", callback_data="rgen:create"),
                InlineKeyboardButton(text="✏️ Edit", callback_data="rgen:edit:0"),
                InlineKeyboardButton(text="🗑 Delete", callback_data="rgen:delete:0"),
            ]
        ]
    )


# ── Create flow ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "rgen:create", F.message.chat.id == settings.ADMIN_GROUP_ID)
async def rgen_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CreateReport.title)
    await callback.message.edit_text(
        "➕ <b>Create Report Link</b>\n\nStep 1/4 — Send the <b>title</b> for this report link.\n"
        "Example: <i>Hoppa link</i>"
    )
    await callback.answer()


@router.message(CreateReport.title, F.chat.id == settings.ADMIN_GROUP_ID)
async def rgen_got_title(msg: Message, state: FSMContext) -> None:
    await state.update_data(title=msg.text.strip())
    await state.set_state(CreateReport.prompt_msg)
    await msg.answer(
        "Step 2/4 — Send the <b>report prompt message</b>.\n"
        "This is shown to users when they open the report link.\n"
        "Example: <i>Do you want to report that Movie Hoppa is not working?</i>"
    )


@router.message(CreateReport.prompt_msg, F.chat.id == settings.ADMIN_GROUP_ID)
async def rgen_got_prompt(msg: Message, state: FSMContext) -> None:
    await state.update_data(prompt_msg=msg.text.strip())
    await state.set_state(CreateReport.invalid_msg)
    await msg.answer(
        "Step 3/4 — Send the <b>invalid/resolved message</b>.\n"
        "Sent to the user when an admin marks the report as Invalid.\n"
        "Example: <i>The Movie Hoppa link is working fine, there is no issue.</i>"
    )


@router.message(CreateReport.invalid_msg, F.chat.id == settings.ADMIN_GROUP_ID)
async def rgen_got_invalid(msg: Message, state: FSMContext) -> None:
    await state.update_data(invalid_msg=msg.text.strip())
    await state.set_state(CreateReport.done_msg)
    await msg.answer(
        "Step 4/4 — Send the <b>done/fixed message</b>.\n"
        "Sent to the user when an admin marks the report as Done.\n"
        "Example: <i>The movie link has been fixed.</i>"
    )


@router.message(CreateReport.done_msg, F.chat.id == settings.ADMIN_GROUP_ID)
async def rgen_got_done(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()

    template = await create_template(
        title=data["title"],
        prompt_msg=data["prompt_msg"],
        invalid_msg=data["invalid_msg"],
        done_msg=data["done_msg"],
    )
    bot_info = await msg.bot.get_me()
    deep_link = f"https://t.me/{bot_info.username}?start=report_{template['slug']}"

    await msg.answer(
        f"✅ <b>Report link created!</b>\n\n"
        f"<b>Title:</b> {template['title']}\n"
        f"<b>Deep link:</b>\n<code>{deep_link}</code>\n\n"
        f"Share this link with users to let them report issues."
    )


# ── Delete flow ───────────────────────────────────────────────────────────────

@router.callback_query(
    lambda c: c.data and c.data.startswith("rgen:delete:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rgen_delete_list(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[2])
    templates = await list_templates(page, PAGE_SIZE)
    total = await count_templates()

    if not templates:
        await callback.message.edit_text("ℹ️ No report links found.")
        await callback.answer()
        return

    buttons = [
        [InlineKeyboardButton(
            text=t["title"],
            callback_data=f"rgen:del_confirm:{str(t['_id'])}",
        )]
        for t in templates
    ]
    nav = _pagination_nav("rgen:delete", page, total)
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="« Back", callback_data="rgen:back")])

    await callback.message.edit_text(
        "🗑 <b>Delete Report Link</b>\n\nSelect a link to delete:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(
    lambda c: c.data and c.data.startswith("rgen:del_confirm:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rgen_delete_confirm(callback: CallbackQuery) -> None:
    tid = callback.data.split(":", 2)[2]
    template = await get_template(tid)
    if not template:
        await callback.message.edit_text("❌ Template not found.")
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm Delete", callback_data=f"rgen:del_do:{tid}"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="rgen:delete:0"),
            ]
        ]
    )
    await callback.message.edit_text(
        f"⚠️ Delete <b>{template['title']}</b>?\n\nThis cannot be undone.",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(
    lambda c: c.data and c.data.startswith("rgen:del_do:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rgen_delete_do(callback: CallbackQuery) -> None:
    tid = callback.data.split(":", 2)[2]
    template = await get_template(tid)
    title = template["title"] if template else tid
    if await delete_template(tid):
        await callback.message.edit_text(f"✅ <b>{title}</b> deleted.")
    else:
        await callback.message.edit_text("❌ Deletion failed.")
    await callback.answer()


# ── Edit flow ─────────────────────────────────────────────────────────────────

@router.callback_query(
    lambda c: c.data and c.data.startswith("rgen:edit:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rgen_edit_list(callback: CallbackQuery) -> None:
    page = int(callback.data.split(":")[2])
    templates = await list_templates(page, PAGE_SIZE)
    total = await count_templates()

    if not templates:
        await callback.message.edit_text("ℹ️ No report links found.")
        await callback.answer()
        return

    buttons = [
        [InlineKeyboardButton(
            text=t["title"],
            callback_data=f"rgen:edit_fields:{str(t['_id'])}",
        )]
        for t in templates
    ]
    nav = _pagination_nav("rgen:edit", page, total)
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="« Back", callback_data="rgen:back")])

    await callback.message.edit_text(
        "✏️ <b>Edit Report Link</b>\n\nSelect a link to edit:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@router.callback_query(
    lambda c: c.data and c.data.startswith("rgen:edit_fields:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rgen_edit_fields(callback: CallbackQuery) -> None:
    tid = callback.data.split(":", 2)[2]
    template = await get_template(tid)
    if not template:
        await callback.message.edit_text("❌ Template not found.")
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Title", callback_data=f"rgen:edit_field:{tid}:title")],
            [InlineKeyboardButton(text="Prompt message", callback_data=f"rgen:edit_field:{tid}:prompt_msg")],
            [InlineKeyboardButton(text="Invalid message", callback_data=f"rgen:edit_field:{tid}:invalid_msg")],
            [InlineKeyboardButton(text="Done message", callback_data=f"rgen:edit_field:{tid}:done_msg")],
            [InlineKeyboardButton(text="« Back", callback_data="rgen:edit:0")],
        ]
    )
    await callback.message.edit_text(
        f"✏️ Editing: <b>{template['title']}</b>\n\nChoose a field to edit:",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(
    lambda c: c.data and c.data.startswith("rgen:edit_field:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rgen_edit_field_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":", 3)
    tid, field = parts[2], parts[3]
    await state.set_state(EditReport.new_value)
    await state.update_data(edit_tid=tid, edit_field=field)

    field_labels = {
        "title": "Title",
        "prompt_msg": "Prompt message",
        "invalid_msg": "Invalid message",
        "done_msg": "Done message",
    }
    await callback.message.edit_text(
        f"✏️ Send the new value for <b>{field_labels.get(field, field)}</b>:"
    )
    await callback.answer()


@router.message(EditReport.new_value, F.chat.id == settings.ADMIN_GROUP_ID)
async def rgen_edit_save(msg: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    tid = data["edit_tid"]
    field = data["edit_field"]
    new_value = msg.text.strip()
    if await update_template(tid, {field: new_value}):
        await msg.answer(f"✅ Field <b>{field}</b> updated.")
    else:
        await msg.answer("❌ Update failed.")


# ── Back button ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "rgen:back", F.message.chat.id == settings.ADMIN_GROUP_ID)
async def rgen_back(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🛠 <b>Report Link Generator</b>\n\nChoose an action:",
        reply_markup=_reportgen_main_kb(),
    )
    await callback.answer()


# ── User: Proceed / Cancel report ────────────────────────────────────────────

@router.callback_query(lambda c: c.data and c.data.startswith("rpt_proceed:"))
async def rpt_proceed(callback: CallbackQuery) -> None:
    tid = callback.data.split(":", 1)[1]
    user = callback.from_user

    template = await get_template(tid)
    if not template:
        await callback.answer("❌ This report link no longer exists.", show_alert=True)
        return

    # Anti-spam: check existing pending state
    state = await get_report_state(user.id, tid)
    if state and state["status"] == "pending":
        await callback.answer("⏳ You already have a pending report. Wait for admin resolution.", show_alert=True)
        return

    await create_report_state(user.id, tid)

    # Fetch user info for admin message
    user_doc = await get_user(user.id)
    uname = f"@{user.username}" if user.username else f"ID: <code>{user.id}</code>"

    try:
        sent = await callback.bot.send_message(
            chat_id=settings.ADMIN_GROUP_ID,
            text=(
                f"🚨 <b>New Report</b>\n\n"
                f"{template['prompt_msg']}\n\n"
                f"<b>Reported by:</b> {uname} (<code>{user.id}</code>)"
            ),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Done",
                            callback_data=f"rpt_admin:done:{user.id}:{tid}",
                        ),
                        InlineKeyboardButton(
                            text="❌ Invalid",
                            callback_data=f"rpt_admin:invalid:{user.id}:{tid}",
                        ),
                    ]
                ]
            ),
        )
        await save_report_admin_msg(user.id, tid, sent.message_id)
    except Exception as exc:
        logger.error("Failed to send report to admin group: %s", exc)
        await callback.answer("❌ Failed to submit report. Please try again.", show_alert=True)
        return

    await callback.message.edit_text(
        "✅ <b>Report submitted!</b>\n\nAdmins have been notified. "
        "You will receive a message once it is resolved."
    )
    await callback.answer("Report sent!")


@router.callback_query(lambda c: c.data == "rpt_cancel")
async def rpt_cancel(callback: CallbackQuery) -> None:
    await callback.message.edit_text("❌ Report cancelled.")
    await callback.answer()


# ── Admin: Done / Invalid buttons on report messages ─────────────────────────

@router.callback_query(
    lambda c: c.data and c.data.startswith("rpt_admin:"),
    F.message.chat.id == settings.ADMIN_GROUP_ID,
)
async def rpt_admin_action(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    # rpt_admin:<action>:<user_id>:<template_id>
    if len(parts) != 4:
        await callback.answer("Malformed callback data.", show_alert=True)
        return

    _, action, user_id_str, tid = parts
    user_id = int(user_id_str)

    template = await get_template(tid)
    if not template:
        await callback.answer("Template no longer exists.", show_alert=True)
        return

    state = await get_report_state(user_id, tid)
    if not state or state["status"] != "pending":
        await callback.answer("This report has already been resolved.", show_alert=True)
        return

    if action == "done":
        reply_text = template["done_msg"]
        status = "done"
        label = "✅ Done"
    else:
        reply_text = template["invalid_msg"]
        status = "invalid"
        label = "❌ Invalid"

    await resolve_report_state(user_id, tid, status)

    try:
        await callback.bot.send_message(chat_id=user_id, text=reply_text)
    except Exception as exc:
        logger.warning("Could not notify user %d: %s", user_id, exc)

    # Update the admin message to show resolution
    admin_name = callback.from_user.first_name
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.edit_text(
            callback.message.text + f"\n\n<b>Resolved as {label} by {admin_name}</b>"
        )
    except Exception:
        pass

    await callback.answer(f"Marked as {label}")


# ── Pagination helper ─────────────────────────────────────────────────────────

def _pagination_nav(
    prefix: str, page: int, total: int
) -> list[InlineKeyboardButton] | None:
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"{prefix}:{page - 1}"))
    if (page + 1) * PAGE_SIZE < total:
        buttons.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"{prefix}:{page + 1}"))
    return buttons if buttons else None
