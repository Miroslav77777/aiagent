"""Обработчик действий: плагины, скрипты, редактирование кода."""

import logging
import traceback

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from core.context import PluginContext
from core.history import history
from core.registry import registry, read_bot_file
from services.llm import (
    plan_action, generate_code, fix_code,
    generate_chat_reply,
)

logger = logging.getLogger(__name__)

router = Router()

MAX_RETRIES = 3


@router.message(Command("plugins"))
async def list_plugins_handler(message: Message) -> None:
    plugins = registry.list_plugins()
    if not plugins:
        await message.answer("Нет активных плагинов.")
        return
    lines = ["Плагины:"]
    for p in plugins:
        lines.append(f"  {p['trigger_value']} — {p['description']}")
    await message.answer("\n".join(lines))


@router.message(Command("remove_plugin"))
async def remove_plugin_handler(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("/remove_plugin имя")
        return
    name = parts[1].strip()
    if registry.unregister(name):
        await message.answer(f"Плагин «{name}» удалён.")
    else:
        await message.answer(f"«{name}» не найден.")


async def handle_action(message: Message, description: str, action_type: str | None, ctx: PluginContext) -> None:
    """Главный обработчик действий: план → код → тест → retry."""
    task = description or (message.text or "")

    # 1. Планирование
    await message.answer("Думаю...")
    try:
        plan = await plan_action(task, history.get_messages())
    except Exception:
        logger.exception("Planning failed")
        plan = {"plan": task, "type": action_type or "script", "needs_packages": [], "files_to_read": []}

    resolved_type = plan.get("type", action_type or "script")
    logger.info("Plan: type=%s, plan=%s", resolved_type, plan.get("plan", ""))

    # 2. Читаем файлы если план требует
    context_files = {}
    for fpath in plan.get("files_to_read", []):
        try:
            context_files[fpath] = read_bot_file(fpath)
        except Exception as e:
            logger.warning("Cannot read %s: %s", fpath, e)

    # 3. Генерация + тестирование + retry
    code = None
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if code is None:
                code = await generate_code(task, plan, context_files)
            else:
                if attempt > 1:
                    await message.answer(f"Исправляю (попытка {attempt})...")
                code = await fix_code(code, last_error, task)

            logger.info("Code attempt %d:\n%s", attempt, code)

            # Тестируем компиляцию и exec
            test_ns = registry.test_code(code)

            if resolved_type == "script":
                # Одноразовый скрипт — выполняем
                if not callable(test_ns.get("run")):
                    raise ValueError("Скрипт должен определить async def run(ctx)")
                result = await registry.run_script(code, ctx)
                if result:
                    await message.answer(result)
                    history.add_assistant(result)
                else:
                    await message.answer("Готово.")
                    history.add_assistant("[Скрипт выполнен]")
                return

            elif resolved_type == "edit_code":
                # Редактирование файлов — скрипт который пишет файлы
                if callable(test_ns.get("run")):
                    result = await registry.run_script(code, ctx)
                    msg = result or "Код изменён."
                    await message.answer(msg)
                    history.add_assistant(msg)
                else:
                    raise ValueError("edit_code должен определить async def run(ctx)")
                return

            else:
                # Плагин — регистрируем
                if not test_ns.get("PLUGIN_NAME"):
                    raise ValueError("Нет PLUGIN_NAME")
                if not callable(test_ns.get("handle")):
                    raise ValueError("Нет async def handle(ctx)")

                # Удаляем старый плагин с таким же именем если есть
                plugin_name = test_ns["PLUGIN_NAME"]
                if plugin_name in registry.plugins:
                    registry.unregister(plugin_name)

                registry.load_from_code("_pending", code)

                note = await generate_chat_reply(
                    f"[СИСТЕМА: создан плагин «{plugin_name}» по запросу «{task}». "
                    f"Попыток: {attempt}. Скажи 1 предложение.]",
                    history.get_messages(),
                )
                await message.answer(note)
                history.add_assistant(note)
                return

        except Exception as e:
            last_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-500:]}"
            logger.warning("Attempt %d failed: %s", attempt, e)
            code_for_fix = code  # сохраняем для следующей итерации

    # Все попытки провалились
    fail = await generate_chat_reply(
        f"[СИСТЕМА: не удалось выполнить «{task}» за {MAX_RETRIES} попыток. "
        f"Ошибка: {last_error[:300]}. Скажи коротко.]",
        history.get_messages(),
    )
    await message.answer(fail)
    history.add_assistant(fail)
