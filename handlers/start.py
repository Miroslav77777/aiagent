"""Хендлер /start."""

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "Привет! Я бот, созданный Мирославом Александровичем\n"
        "Я живу у него на компьютере\n"
        "Можешь спросить, например:\n"
        "— Какая погода в Москве?\n"
        "— Какая завтра погода в Берлине?\n"
        "— Просто поговорить со мной :)\n\n"
        "Я также могу добавлять себе новые возможности!\n"
        "Напиши: «добавь команду /joke которая рассказывает шутки»"
    )
