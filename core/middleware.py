"""Middleware: доступ только для ADMIN_USER_ID."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message

from config import ADMIN_USER_ID


class AdminOnlyMiddleware(BaseMiddleware):
    """Молча игнорирует все сообщения не от админа."""

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if not user or user.id != ADMIN_USER_ID:
            return  # Тихо отбрасываем — посторонний не получит даже ошибку
        return await handler(event, data)
