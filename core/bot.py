"""Глобальные объекты бота — создаются один раз при импорте."""

from aiogram import Bot, Dispatcher

from config import TELEGRAM_BOT_TOKEN

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
