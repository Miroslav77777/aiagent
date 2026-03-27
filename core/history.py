"""История диалога — единый контекст разговора для всех частей бота."""

from __future__ import annotations


class ChatHistory:
    """Хранит последние N сообщений диалога в формате OpenAI-style."""

    def __init__(self, max_messages: int = 30) -> None:
        self._max = max_messages
        self._messages: list[dict[str, str]] = []

    def add(self, role: str, content: str) -> None:
        self._messages.append({"role": role, "content": content})
        # Обрезаем с начала, сохраняя последние N
        if len(self._messages) > self._max:
            self._messages = self._messages[-self._max:]

    def add_user(self, text: str) -> None:
        self.add("user", text)

    def add_assistant(self, text: str) -> None:
        self.add("assistant", text)

    def add_system_event(self, text: str) -> None:
        """Внутреннее событие (результат погоды, результат selfmod) — видно LLM, скрыто от юзера."""
        self.add("system", text)

    def get_messages(self) -> list[dict[str, str]]:
        return list(self._messages)

    def __len__(self) -> int:
        return len(self._messages)


# Единый экземпляр — бот общается с одним пользователем (ADMIN)
history = ChatHistory()
