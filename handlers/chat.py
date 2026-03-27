"""Хендлер чата — catch-all для всех сообщений."""

import logging
import re

from aiogram import Router
from aiogram.types import Message

from core.context import PluginContext
from core.registry import registry
from handlers.selfmod import handle_selfmod
from handlers.weather import handle_weather
from services.llm import route_user_message, generate_chat_reply
from services.weather_api import WeatherError
import services.llm as llm_service

logger = logging.getLogger(__name__)

router = Router()


def _build_context(message: Message) -> PluginContext:
    return PluginContext(
        message=message,
        services={"llm": llm_service},
    )


@router.message()
async def main_handler(message: Message) -> None:
    """Главный catch-all: плагины -> LLM-роутер (selfmod/weather/chat)."""
    user_text = (message.text or "").strip()
    if not user_text:
        await message.answer("Я пока умею работать только с текстовыми сообщениями.")
        return

    # 1. Динамические плагины — проверяем первыми
    ctx = _build_context(message)
    if await registry.try_dispatch(ctx):
        return

    # 2. LLM-роутер решает что делать
    try:
        route = await route_user_message(user_text)

        # Фоллбэк: слово «погода» в тексте
        if route.get("intent") == "chat" and re.search(
            r"\bпогод", user_text, re.IGNORECASE
        ):
            route["intent"] = "weather"

        intent = route["intent"]

        if intent == "selfmod":
            action = route.get("selfmod_action") or user_text
            await handle_selfmod(message, action)
            return

        if intent == "weather":
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
