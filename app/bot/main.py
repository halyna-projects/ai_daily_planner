from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from app.bot.handlers import router
from app.bot.scheduler import run_reminder_loop
from app.bot.wizard import router as wizard_router
from app.config import get_settings
from app.db import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set (check your .env file)")

    await init_db()

    bot = Bot(token=settings.telegram_bot_token)
    # Populates Telegram's native "Menu" button next to the message box --
    # a persistent, always-visible list of commands, so there's no need to
    # remember or scroll up to find /today, /tasks etc.
    await bot.set_my_commands([
        BotCommand(command="new", description="Нова задача (покроково)"),
        BotCommand(command="today", description="Задачі на сьогодні"),
        BotCommand(command="tasks", description="Усі активні задачі"),
        BotCommand(command="help", description="Довідка"),
    ])

    dispatcher = Dispatcher()
    # The wizard router must come first: its handlers are state-gated (only
    # fire mid-/new-flow), while handlers.router's F.text catch-all matches
    # any text unconditionally and would otherwise swallow wizard input.
    dispatcher.include_router(wizard_router)
    dispatcher.include_router(router)

    use_ai = "yes" if settings.anthropic_api_key else "no (fallback parser)"
    logger.info("AI daily planner bot started, live AI=%s", use_ai)

    reminder_task = asyncio.create_task(run_reminder_loop(bot))
    try:
        await dispatcher.start_polling(bot)
    finally:
        reminder_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
