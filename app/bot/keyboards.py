from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def reminder_callback_data(task_id: int, action: str) -> str:
    return f"task:{task_id}:{action}"


def parse_reminder_callback(data: str) -> tuple[int, str]:
    _, task_id, action = data.split(":")
    return int(task_id), action


def reminder_keyboard(task_id: int) -> InlineKeyboardMarkup:
    row1 = [
        InlineKeyboardButton(text="✅ Виконано", callback_data=reminder_callback_data(task_id, "done")),
        InlineKeyboardButton(text="⏳ Ще ні", callback_data=reminder_callback_data(task_id, "not_yet")),
        InlineKeyboardButton(text="🔁 Перенести", callback_data=reminder_callback_data(task_id, "snooze")),
    ]
    row2 = [
        InlineKeyboardButton(text="🗑 Видалити", callback_data=reminder_callback_data(task_id, "delete")),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


def delete_only_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Used in the /tasks list -- a quick one-tap undo for an older
    mistake (no real "edit" yet: delete and resend the corrected text)."""

    buttons = [
        InlineKeyboardButton(text="🗑 Видалити", callback_data=reminder_callback_data(task_id, "delete")),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def task_row_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Used wherever an existing task is listed (/today, /tasks): edit
    re-runs it through the same date/cadence questions as /new, in place,
    instead of delete-and-recreate. "Нова задача" is repeated on every
    row (not just once at the top) so a long list never means scrolling
    back up to start the next task."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редагувати", callback_data=f"edit:{task_id}")],
            [InlineKeyboardButton(text="🗑 Видалити", callback_data=reminder_callback_data(task_id, "delete"))],
            [InlineKeyboardButton(text="➕ Нова задача", callback_data="wiz:new")],
        ]
    )


def confirmation_keyboard(task_id: int) -> InlineKeyboardMarkup:
    """Shown right after a task is created: delete (undo a typo), a
    one-tap way to start the next task's /new wizard, and a way to see
    everything recorded so far -- all without scrolling up in the chat to
    find and retype a command (there's also Telegram's own Menu button
    next to the message box, listing all commands, set via
    bot.set_my_commands in app/bot/main.py)."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Видалити", callback_data=reminder_callback_data(task_id, "delete"))],
            [InlineKeyboardButton(text="➕ Нова задача (покроково)", callback_data="wiz:new")],
            [InlineKeyboardButton(text="📋 Усі задачі", callback_data="menu:tasks")],
        ]
    )


def clarify_due_date_keyboard(labels: list[str]) -> InlineKeyboardMarkup:
    """One button per date/time candidate found in an ambiguous message,
    asked instead of silently guessing which one is the actual reminder."""

    buttons = [
        [InlineKeyboardButton(text=label, callback_data=f"clarify:{i}")]
        for i, label in enumerate(labels)
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def parse_clarify_callback(data: str) -> int:
    return int(data.split(":")[1])


def clear_all_confirm_keyboard() -> InlineKeyboardMarkup:
    """A destructive, irreversible bulk delete -- needs an explicit
    confirm tap, not a single accidental one."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚠️ Так, видалити все", callback_data="clear:confirm")],
            [InlineKeyboardButton(text="Скасувати", callback_data="clear:cancel")],
        ]
    )
