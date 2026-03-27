"""Точка входа — запуск бота."""

import asyncio
import logging

from config import ADMIN_USER_ID
from core.bot import bot, dp
from core.middleware import AdminOnlyMiddleware
from core.proactive import proactive_loop
from core.registry import registry

from handlers.start import router as start_router
from handlers.selfmod import router as selfmod_router
from handlers.chat import router as chat_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    count = registry.load_all_from_disk()
    if count:
        logger.info("Loaded %d plugin(s) from disk", count)

    dp.message.middleware(AdminOnlyMiddleware())
    logger.info("Access restricted to user_id=%d", ADMIN_USER_ID)

    dp.include_router(start_router)
    dp.include_router(selfmod_router)
    dp.include_router(chat_router)

    # Фоновая задача: бот сам пишет когда есть что сказать
    asyncio.create_task(proactive_loop(bot))
    logger.info("Proactive loop started")

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
