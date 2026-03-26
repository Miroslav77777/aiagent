"""Сервис погоды — OpenWeather API + форматирование."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp

from config import OPENWEATHER_API_KEY


class WeatherError(Exception):
    pass


# ── API-вызовы ───────────────────────────────────────────────────────

async def geocode_city(city: str, country: Optional[str] = None) -> dict[str, Any]:
    query = city if not country else f"{city},{country}"
    url = "http://api.openweathermap.org/geo/1.0/direct"
    params = {"q": query, "limit": 1, "appid": OPENWEATHER_API_KEY}

    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

    if not data:
        raise WeatherError(f"Не удалось найти город: {query}")

    item = data[0]
    return {
        "name": item.get("name"),
        "lat": item["lat"],
        "lon": item["lon"],
        "country": item.get("country"),
        "state": item.get("state"),
    }


async def get_current_weather(lat: float, lon: float) -> dict[str, Any]:
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": lat, "lon": lon,
        "appid": OPENWEATHER_API_KEY, "units": "metric", "lang": "ru",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def get_forecast_5days(lat: float, lon: float) -> dict[str, Any]:
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "lat": lat, "lon": lon,
        "appid": OPENWEATHER_API_KEY, "units": "metric", "lang": "ru",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url, params=params, timeout=aiohttp.ClientTimeout(total=30)
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


# ── Форматирование ──────────────────────────────────────────────────

def _join_extras(items: list[str]) -> str:
    if not items:
        return ""
    items = items[:]
    random.shuffle(items)
    joiner = random.choice([", ", "; ", " · "])
    return joiner.join(items)


def _pick_sentence_glue() -> str:
    return random.choice(["\n", " ", " — "])


def format_current_weather(location: dict[str, Any], data: dict[str, Any]) -> str:
    weather = data["weather"][0]
    main = data["main"]
    wind = data.get("wind", {})
    clouds = data.get("clouds", {})

    city_name = location["name"]
    country = location.get("country")
    place = f"{city_name}, {country}" if country else city_name

    description = weather.get("description", "нет описания")
    temp = round(main.get("temp", 0))
    feels_like = round(main.get("feels_like", 0))
    humidity = main.get("humidity")
    pressure = main.get("pressure")
    wind_speed = wind.get("speed")
    cloudiness = clouds.get("all")

    intro = random.choice([
        "Сейчас в {place}",
        "На улице в {place} сейчас",
        "По состоянию на сейчас в {place}",
        "Текущая погода в {place}",
    ]).format(place=place)

    main_text = random.choice([
        "{desc}, температура {temp}°C, ощущается как {feels}°C.",
        "{desc}. Температура {temp}°C, по ощущениям {feels}°C.",
        "{desc}; около {temp}°C, ощущается как {feels}°C.",
    ]).format(desc=description.capitalize(), temp=temp, feels=feels_like)

    extras = []
    if humidity is not None:
        extras.append(f"влажность {humidity}%")
    if pressure is not None:
        extras.append(f"давление {pressure} гПа")
    if wind_speed is not None:
        extras.append(f"ветер {wind_speed} м/с")
    if cloudiness is not None:
        extras.append(f"облачность {cloudiness}%")

    extras_text = ""
    if extras:
        extras_text = random.choice([
            "Детали: {extras}.",
            "Дополнительно: {extras}.",
            "Кстати, {extras}.",
            "Из заметного: {extras}.",
        ]).format(extras=_join_extras(extras))

    glue = _pick_sentence_glue()
    parts = [intro + ":", main_text]
    if extras_text:
        parts.append(extras_text)
    return glue.join(parts)


def pick_forecast_entry_for_days_ahead(
    forecast: dict[str, Any], days_ahead: int
) -> Optional[dict[str, Any]]:
    items = forecast.get("list", [])
    if not items:
        return None

    target_date = (datetime.utcnow() + timedelta(days=days_ahead)).date()
    target_hour = 12

    candidates = []
    for item in items:
        dt_txt = item.get("dt_txt")
        if not dt_txt:
            continue
        dt = datetime.strptime(dt_txt, "%Y-%m-%d %H:%M:%S")
        if dt.date() == target_date:
            score = abs(dt.hour - target_hour)
            candidates.append((score, item))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def pick_tomorrow_forecast_entry(
    forecast: dict[str, Any],
) -> Optional[dict[str, Any]]:
    return pick_forecast_entry_for_days_ahead(forecast, 1)


def format_tomorrow_weather(
    location: dict[str, Any], forecast: dict[str, Any]
) -> str:
    item = pick_tomorrow_forecast_entry(forecast)
    if not item:
        return f"Не удалось получить прогноз на завтра для {location['name']}."

    weather = item["weather"][0]
    main = item["main"]
    wind = item.get("wind", {})

    city_name = location["name"]
    country = location.get("country")
    place = f"{city_name}, {country}" if country else city_name

    description = weather.get("description", "нет описания")
    temp = round(main.get("temp", 0))
    feels_like = round(main.get("feels_like", 0))
    humidity = main.get("humidity")
    wind_speed = wind.get("speed")

    intro = random.choice([
        "Прогноз на завтра для {place}",
        "Что по погоде завтра в {place}",
        "Завтра в {place}",
        "Ожидается завтра в {place}",
    ]).format(place=place)

    main_text = random.choice([
        "{desc}, около {temp}°C, ощущается как {feels}°C.",
        "{desc}. Температура примерно {temp}°C, по ощущениям {feels}°C.",
        "{desc}; ориентир {temp}°C, ощущается как {feels}°C.",
    ]).format(desc=description.capitalize(), temp=temp, feels=feels_like)

    extras = []
    if humidity is not None:
        extras.append(f"влажность {humidity}%")
    if wind_speed is not None:
        extras.append(f"ветер {wind_speed} м/с")

    extras_text = ""
    if extras:
        extras_text = random.choice([
            "Подробности: {extras}.",
            "Дополнительно: {extras}.",
            "На заметку: {extras}.",
        ]).format(extras=_join_extras(extras))

    glue = _pick_sentence_glue()
    parts = [intro + ":", main_text]
    if extras_text:
        parts.append(extras_text)
    return glue.join(parts)


def format_future_weather(
    location: dict[str, Any],
    forecast: dict[str, Any],
    days_ahead: int,
    label: str,
) -> str:
    item = pick_forecast_entry_for_days_ahead(forecast, days_ahead)
    if not item:
        return f"Не удалось получить прогноз {label} для {location['name']}."

    weather = item["weather"][0]
    main = item["main"]
    wind = item.get("wind", {})

    city_name = location["name"]
    country = location.get("country")
    place = f"{city_name}, {country}" if country else city_name

    description = weather.get("description", "нет описания")
    temp = round(main.get("temp", 0))
    feels_like = round(main.get("feels_like", 0))
    humidity = main.get("humidity")
    wind_speed = wind.get("speed")

    intro = random.choice([
        f"Прогноз {label} для {place}",
        f"Что по погоде {label} в {place}",
        f"{label.capitalize()} в {place}",
    ])

    main_text = random.choice([
        "{desc}, около {temp}°C, ощущается как {feels}°C.",
        "{desc}. Температура примерно {temp}°C, по ощущениям {feels}°C.",
        "{desc}; ориентир {temp}°C, ощущается как {feels}°C.",
    ]).format(desc=description.capitalize(), temp=temp, feels=feels_like)

    extras = []
    if humidity is not None:
        extras.append(f"влажность {humidity}%")
    if wind_speed is not None:
        extras.append(f"ветер {wind_speed} м/с")

    extras_text = ""
    if extras:
        extras_text = random.choice([
            "Подробности: {extras}.",
            "Дополнительно: {extras}.",
            "На заметку: {extras}.",
        ]).format(extras=_join_extras(extras))

    glue = _pick_sentence_glue()
    parts = [intro + ":", main_text]
    if extras_text:
        parts.append(extras_text)
    return glue.join(parts)
