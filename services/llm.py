"""Сервис LLM — обёртка над Ollama API."""

import json
import re
from typing import Any

import aiohttp

from config import OLLAMA_BASE_URL, OLLAMA_MODEL


# ── Системные промпты ──────────────────────────────────────────────

SYSTEM_ROUTER_PROMPT = """
Ты роутер пользовательских запросов.

Твоя задача:
1. Определить, связан ли запрос с погодой.
2. Если связан, вернуть СТРОГО JSON по схеме ниже.
3. Если не связан, вернуть СТРОГО JSON по схеме ниже.

Запрещено:
- писать пояснения
- писать markdown
- писать текст вне JSON
- добавлять лишние поля

СХЕМА JSON:
{
  "intent": "weather" | "chat",
  "cities": [{"city": string, "country": string | null}],
  "city": string | null,
  "country": string | null,
  "date_hint": "today" | "tomorrow" | "unknown",
  "days_ahead": integer | null,
  "original_user_text": string
}

ПРАВИЛА:
- Если пользователь спрашивает о погоде, intent = "weather".
- Если город(а) не указан(ы), cities = [].
- Если упомянут один город, заполни cities с одним элементом.
- Если упомянуто несколько городов, добавь каждый в cities.
- Поля city/country заполняй только при одном городе, иначе null.
- Если есть "сегодня" -> date_hint = "today".
- Если есть "завтра" -> date_hint = "tomorrow".
- Если есть относительная дата ("через 3 дня", "через неделю", "через 2 недели") -> days_ahead = 3/7/14.
- Если "через неделю" -> days_ahead = 7.
- Если есть "через X дней/недель", пересчитай в дни и заполни days_ahead.
- Иначе -> "unknown".
- original_user_text должен повторять запрос пользователя без изменений.
- Ответ должен быть только валидным JSON.
"""

SYSTEM_CHAT_PROMPT = """
Ты дружелюбный Telegram-бот.
Отвечай кратко, естественно и по-русски.
Не используй markdown без необходимости.
Ты не можешь выполнять или изменять код бота во время переписки.
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
Ты генератор плагинов для Telegram-бота. Пиши на Python.

Каждый плагин — это Python-файл, определяющий:

  PLUGIN_NAME = "уникальное_имя"           # латиница, snake_case
  PLUGIN_DESCRIPTION = "Описание"          # что делает
  TRIGGER_TYPE = "command"                  # command | keyword | regex
  TRIGGER_VALUE = "/команда"               # значение триггера

  async def handle(ctx):
      # ctx.text      — текст сообщения пользователя
      # ctx.user_id   — id пользователя
      # ctx.reply(text) — отправить ответ
      # ctx.llm       — сервис LLM (await ctx.llm.chat_reply(text))
      # ctx.services   — dict сервисов
      # Доступны: aiohttp, json, random, re, datetime, asyncio
      return "Текст ответа"   # или None если уже вызвал ctx.reply

УСТАНОВКА БИБЛИОТЕК:
  Если плагину нужна внешняя библиотека, вызови pip_install и safe_import
  НА ВЕРХНЕМ УРОВНЕ файла (вне handle):

  pip_install("beautifulsoup4", "lxml")   # установит если ещё нет
  bs4 = safe_import("bs4")                # импортирует модуль

  Потом в handle используй bs4 как обычно.

ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (.env):
  env_set("MY_API_KEY", "значение")   # записать/обновить в .env + применить
  env_get("MY_API_KEY")               # прочитать переменную
  Используй для хранения API-ключей и настроек.

ПРАВИЛА:
- Возвращай ТОЛЬКО код Python, без markdown и пояснений.
- Не пиши import (базовые модули уже доступны в namespace).
- Для внешних библиотек используй pip_install() + safe_import(), НЕ import.
- PLUGIN_NAME — только латиница и подчёркивания.
- handle — обязательно async def.
- Если нужен HTTP-запрос, используй aiohttp.
- Для LLM-ответов используй: await ctx.llm.chat_reply("промпт")
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

async def route_user_message(user_text: str) -> dict[str, Any]:
    raw = await ollama_chat(
        [
            {"role": "system", "content": SYSTEM_ROUTER_PROMPT},
            {"role": "user", "content": user_text},
        ],
        temperature=0.0,
    )
    data = extract_json(raw)

    # Нормализация
    if data.get("intent") not in ("weather", "chat"):
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


async def generate_chat_reply(user_text: str) -> str:
    raw = await ollama_chat(
        [
            {"role": "system", "content": SYSTEM_CHAT_PROMPT},
            {"role": "user", "content": user_text},
        ],
        temperature=0.7,
    )
    return raw.strip()


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


async def generate_plugin_code(user_request: str) -> str:
    """Попросить LLM сгенерировать код плагина по запросу пользователя."""
    raw = await ollama_chat(
        [
            {"role": "system", "content": SYSTEM_CODEGEN_PROMPT},
            {"role": "user", "content": user_request},
        ],
        temperature=0.3,
    )
    # Убираем markdown-обёртку если модель её добавила
    code = raw.strip()
    if code.startswith("```"):
        lines = code.split("\n")
        # Убираем первую строку ```python и последнюю ```
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        code = "\n".join(lines)
    return code
