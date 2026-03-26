"""Точка входа — запуск бота."""

import asyncio
import logging

from core.bot import bot, dp
from core.registry import registry

# Импортируем роутеры хендлеров
from handlers.start import router as start_router
from handlers.selfmod import router as selfmod_router
from handlers.chat import router as chat_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    # Загружаем сохранённые плагины с диска
    count = registry.load_all_from_disk()
    if count:
        logger.info("Loaded %d plugin(s) from disk", count)

    # Подключаем роутеры (порядок важен!)
    # 1. /start — приоритет
    # 2. /plugins, /remove_plugin, /add — команды самомодификации
    # 3. catch-all — плагины -> selfmod -> погода -> чат
    dp.include_router(start_router)
    dp.include_router(selfmod_router)
    dp.include_router(chat_router)

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
