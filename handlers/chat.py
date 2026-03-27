"""Хендлер чата — единая точка входа для всех текстовых сообщений."""

import logging
import re

from aiogram import Router
from aiogram.types import Message

from core.context import PluginContext
from core.history import history
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

    # Записываем сообщение пользователя в историю
    history.add_user(user_text)

    # 2. LLM-роутер решает что делать (с контекстом истории)
    try:
        route = await route_user_message(user_text, history.get_messages())

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
            # Записываем факт получения погоды в историю
            history.add_assistant("[Отправил информацию о погоде]")
            return

        # Обычный чат — с полной историей
        reply = await generate_chat_reply(user_text, history.get_messages())
        await message.answer(reply)
        history.add_assistant(reply)

    except WeatherError as e:
        error_msg = f"Не получилось получить погоду: {e}"
        await message.answer(error_msg)
        history.add_assistant(error_msg)
    except Exception:
        logger.exception("Ошибка в main_handler")
        await message.answer("Произошла ошибка при обработке запроса.")
        history.add_assistant("[Произошла внутренняя ошибка]")
