import json
import re
from typing import Any, Dict

import aiohttp

from config import OLLAMA_BASE_URL, OLLAMA_MODEL


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


async def ollama_chat(messages: list[dict[str, str]], temperature: float = 0.2) -> str:
    url = f"{OLLAMA_BASE_URL}/api/chat"

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=90)) as resp:
            resp.raise_for_status()
            data = await resp.json()

    # Ollama обычно возвращает content здесь
    return data["message"]["content"]


def extract_json(text: str) -> Dict[str, Any]:
    """
    Пытаемся вытащить JSON даже если модель случайно обернула его лишним текстом.
    """
    text = text.strip()

    # Попытка 1: сразу parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Попытка 2: найти первый {...}
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Не удалось извлечь JSON из ответа модели: {text}")

    candidate = match.group(0)
    return json.loads(candidate)


async def route_user_message(user_text: str) -> Dict[str, Any]:
    raw = await ollama_chat(
        [
            {"role": "system", "content": SYSTEM_ROUTER_PROMPT},
            {"role": "user", "content": user_text},
        ],
        temperature=0.0,
    )
    data = extract_json(raw)

    # Нормализация
    intent = data.get("intent")
    if intent not in ("weather", "chat"):
        data["intent"] = "chat"

    if "cities" not in data or not isinstance(data.get("cities"), list):
        data["cities"] = []
    if "city" not in data:
        data["city"] = None
    if "country" not in data:
        data["country"] = None
    if data.get("date_hint") not in ("today", "tomorrow", "unknown"):
        data["date_hint"] = "unknown"
    if "days_ahead" not in data or not isinstance(data.get("days_ahead"), int):
        data["days_ahead"] = None
    if "original_user_text" not in data:
        data["original_user_text"] = user_text

    # Совместимость: если cities пуст, но есть city, перенесем в список
    if not data["cities"] and data.get("city"):
        data["cities"] = [{"city": data["city"], "country": data.get("country")}]
    # Если в cities несколько, одиночные поля обнулим
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
    result = []
    for item in cities:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
    return result[:3]
