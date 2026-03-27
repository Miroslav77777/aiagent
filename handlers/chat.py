"""Главный catch-all хендлер."""

import logging
import re

from aiogram import Router
from aiogram.types import Message

from core.context import PluginContext
from core.history import history
from core.registry import registry
from handlers.selfmod import handle_action
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
    user_text = (message.text or "").strip()
    if not user_text:
        await message.answer("Только текст.")
        return

    # 1. Динамические плагины
    ctx = _build_context(message)
    if await registry.try_dispatch(ctx):
        return

    history.add_user(user_text)

    # 2. LLM-роутер
    try:
        route = await route_user_message(user_text, history.get_messages())

        # Фоллбэк: «погода» в тексте
        if route.get("intent") == "chat" and re.search(r"\bпогод", user_text, re.IGNORECASE):
            route["intent"] = "weather"

        intent = route["intent"]

        if intent == "action":
            desc = route.get("action_description") or user_text
            atype = route.get("action_type")
            await handle_action(message, desc, atype, ctx)
            return

        if intent == "weather":
            await handle_weather(message, route)
            history.add_assistant("[Отправил погоду]")
            return

        # Чат
        reply = await generate_chat_reply(user_text, history.get_messages())
        await message.answer(reply)
        history.add_assistant(reply)

    except WeatherError as e:
        msg = f"Не получилось: {e}"
        await message.answer(msg)
        history.add_assistant(msg)
    except Exception:
        logger.exception("Ошибка в main_handler")
        await message.answer("Ошибка.")
        history.add_assistant("[Ошибка]")
