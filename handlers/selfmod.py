"""Хендлер самомодификации — бот может добавлять/удалять/просматривать плагины."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.history import history
from core.registry import registry
from services.llm import generate_plugin_code, generate_chat_reply

logger = logging.getLogger(__name__)

router = Router()


@router.message(Command("plugins"))
async def list_plugins_handler(message: Message) -> None:
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
    """Обработать запрос самомодификации. Ответы — через единую личность."""
    request = action or (message.text or "")

    # Бот отвечает естественно что берётся за дело
    thinking_reply = await generate_chat_reply(
        f"[СИСТЕМНОЕ СОБЫТИЕ: пользователь попросил тебя измениться. "
        f"Его запрос: «{request}». Ты сейчас начинаешь генерировать код плагина. "
        f"Коротко ответь что берёшься за это, своими словами, в своём стиле. "
        f"Не пиши шаблонно.]",
        history.get_messages(),
    )
    await message.answer(thinking_reply)
    history.add_assistant(thinking_reply)

    try:
        code = await generate_plugin_code(request)
        logger.info("Generated plugin code:\n%s", code)
        registry.load_from_code("_pending", code)

        # Бот сообщает об успехе естественно
        result_reply = await generate_chat_reply(
            f"[СИСТЕМНОЕ СОБЫТИЕ: ты только что успешно создал новый плагин! "
            f"Запрос был: «{request}». Плагин уже зарегистрирован и работает. "
            f"Расскажи об этом пользователю своими словами, можешь предложить попробовать.]",
            history.get_messages(),
        )
        await message.answer(result_reply)
        history.add_assistant(result_reply)

    except Exception as e:
        logger.exception("Failed to generate/register plugin")
        # Бот сообщает об ошибке естественно
        error_reply = await generate_chat_reply(
            f"[СИСТЕМНОЕ СОБЫТИЕ: ты попытался создать плагин по запросу «{request}», "
            f"но произошла ошибка: {e}. Расскажи пользователю об этом по-человечески. "
            f"Можешь предложить переформулировать или помочь разобраться.]",
            history.get_messages(),
        )
        await message.answer(error_reply)
        history.add_assistant(error_reply)
