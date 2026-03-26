"""Контекст, доступный динамическим плагинам.

Каждый плагин получает объект PluginContext при вызове,
через который может обращаться к сервисам бота.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiogram.types import Message


@dataclass
class PluginContext:
    """Набор утилит, передаваемых в динамический хендлер."""

    message: Message
    # Сервисы — заполняются при создании контекста
    services: dict[str, Any] = field(default_factory=dict)

    # --- Удобные шорткаты ---

    async def reply(self, text: str) -> None:
        await self.message.answer(text)

    @property
    def text(self) -> str:
        return (self.message.text or "").strip()

    @property
    def user_id(self) -> int:
        return self.message.from_user.id if self.message.from_user else 0

    @property
    def llm(self):
        """Доступ к LLM-сервису."""
        return self.services["llm"]

    @property
    def weather(self):
        """Доступ к weather-сервису."""
        return self.services["weather"]
