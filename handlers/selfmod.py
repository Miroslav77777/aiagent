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


@router.message(Command("add"))
async def add_plugin_handler(message: Message) -> None:
    """Добавить плагин по описанию: /add команда /dice — бросает кубик"""
    text = (message.text or "").strip()
    # Убираем /add
    request = re.sub(r"^/add\s*", "", text).strip()
    if not request:
        await message.answer(
            "Опиши, что нужно добавить. Например:\n"
            "/add команда /dice — бросает кубик от 1 до 6"
        )
        return
    await _generate_and_register(message, request)


async def is_selfmod_request(text: str) -> bool:
    """Проверить, похож ли текст на запрос самомодификации."""
    lower = text.lower()
    triggers = [
        "добавь команду", "создай команду", "сделай команду",
        "добавь функцию", "создай функцию", "сделай функцию",
        "добавь плагин", "создай плагин",
        "добавь хендлер", "создай хендлер",
        "научись", "добавь возможность",
    ]
    return any(t in lower for t in triggers)


async def handle_selfmod_natural(message: Message) -> None:
    """Обработать запрос самомодификации в свободной форме."""
    await _generate_and_register(message, message.text or "")


async def _generate_and_register(message: Message, request: str) -> None:
    """Общая логика: генерация кода плагина и его регистрация."""
    await message.answer("Генерирую новый плагин...")

    try:
        code = await generate_plugin_code(request)
        logger.info("Generated plugin code:\n%s", code)

        registry.load_from_code("_pending", code)
        await message.answer(
            f"Плагин добавлен и уже работает!\n"
            f"Попробуй его использовать."
        )
    except Exception as e:
        logger.exception("Failed to generate/register plugin")
        await message.answer(
            f"Не удалось создать плагин: {e}\n"
            "Попробуй описать задачу подробнее."
        )
