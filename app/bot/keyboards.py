from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def reminder_callback_data(task_id: int, action: str) -> str:
    return f"task:{task_id}:{action}"


def parse_reminder_callback(data: str) -> tuple[int, str]:
    _, task_id, action = data.split(":")
    return int(task_id), action


def reminder_keyboard(task_id: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text="✅ Виконано", callback_data=reminder_callback_data(task_id, "done")),
        InlineKeyboardButton(text="⏳ Ще ні", callback_data=reminder_callback_data(task_id, "not_yet")),
        InlineKeyboardButton(text="🔁 Перенести", callback_data=reminder_callback_data(task_id, "snooze")),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])
