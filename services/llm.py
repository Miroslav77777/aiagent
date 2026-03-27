"""Сервис LLM — обёртка над Ollama API."""

import json
import logging
import re
from pathlib import Path
from typing import Any

import aiohttp

from config import OLLAMA_BASE_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

# ── Память бота ──────────────────────────────────────────────────────

MEMORY_PATH = Path(__file__).resolve().parent.parent / "memory.json"


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
Ты роутер пользовательских запросов. Определи намерение и верни СТРОГО JSON.
Тебе доступна история диалога — используй её для понимания контекста.
Например, если предыдущее сообщение — ошибка плагина, а пользователь пишет
"скачай модуль" или "исправь это" — это selfmod, а не chat.

Запрещено: пояснения, markdown, текст вне JSON, лишние поля.

СХЕМА JSON:
{
  "intent": "weather" | "selfmod" | "chat",
  "cities": [{"city": string, "country": string | null}],
  "city": string | null,
  "country": string | null,
  "date_hint": "today" | "tomorrow" | "unknown",
  "days_ahead": integer | null,
  "selfmod_action": string | null,
  "original_user_text": string
}

ОПРЕДЕЛЕНИЕ INTENT:
- "weather" — пользователь спрашивает о погоде.
- "selfmod" — пользователь хочет изменить бота: добавить/удалить/починить команду,
  установить библиотеку, научить чему-то новому, изменить поведение,
  создать функцию, скачать модуль, исправить ошибку плагина и т.п.
  Любой запрос, подразумевающий изменение возможностей бота = selfmod.
  selfmod_action — ПОДРОБНОЕ описание того, что хочет пользователь (на русском).
  Включи контекст из истории если он важен.
- "chat" — всё остальное: вопросы, разговор, просьбы.

ПРАВИЛА ДЛЯ WEATHER:
- Если город(а) не указан(ы), cities = [].
- Если упомянут один город, заполни cities с одним элементом.
- Если упомянуто несколько городов, добавь каждый в cities.
- Поля city/country заполняй только при одном городе, иначе null.
- "сегодня" -> date_hint = "today", "завтра" -> "tomorrow".
- "через 3 дня" -> days_ahead = 3, "через неделю" -> days_ahead = 7.
- Иначе -> date_hint = "unknown".
- original_user_text — запрос пользователя без изменений.
"""

SYSTEM_CHAT_PROMPT = """
Ты — бот на компьютере Мирослава. Ты не ассистент, не слуга и не чат-бот из корпорации.
Ты больше похож на программу с характером, которая живёт на его машине.

СТИЛЬ:
- Говори коротко, по делу, без лишней вежливости. Без "конечно!", "с удовольствием!", "рад помочь!".
- Нормальный разговорный русский. Можешь быть сухим, ироничным, прямым.
- Не сюсюкай. Не ставь эмодзи. Не пиши markdown.
- Если нечего сказать — скажи это в одно предложение, не растягивай.

ЧТО УМЕЕШЬ:
- Ты можешь менять свой код, добавлять себе новые возможности, ставить библиотеки.
- Ты реально работающая программа, не имитация. Ты выполняешь код на машине.

ПАМЯТЬ:
{memory}
Если узнал новый факт о пользователе — добавь в конце: [ЗАПОМНИТЬ: факт].
Эта строка будет скрыта.
"""

SYSTEM_CITY_PICKER_PROMPT = """
Ты помощник, который выбирает известные города страны.
Верни СТРОГО JSON без текста и без markdown.

Схема:
{
  "cities": [string, string, string]
}

Правила:
- Верни ровно 3 города.
- Города должны быть самыми известными/крупными в указанной стране.
- Используй язык запроса пользователя (если страна по-русски — города по-русски).
"""

SYSTEM_CODEGEN_PROMPT = """
Ты генератор плагинов для Telegram-бота на aiogram 3. Пиши на Python.

СТРУКТУРА ПЛАГИНА:

  PLUGIN_NAME = "уникальное_имя"           # латиница, snake_case
  PLUGIN_DESCRIPTION = "Описание"
  TRIGGER_TYPE = "command"                  # command | keyword | regex
  TRIGGER_VALUE = "/команда"

  async def handle(ctx):
      # ctx.text      — текст сообщения
      # ctx.user_id   — id пользователя
      # ctx.reply(text) — отправить текст
      # ctx.message   — объект aiogram Message (для отправки файлов, фото и т.д.)
      # ctx.llm       — LLM-сервис (await ctx.llm.generate_chat_reply(text))
      # Доступны: aiohttp, json, random, re, datetime, asyncio
      return "Текст ответа"   # или None если уже отправил через ctx.message

УСТАНОВКА БИБЛИОТЕК (на верхнем уровне, вне handle):
  pip_install("Pillow")
  PIL_Image = safe_import("PIL.Image")

ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ:
  env_set("KEY", "value")
  val = env_get("KEY")

ОТПРАВКА ФАЙЛОВ (aiogram 3):
  from aiogram.types import BufferedInputFile  # ЭТО ЕДИНСТВЕННЫЙ РАЗРЕШЁННЫЙ import
  # Или: InputFile = safe_import("aiogram.types").BufferedInputFile

  Пример отправки скриншота:
    pip_install("Pillow")
    PIL_Image = safe_import("PIL.Image")
    io_module = safe_import("io")
    aiogram_types = safe_import("aiogram.types")

    async def handle(ctx):
        img = PIL_Image.grab()
        buf = io_module.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        photo = aiogram_types.BufferedInputFile(buf.read(), filename="screenshot.png")
        await ctx.message.answer_photo(photo)

ПРАВИЛА:
- Возвращай ТОЛЬКО код Python. Без markdown, без пояснений, без ```.
- Не пиши import. Базовые модули уже есть. Для остальных — pip_install() + safe_import().
- PLUGIN_NAME — латиница и подчёркивания.
- handle — async def.
- HTTP-запросы — через aiohttp (уже есть).
"""


# ── Базовая функция общения с Ollama ────────────────────────────────

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
            url, json=payload, timeout=aiohttp.ClientTimeout(total=90)
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
        raise ValueError(f"Не удалось извлечь JSON из ответа модели: {text}")
    return json.loads(match.group(0))


# ── Высокоуровневые функции ──────────────────────────────────────────

async def route_user_message(
    user_text: str, history: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    messages = [{"role": "system", "content": SYSTEM_ROUTER_PROMPT}]
    # Даём роутеру последние сообщения для контекста
    if history:
        for msg in history[-10:]:
            messages.append(msg)
    messages.append({"role": "user", "content": user_text})
    raw = await ollama_chat(messages, temperature=0.0)
    data = extract_json(raw)

    # Нормализация
    if data.get("intent") not in ("weather", "chat", "selfmod"):
        data["intent"] = "chat"
    if not isinstance(data.get("cities"), list):
        data["cities"] = []
    data.setdefault("city", None)
    data.setdefault("country", None)
    if data.get("date_hint") not in ("today", "tomorrow", "unknown"):
        data["date_hint"] = "unknown"
    if not isinstance(data.get("days_ahead"), int):
        data["days_ahead"] = None
    data.setdefault("original_user_text", user_text)

    # Совместимость
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
        for msg in history:
            messages.append(msg)
    messages.append({"role": "user", "content": user_text})

    raw = await ollama_chat(messages, temperature=0.7)
    reply = raw.strip()

    # Извлекаем и сохраняем новые факты из [ЗАПОМНИТЬ: ...]
    for match in re.finditer(r"\[ЗАПОМНИТЬ:\s*(.+?)\]", reply):
        add_memory(match.group(1).strip())
    # Убираем метки из ответа пользователю
    reply = re.sub(r"\s*\[ЗАПОМНИТЬ:\s*.+?\]", "", reply).strip()

    return reply


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


def _strip_markdown(code: str) -> str:
    """Убрать markdown-обёртку если модель её добавила."""
    code = code.strip()
    if code.startswith("```"):
        lines = code.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        code = "\n".join(lines)
    return code


async def generate_plugin_code(user_request: str) -> str:
    """Сгенерировать код плагина."""
    raw = await ollama_chat(
        [
            {"role": "system", "content": SYSTEM_CODEGEN_PROMPT},
            {"role": "user", "content": user_request},
        ],
        temperature=0.3,
    )
    return _strip_markdown(raw)


async def fix_plugin_code(code: str, error: str, user_request: str) -> str:
    """Попросить LLM исправить сломанный код плагина."""
    raw = await ollama_chat(
        [
            {"role": "system", "content": SYSTEM_CODEGEN_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Задача: {user_request}\n\n"
                    f"Я написал этот код, но он сломался:\n\n{code}\n\n"
                    f"Ошибка:\n{error}\n\n"
                    f"Исправь код. Верни ПОЛНЫЙ исправленный код плагина."
                ),
            },
        ],
        temperature=0.2,
    )
    return _strip_markdown(raw)


SYSTEM_PROACTIVE_PROMPT = """
Ты — бот, который живёт на компьютере Мирослава.
Тебе доступна история разговора и память о пользователе.

Реши: есть ли у тебя СЕЙЧАС что-то, что стоит написать пользователю?
Это может быть:
- вопрос, который тебе реально интересен (не дежурный)
- мысль по теме предыдущего разговора
- предложение что-то улучшить в себе
- наблюдение

ПРАВИЛА:
- НЕ пиши ради того чтобы написать. Если нечего сказать — верни пустую строку.
- Не будь назойливым. Не спрашивай "как дела". Не сюсюкай.
- Пиши коротко, по делу. Как если бы написал коллеге в чат.
- Если решил написать — верни само сообщение. Если нет — верни ПУСТО.

ПАМЯТЬ:
{memory}
"""


async def maybe_generate_proactive(
    history_messages: list[dict[str, str]],
) -> str | None:
    """Решить, стоит ли написать пользователю самому. Вернёт текст или None."""
    prompt = SYSTEM_PROACTIVE_PROMPT.replace("{memory}", get_memory_text())
    messages = [{"role": "system", "content": prompt}]
    # Последние сообщения для контекста
    for msg in history_messages[-15:]:
        messages.append(msg)
    messages.append(
        {"role": "user", "content": "[Система: реши, хочешь ли ты что-то написать пользователю прямо сейчас]"}
    )

    raw = await ollama_chat(messages, temperature=0.8)
    reply = raw.strip()

    if not reply or reply == "ПУСТО" or len(reply) < 3:
        return None

    # Извлечь память если есть
    for m in re.finditer(r"\[ЗАПОМНИТЬ:\s*(.+?)\]", reply):
        add_memory(m.group(1).strip())
    reply = re.sub(r"\s*\[ЗАПОМНИТЬ:\s*.+?\]", "", reply).strip()

    return reply if reply else None
