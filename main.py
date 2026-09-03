import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from config import BOT_TOKEN
from database.db import init_db
from database.fsm_storage import SQLiteStorage
from handlers import consultation, followup, history, profile, start
from handlers import appointment, bad_advisor, family, tracker, diary


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    await init_db()

    # SQLite-backed, not aiogram's MemoryStorage — a deploy restart used to
    # silently wipe every in-progress conversation (verified live: mid-
    # consultation history vanished after a restart, model then acted like
    # it was a brand new chat). Same DB file/connection pattern as the rest
    # of the app, so this doesn't need any new infrastructure.
    fsm_storage = SQLiteStorage()
    await fsm_storage.init()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=fsm_storage)

    # Registering at least one command is what makes Telegram show the blue
    # "Menu" pill next to the message input — without this call it never
    # appears, regardless of whether a command handler exists.
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
    ])

    # Router order matters: more specific routers first
    dp.include_router(start.router)
    dp.include_router(profile.router)
    dp.include_router(family.router)
    dp.include_router(followup.router)
    dp.include_router(appointment.router)
    dp.include_router(bad_advisor.router)
    dp.include_router(tracker.router)
    dp.include_router(diary.router)
    dp.include_router(consultation.router)
    dp.include_router(history.router)

    logging.info("Бот запущен ✅ (v2)")

    # Background loops run alongside polling. They must be cancelled
    # explicitly once polling stops (e.g. on SIGTERM/SIGINT) — otherwise the
    # process hangs until systemd's stop timeout forces a SIGKILL, since the
    # loops sit in asyncio.sleep() and asyncio.gather() would wait for them.
    background_tasks = [
        asyncio.create_task(followup.follow_up_loop(bot)),
        asyncio.create_task(tracker.reminder_loop(bot)),
        asyncio.create_task(appointment.appointment_loop(bot)),
    ]

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
