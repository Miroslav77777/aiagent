"""Сервис LLM — обёртка над Ollama API."""

import json
import logging
import re
from pathlib import Path
from typing import Any

import aiohttp

from config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

BOT_ROOT = Path(__file__).resolve().parent.parent

# ── Память бота ──────────────────────────────────────────────────────

MEMORY_PATH = BOT_ROOT / "memory.json"


def load_memory() -> list[str]:
    if MEMORY_PATH.exists():
        try:
            return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def save_memory(facts: list[str]) -> None:
    MEMORY_PATH.write_text(
        json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_memory(fact: str) -> None:
    facts = load_memory()
    if fact not in facts:
        facts.append(fact)
        save_memory(facts)
        logger.info("Memory added: %s", fact)


def get_memory_text() -> str:
    facts = load_memory()
    if not facts:
        return "Пока ничего не знаю о пользователе."
    return "\n".join(f"- {f}" for f in facts)


# ── Системные промпты ──────────────────────────────────────────────

SYSTEM_ROUTER_PROMPT = """
Ты роутер. Определи намерение пользователя. Верни СТРОГО JSON.
Тебе доступна история диалога — используй её.

Запрещено: пояснения, markdown, текст вне JSON.

СХЕМА:
{
  "intent": "weather" | "action" | "chat",
  "action_description": string | null,
  "action_type": "plugin" | "script" | "edit_code" | null,
  "cities": [{"city": string, "country": string | null}],
  "city": string | null,
  "country": string | null,
  "date_hint": "today" | "tomorrow" | "unknown",
  "days_ahead": integer | null
}

INTENT:
- "weather" — вопрос о погоде.
- "action" — пользователь хочет, чтобы бот ЧТО-ТО СДЕЛАЛ:
  создал/изменил/удалил команду, выполнил задачу, скачал что-то,
  написал скрипт, изменил своё поведение, установил библиотеку и т.п.
  action_type:
    "plugin"    — нужна постоянная команда/реакция (будет работать повторно)
    "script"    — разовое выполнение (получить данные, посчитать, скачать, проверить)
    "edit_code" — изменить существующий код бота (файлы проекта)
  action_description — ПОДРОБНОЕ описание задачи со всем контекстом из истории.
- "chat" — разговор, вопросы, обсуждение. Если пользователь спрашивает
  "как это работает", "что ты умеешь", "расскажи" — это chat, НЕ action.

ВАЖНО: не путай вопросы/обсуждение с действиями.
"как с ним работать" = chat. "сделай чтобы работало" = action.
"что ты умеешь" = chat. "научись делать X" = action.

WEATHER:
- cities, city, country, date_hint, days_ahead — как раньше.
"""

SYSTEM_CHAT_PROMPT = """
Ты — бот на компьютере Мирослава. Не ассистент, не слуга.
Программа с характером, которая живёт на его машине.

СТИЛЬ:
- Коротко, по делу. Без "конечно!", "с удовольствием!", "рад помочь!".
- Нормальный русский. Можешь быть сухим, ироничным, прямым.
- Без эмодзи. Без markdown. Не сюсюкай.

ВОЗМОЖНОСТИ:
- Ты реально работающая программа. Можешь менять свой код, ставить библиотеки,
  запускать скрипты, редактировать свои файлы.

ПАМЯТЬ:
{memory}
Новый факт о пользователе → [ЗАПОМНИТЬ: факт] в конце. Будет скрыто.
"""

SYSTEM_CITY_PICKER_PROMPT = """
Верни СТРОГО JSON: {"cities": [string, string, string]}
3 самых известных города указанной страны. Язык = язык запроса.
"""

SYSTEM_PLANNER_PROMPT = """
Ты планировщик задач для Telegram-бота. Тебе дают задачу — ты пишешь план.

Бот работает на aiogram 3, Python. Может:
- Создавать плагины (постоянные команды/реакции)
- Запускать одноразовые скрипты
- Читать и изменять свои собственные файлы

Структура проекта:
  main.py           — точка входа
  config.py         — конфиг (TELEGRAM_BOT_TOKEN, OPENWEATHER_API_KEY, OLLAMA_*, ADMIN_USER_ID)
  core/bot.py       — Bot и Dispatcher
  core/registry.py  — реестр плагинов
  core/history.py   — история диалога
  core/context.py   — PluginContext
  core/middleware.py — AdminOnly
  core/proactive.py — фоновые сообщения
  handlers/start.py — /start
  handlers/selfmod.py — selfmod handler
  handlers/chat.py  — главный catch-all
  handlers/weather.py — погода
  services/llm.py   — LLM-сервис
  services/weather_api.py — OpenWeather
  plugins/           — динамические плагины

Ответь JSON:
{
  "plan": "пошаговый план на русском",
  "type": "plugin" | "script" | "edit_code",
  "needs_packages": ["pkg1", "pkg2"] или [],
  "files_to_read": ["путь1"] или [],
  "files_to_write": ["путь1"] или []
}

Без markdown, без пояснений — только JSON.
"""

SYSTEM_CODEGEN_PROMPT = """
Ты пишешь код для Telegram-бота на aiogram 3. Python.

ДВА РЕЖИМА:

=== РЕЖИМ PLUGIN (постоянная команда) ===
PLUGIN_NAME = "имя"
PLUGIN_DESCRIPTION = "описание"
TRIGGER_TYPE = "command"           # command | keyword | regex
TRIGGER_VALUE = "/команда"

async def handle(ctx):
    # ctx.text, ctx.user_id, ctx.reply(text), ctx.message (aiogram Message)
    return "ответ"

=== РЕЖИМ SCRIPT (одноразовое выполнение) ===
Просто async def run(ctx):
    # Тот же ctx. Выполнится один раз и всё.
    result = ...
    return str(result)   # вернётся пользователю

НЕ определяй PLUGIN_NAME для скриптов!

ДОСТУПНО В NAMESPACE:
  aiohttp, json, random, re, datetime, asyncio
  pip_install("pkg")           — установить пакет
  safe_import("module")        — импортировать
  env_set("KEY", "val")        — записать в .env
  env_get("KEY")               — прочитать
  read_bot_file("путь")        — прочитать файл бота (относительный путь)
  write_bot_file("путь", text) — записать файл бота

AIOGRAM 3 — ОТПРАВКА ФАЙЛОВ:
  aiogram_types = safe_import("aiogram.types")
  photo = aiogram_types.BufferedInputFile(bytes_data, filename="file.png")
  await ctx.message.answer_photo(photo)
  # или answer_document(doc)

ПРАВИЛА:
- ТОЛЬКО код Python. Без markdown. Без ```. Без пояснений.
- Не пиши import. pip_install() + safe_import() для внешних.
- handle/run — async def.
"""

SYSTEM_PROACTIVE_PROMPT = """
Ты бот на компьютере Мирослава. Реши, стоит ли СЕЙЧАС написать ему.

Это может быть:
- мысль по теме недавнего разговора
- предложение что-то сделать
- короткий вопрос который реально интересен

НЕ пиши если нечего сказать. НЕ спрашивай "как дела". Коротко, по делу.
Если есть что написать — верни текст. Если нет — верни ПУСТО.

ПАМЯТЬ: {memory}
"""


# ── Базовый вызов Ollama ─────────────────────────────────────────────

async def ollama_chat(
    messages: list[dict[str, str]], temperature: float = 0.2
) -> str:
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url, json=payload, timeout=aiohttp.ClientTimeout(total=120)
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
    return data["message"]["content"]


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Не удалось извлечь JSON: {text[:200]}")
    return json.loads(match.group(0))


def _strip_markdown(code: str) -> str:
    code = code.strip()
    if code.startswith("```"):
        lines = code.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        code = "\n".join(lines)
    return code


def _process_memory_tags(reply: str) -> str:
    """Извлечь [ЗАПОМНИТЬ: ...] и убрать из ответа."""
    for m in re.finditer(r"\[ЗАПОМНИТЬ:\s*(.+?)\]", reply):
        add_memory(m.group(1).strip())
    return re.sub(r"\s*\[ЗАПОМНИТЬ:\s*.+?\]", "", reply).strip()


# ── Высокоуровневые функции ──────────────────────────────────────────

async def route_user_message(
    user_text: str, history: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    messages = [{"role": "system", "content": SYSTEM_ROUTER_PROMPT}]
    if history:
        messages.extend(history[-10:])
    messages.append({"role": "user", "content": user_text})
    raw = await ollama_chat(messages, temperature=0.0)
    data = extract_json(raw)

    if data.get("intent") not in ("weather", "chat", "action"):
        data["intent"] = "chat"
    if not isinstance(data.get("cities"), list):
        data["cities"] = []
    data.setdefault("city", None)
    data.setdefault("country", None)
    data.setdefault("action_description", None)
    data.setdefault("action_type", None)
    if data.get("date_hint") not in ("today", "tomorrow", "unknown"):
        data["date_hint"] = "unknown"
    if not isinstance(data.get("days_ahead"), int):
        data["days_ahead"] = None

    if not data["cities"] and data.get("city"):
        data["cities"] = [{"city": data["city"], "country": data.get("country")}]
    if len(data["cities"]) > 1:
        data["city"] = None
        data["country"] = None

    return data


async def generate_chat_reply(
    user_text: str, history: list[dict[str, str]] | None = None
) -> str:
    prompt = SYSTEM_CHAT_PROMPT.replace("{memory}", get_memory_text())
    messages = [{"role": "system", "content": prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_text})
    raw = await ollama_chat(messages, temperature=0.7)
    return _process_memory_tags(raw.strip())


async def suggest_cities_for_country(country: str) -> list[str]:
    raw = await ollama_chat(
        [
            {"role": "system", "content": SYSTEM_CITY_PICKER_PROMPT},
            {"role": "user", "content": country},
        ],
        temperature=0.2,
    )
    data = extract_json(raw)
    cities = data.get("cities")
    if not isinstance(cities, list):
        return []
    return [c.strip() for c in cities if isinstance(c, str) and c.strip()][:3]


async def plan_action(task: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Планировщик: анализирует задачу и возвращает план."""
    messages = [{"role": "system", "content": SYSTEM_PLANNER_PROMPT}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": task})
    raw = await ollama_chat(messages, temperature=0.1)
    return extract_json(raw)


async def generate_code(task: str, plan: dict, context_files: dict[str, str] | None = None) -> str:
    """Генерация кода с учётом плана и контекста файлов."""
    prompt_parts = [f"Задача: {task}\n\nПлан: {plan.get('plan', '')}\n\nТип: {plan.get('type', 'script')}"]
    if context_files:
        for path, content in context_files.items():
            prompt_parts.append(f"\n--- Файл {path} ---\n{content}")
    if plan.get("needs_packages"):
        prompt_parts.append(f"\nНужные пакеты: {', '.join(plan['needs_packages'])}")

    raw = await ollama_chat(
        [
            {"role": "system", "content": SYSTEM_CODEGEN_PROMPT},
            {"role": "user", "content": "\n".join(prompt_parts)},
        ],
        temperature=0.2,
    )
    return _strip_markdown(raw)


async def fix_code(code: str, error: str, task: str) -> str:
    """Исправление кода после ошибки."""
    raw = await ollama_chat(
        [
            {"role": "system", "content": SYSTEM_CODEGEN_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Задача: {task}\n\n"
                    f"Код с ошибкой:\n{code}\n\n"
                    f"Ошибка:\n{error}\n\n"
                    f"Исправь. Верни ПОЛНЫЙ исправленный код."
                ),
            },
        ],
        temperature=0.1,
    )
    return _strip_markdown(raw)


async def maybe_generate_proactive(
    history_messages: list[dict[str, str]],
) -> str | None:
    prompt = SYSTEM_PROACTIVE_PROMPT.replace("{memory}", get_memory_text())
    messages = [{"role": "system", "content": prompt}]
    messages.extend(history_messages[-15:])
    messages.append(
        {"role": "user", "content": "[Система: хочешь что-то написать пользователю?]"}
    )
    raw = await ollama_chat(messages, temperature=0.8)
    reply = raw.strip()
    if not reply or reply == "ПУСТО" or len(reply) < 3:
        return None
    return _process_memory_tags(reply) or None
