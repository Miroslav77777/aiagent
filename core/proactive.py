"""Фоновая задача: бот сам пишет пользователю когда ему есть что сказать."""

import asyncio
import logging
import random

from aiogram import Bot

from config import ADMIN_USER_ID
from core.history import history
from services.llm import maybe_generate_proactive

logger = logging.getLogger(__name__)

# Интервал между проверками (в секундах)
MIN_INTERVAL = 3 * 60    # 3 минуты
MAX_INTERVAL = 15 * 60   # 15 минут

# Не писать если последнее сообщение было слишком давно (нет активного разговора)
MIN_HISTORY_LEN = 4  # хотя бы 4 сообщения в истории


async def proactive_loop(bot: Bot) -> None:
    """Бесконечный цикл: периодически решает, написать ли пользователю."""
    # Ждём пару минут после старта чтобы не спамить сразу
    await asyncio.sleep(120)

    while True:
        interval = random.randint(MIN_INTERVAL, MAX_INTERVAL)
        await asyncio.sleep(interval)

        try:
            # Не пишем если мало истории (бот только запустился / нет разговора)
            if len(history) < MIN_HISTORY_LEN:
                continue

            msg = await maybe_generate_proactive(history.get_messages())
            if msg:
                await bot.send_message(ADMIN_USER_ID, msg)
                history.add_assistant(msg)
                logger.info("Proactive message sent: %s", msg[:80])

        except Exception:
            logger.exception("Error in proactive loop")
