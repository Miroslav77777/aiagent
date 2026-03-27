"""Хендлер самомодификации — бот может добавлять/удалять/просматривать плагины."""

import logging
import re

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.registry import registry
from services.llm import generate_plugin_code

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("plugins"))
async def list_plugins_handler(message: Message) -> None:
    """Показать список активных динамических плагинов."""
    plugins = registry.list_plugins()
    if not plugins:
        await message.answer("Пока нет ни одного динамического плагина.")
        return
    lines = ["Активные плагины:\n"]
    for p in plugins:
        lines.append(
            f"  {p['trigger_value']} — {p['description']} [{p['trigger_type']}]"
        )
    await message.answer("\n".join(lines))


@router.message(Command("remove_plugin"))
async def remove_plugin_handler(message: Message) -> None:
    """Удалить плагин: /remove_plugin имя_плагина"""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("Использование: /remove_plugin имя_плагина")
        return
    name = parts[1].strip()
    if registry.unregister(name):
        await message.answer(f"Плагин «{name}» удалён.")
    else:
        await message.answer(f"Плагин «{name}» не найден.")


async def handle_selfmod(message: Message, action: str) -> None:
    """Обработать запрос самомодификации. action — описание из роутера."""
    request = action or (message.text or "")
    await message.answer("Генерирую новый плагин...")

    try:
        code = await generate_plugin_code(request)
        logger.info("Generated plugin code:\n%s", code)

        registry.load_from_code("_pending", code)
        await message.answer(
            "Готово, плагин добавлен и уже работает!\n"
            "Попробуй его использовать."
        )
    except Exception as e:
        logger.exception("Failed to generate/register plugin")
        await message.answer(
            f"Не удалось создать плагин: {e}\n"
            "Попробуй описать задачу подробнее."
        )
