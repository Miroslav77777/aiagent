"""Хендлер самомодификации — генерация, тестирование, автоисправление плагинов."""

import logging
import traceback

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.history import history
from core.registry import registry
from services.llm import generate_plugin_code, fix_plugin_code, generate_chat_reply

logger = logging.getLogger(__name__)

router = Router()

MAX_RETRIES = 3


@router.message(Command("plugins"))
async def list_plugins_handler(message: Message) -> None:
    plugins = registry.list_plugins()
    if not plugins:
        await message.answer("Нет активных плагинов.")
        return
    lines = ["Плагины:\n"]
    for p in plugins:
        lines.append(
            f"  {p['trigger_value']} — {p['description']} [{p['trigger_type']}]"
        )
    await message.answer("\n".join(lines))


@router.message(Command("remove_plugin"))
async def remove_plugin_handler(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await message.answer("/remove_plugin имя_плагина")
        return
    name = parts[1].strip()
    if registry.unregister(name):
        await message.answer(f"Плагин «{name}» удалён.")
    else:
        await message.answer(f"Плагин «{name}» не найден.")


async def handle_selfmod(message: Message, action: str) -> None:
    """Генерация плагина с автотестированием и retry."""
    request = action or (message.text or "")

    # Короткое уведомление через LLM (в стиле бота)
    note = await generate_chat_reply(
        f"[СИСТЕМА: пользователь хочет: «{request}». Ты начинаешь писать код. "
        f"Скажи об этом в 1 предложение, без пафоса.]",
        history.get_messages(),
    )
    await message.answer(note)
    history.add_assistant(note)

    code = None
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if code is None:
                # Первая генерация
                code = await generate_plugin_code(request)
            else:
                # Починка после ошибки
                await message.answer(f"Попытка {attempt}: исправляю...")
                code = await fix_plugin_code(code, last_error, request)

            logger.info("Plugin code (attempt %d):\n%s", attempt, code)

            # Тест: компиляция
            compile(code, "<plugin_test>", "exec")

            # Тест: exec в изолированном namespace
            test_ns = registry._make_namespace()
            exec(compile(code, "<plugin_test>", "exec"), test_ns)

            # Проверяем что всё определено
            if not test_ns.get("PLUGIN_NAME"):
                raise ValueError("Нет PLUGIN_NAME")
            if not callable(test_ns.get("handle")):
                raise ValueError("Нет async def handle(ctx)")

            # Всё ок — регистрируем
            registry.load_from_code("_pending", code)

            result = await generate_chat_reply(
                f"[СИСТЕМА: плагин по запросу «{request}» готов и работает. "
                f"Попыток: {attempt}. Скажи коротко.]",
                history.get_messages(),
            )
            await message.answer(result)
            history.add_assistant(result)
            return

        except Exception as e:
            last_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            logger.warning("Plugin attempt %d failed: %s", attempt, e)

    # Все попытки провалились
    fail_msg = await generate_chat_reply(
        f"[СИСТЕМА: не получилось создать плагин «{request}» за {MAX_RETRIES} попыток. "
        f"Последняя ошибка: {last_error}. Скажи об этом коротко и честно.]",
        history.get_messages(),
    )
    await message.answer(fail_msg)
    history.add_assistant(fail_msg)
