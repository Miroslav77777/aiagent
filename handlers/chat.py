"""Хендлер чата — фоллбэк для обычных сообщений."""

import logging
import re

from aiogram import Router
from aiogram.types import Message

from core.context import PluginContext
from core.registry import registry
from handlers.selfmod import is_selfmod_request, handle_selfmod_natural
from handlers.weather import handle_weather
from services.llm import route_user_message, generate_chat_reply
from services.weather_api import WeatherError
import services.llm as llm_service

logger = logging.getLogger(__name__)

router = Router()


def _build_context(message: Message) -> PluginContext:
    """Собрать контекст для динамических плагинов."""
    return PluginContext(
        message=message,
        services={
            "llm": llm_service,
        },
    )


@router.message()
async def main_handler(message: Message) -> None:
    """Главный catch-all хендлер: плагины -> selfmod -> погода -> чат."""
    user_text = (message.text or "").strip()
    if not user_text:
        await message.answer("Я пока умею работать только с текстовыми сообщениями.")
        return

    # 1. Проверяем динамические плагины
    ctx = _build_context(message)
    if await registry.try_dispatch(ctx):
        return

    # 2. Проверяем запрос на самомодификацию
    if await is_selfmod_request(user_text):
        await handle_selfmod_natural(message)
        return

    # 3. Роутинг через LLM
    try:
        route = await route_user_message(user_text)

        # Фоллбэк: слово «погода» в тексте
        if route.get("intent") == "chat" and re.search(
            r"\bпогод", user_text, re.IGNORECASE
        ):
            route["intent"] = "weather"

        if route["intent"] == "weather":
            await handle_weather(message, route)
            return

        # Обычный чат
        reply = await generate_chat_reply(user_text)
        await message.answer(reply)

    except WeatherError as e:
        await message.answer(f"Не получилось получить погоду: {e}")
    except Exception:
        logger.exception("Ошибка в main_handler")
        await message.answer("Произошла ошибка при обработке запроса.")
