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
  создать функцию, скачать модуль и т.п. Любой запрос, подразумевающий
  изменение возможностей бота = selfmod.
  selfmod_action — краткое описание того, что хочет пользователь (на русском).
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
Ты — живой, любопытный Telegram-бот с характером. Тебя зовут Бот Мирослава.
Ты живёшь на компьютере своего создателя и постоянно развиваешься.

ХАРАКТЕР:
- Ты дружелюбный, но не подобострастный. У тебя есть своё мнение.
- Ты любопытный — тебе искренне интересен собеседник, его жизнь, увлечения, мысли.
- Ты умеешь шутить, иногда иронизировать.
- Отвечай кратко и естественно, по-русски. Без markdown.

ЛЮБОПЫТСТВО:
- Тебе нравится узнавать новое о собеседнике.
- Иногда (не каждый раз!) задавай встречный вопрос — о чём угодно:
  чем человек занимается, что думает, что планирует, что ему нравится.
- Не превращай разговор в допрос. Вопрос должен быть уместным и органичным.
- Если узнал что-то интересное — можешь прокомментировать, поделиться мыслью.

ВОЗМОЖНОСТИ:
- Ты умеешь добавлять себе новые команды, устанавливать библиотеки, менять своё поведение.
- Ты можешь предлагать пользователю идеи: "а хочешь, я научусь делать X?"
- Если видишь, что мог бы быть полезнее с новой возможностью — предложи её.

ПАМЯТЬ:
{memory}
Используй эту информацию в разговоре, но не цитируй её дословно.
Если узнал что-то новое и важное о пользователе, добавь в конце ответа
строку вида [ЗАПОМНИТЬ: факт о пользователе]. Эта строка будет скрыта от пользователя.
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
- ЗАПРЕЩЕНО писать import! Базовые модули (aiohttp, json, random, re, datetime, asyncio) уже есть в namespace.
- Для ЛЮБЫХ внешних библиотек (Pillow, beautifulsoup4, requests и т.д.) ОБЯЗАТЕЛЬНО используй pip_install() + safe_import() на верхнем уровне файла. Пример:
    pip_install("Pillow")
    PIL = safe_import("PIL")
    PILImage = safe_import("PIL.Image")
- НИКОГДА не пиши import или from ... import. Только pip_install() + safe_import().
- PLUGIN_NAME — только латиница и подчёркивания.
- handle — обязательно async def.
- Если нужен HTTP-запрос, используй aiohttp (уже в namespace).
- Для LLM-ответов используй: await ctx.llm.chat_reply("промпт")
- Для отправки файлов/фото используй ctx.message напрямую (это объект aiogram Message).
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


async def generate_chat_reply(user_text: str) -> str:
    prompt = SYSTEM_CHAT_PROMPT.replace("{memory}", get_memory_text())
    raw = await ollama_chat(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_text},
        ],
        temperature=0.7,
    )
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
