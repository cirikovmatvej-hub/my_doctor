import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database.db import init_db
from handlers import consultation, followup, history, profile, start
from handlers import bad_advisor, family, tracker, diary


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    await init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Router order matters: more specific routers first
    dp.include_router(start.router)
    dp.include_router(profile.router)
    dp.include_router(family.router)
    dp.include_router(followup.router)
    dp.include_router(bad_advisor.router)
    dp.include_router(tracker.router)
    dp.include_router(diary.router)
    dp.include_router(consultation.router)
    dp.include_router(history.router)

    logging.info("Бот запущен ✅ (v2)")

    # All background loops run in parallel with the polling
    await asyncio.gather(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
        followup.follow_up_loop(bot),
        tracker.reminder_loop(bot),
    )


if __name__ == "__main__":
    asyncio.run(main())
