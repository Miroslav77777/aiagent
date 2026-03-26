"""Хендлер погоды — вся логика обработки weather-интента."""

import asyncio
import logging
import re

from aiogram.types import Message

from services.llm import route_user_message, suggest_cities_for_country
from services.weather_api import (
    WeatherError,
    geocode_city,
    get_current_weather,
    get_forecast_5days,
    format_current_weather,
    format_tomorrow_weather,
    format_future_weather,
)

logger = logging.getLogger(__name__)


# ── Вспомогательные функции ──────────────────────────────────────────

def fallback_extract_country(text: str) -> str | None:
    lower = text.lower()
    if "погод" not in lower:
        return None
    match = re.search(r"(?:\s|^)(?:в|во|на)\s+([^?.!,]+)", text, re.IGNORECASE)
    if not match:
        return None
    chunk = match.group(1).strip()
    for w in ("сегодня", "завтра", "послезавтра"):
        chunk = re.sub(rf"\b{w}\b", "", chunk, flags=re.IGNORECASE).strip()
    return chunk or None


def parse_days_ahead(text: str) -> int | None:
    lower = text.lower()
    if "через неделю" in lower:
        return 7
    m = re.search(r"через\s+(\d+)\s+дн(я|ей|ень)", lower)
    if m:
        return int(m.group(1))
    m = re.search(r"через\s+(\d+)\s+недел(ю|и|ь)", lower)
    if m:
        return int(m.group(1)) * 7
    return None


def plural_days(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return "дня"
    return "дней"


def fallback_extract_cities(text: str) -> list[dict]:
    lower = text.lower()
    if "погод" not in lower:
        return []
    match = re.search(r"(?:\s|^)(?:в|во|на)\s+([^?.!,]+)", text, re.IGNORECASE)
    if not match:
        return []
    chunk = match.group(1).strip()
    for w in ("сегодня", "завтра", "послезавтра"):
        chunk = re.sub(rf"\b{w}\b", "", chunk, flags=re.IGNORECASE).strip()
    norm_map = {"мальдивах": "Мальдивы"}
    if chunk.lower() in norm_map:
        chunk = norm_map[chunk.lower()]
    return [{"city": chunk, "country": None}] if chunk else []


# ── Основная функция обработки погоды ────────────────────────────────

async def handle_weather(message: Message, route: dict) -> None:
    """Обрабатывает weather-интент, отправляет результат пользователю."""
    user_text = (message.text or "").strip()
    date_hint = route.get("date_hint", "unknown")
    days_ahead = route.get("days_ahead")

    if days_ahead is None:
        days_ahead = parse_days_ahead(user_text)
    if date_hint == "today" and days_ahead is None:
        days_ahead = 0
    if date_hint == "tomorrow" and days_ahead is None:
        days_ahead = 1

    # Извлечение городов
    raw_cities = route.get("cities") or []
    cities = []
    for item in raw_cities:
        if not isinstance(item, dict):
            continue
        city = item.get("city")
        if city and isinstance(city, str) and city.strip():
            cities.append({"city": city.strip(), "country": item.get("country")})

    if not cities:
        country_name = route.get("country") or fallback_extract_country(user_text)
        if country_name:
            picked = await suggest_cities_for_country(country_name)
            for name in picked:
                cities.append({"city": name, "country": None})
        if not cities:
            cities = fallback_extract_cities(user_text)

    if not cities:
        await message.answer(
            "Я понял, что ты спрашиваешь про погоду, но не вижу город. "
            "Напиши, например: «Какая погода в Москве?»"
        )
        return

    # Сообщение ожидания
    if len(cities) == 1:
        city = cities[0].get("city")
        wait_text = (
            f"Понял запрос, смотрю прогноз погоды для {city}..."
            if date_hint == "tomorrow"
            else f"Понял запрос, смотрю погоду для {city}..."
        )
        await message.answer(wait_text)
    else:
        await message.answer(
            "Понял запрос, смотрю погоду по всем указанным городам..."
        )

    async def fetch_city_weather(item: dict) -> str:
        city = item.get("city")
        country = item.get("country")
        if not city:
            return "Не смог распознать один из городов."
        location = await geocode_city(city, country)
        if days_ahead is not None and days_ahead > 1:
            if days_ahead > 5:
                return (
                    f"Прогноз доступен только на 5 дней вперёд. "
                    f"Запрос было на {days_ahead} {plural_days(days_ahead)}."
                )
            forecast = await get_forecast_5days(location["lat"], location["lon"])
            label = f"через {days_ahead} {plural_days(days_ahead)}"
            return format_future_weather(location, forecast, days_ahead, label)
        if date_hint == "tomorrow" or days_ahead == 1:
            forecast = await get_forecast_5days(location["lat"], location["lon"])
            return format_tomorrow_weather(location, forecast)
        current = await get_current_weather(location["lat"], location["lon"])
        return format_current_weather(location, current)

    results = await asyncio.gather(
        *(fetch_city_weather(item) for item in cities),
        return_exceptions=True,
    )

    parts = []
    for res in results:
        if isinstance(res, Exception):
            if isinstance(res, WeatherError):
                parts.append(f"Не получилось получить погоду: {res}")
            else:
                logger.exception("Ошибка при получении погоды: %s", res)
                parts.append(
                    "Произошла ошибка при получении погоды для одного из городов."
                )
        else:
            parts.append(res)

    await message.answer("\n\n".join(parts))
