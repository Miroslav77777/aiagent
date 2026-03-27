"""Реестр динамических плагинов.

Плагины бывают трёх типов по триггеру:
  - command:  срабатывает на /команду
  - keyword:  срабатывает если ключевое слово есть в тексте
  - regex:    срабатывает по регулярному выражению

Каждый плагин — это dict:
  {
    "name":        "joke",
    "description": "Рассказывает шутку",
    "trigger_type": "command",        # command | keyword | regex
    "trigger_value": "/joke",         # /joke | "шутка" | r"\\bшутк"
    "handler":     async def(ctx),    # async-функция
    "source":      "...",             # исходный код плагина (для персистенции)
  }
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Awaitable

from core.context import PluginContext

logger = logging.getLogger(__name__)

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"

HandlerFunc = Callable[[PluginContext], Awaitable[str | None]]


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, dict[str, Any]] = {}

    # ---------- Публичный API ----------

    @property
    def plugins(self) -> dict[str, dict[str, Any]]:
        return dict(self._plugins)

    def register(
        self,
        name: str,
        description: str,
        trigger_type: str,
        trigger_value: str,
        handler: HandlerFunc,
        source: str = "",
        persist: bool = True,
    ) -> None:
        """Зарегистрировать плагин в реестре (и опционально сохранить на диск)."""
        self._plugins[name] = {
            "name": name,
            "description": description,
            "trigger_type": trigger_type,
            "trigger_value": trigger_value,
            "handler": handler,
            "source": source,
        }
        if persist and source:
            self._save_plugin(name, source)
        logger.info("Plugin registered: %s [%s=%s]", name, trigger_type, trigger_value)

    def unregister(self, name: str) -> bool:
        """Удалить плагин из реестра и с диска."""
        if name not in self._plugins:
            return False
        del self._plugins[name]
        path = PLUGINS_DIR / f"{name}.py"
        if path.exists():
            path.unlink()
        logger.info("Plugin unregistered: %s", name)
        return True

    def list_plugins(self) -> list[dict[str, str]]:
        """Список плагинов (без handler/source — для отображения)."""
        return [
            {
                "name": p["name"],
                "description": p["description"],
                "trigger_type": p["trigger_type"],
                "trigger_value": p["trigger_value"],
            }
            for p in self._plugins.values()
        ]

    async def try_dispatch(self, ctx: PluginContext) -> bool:
        """Проверить все плагины; если один сработал — вернуть True."""
        text = ctx.text
        if not text:
            return False

        for plugin in self._plugins.values():
            if self._matches(plugin, text):
                try:
                    result = await plugin["handler"](ctx)
                    if result is not None:
                        await ctx.reply(str(result))
                except Exception:
                    logger.exception("Error in plugin %s", plugin["name"])
                    await ctx.reply(
                        f"Ошибка при выполнении плагина «{plugin['name']}»."
                    )
                return True
        return False

    # ---------- Загрузка с диска ----------

    def load_all_from_disk(self) -> int:
        """Загрузить все плагины из папки plugins/ при старте."""
        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        count = 0
        for path in sorted(PLUGINS_DIR.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                self._load_plugin_file(path)
                count += 1
            except Exception:
                logger.exception("Failed to load plugin %s", path)
        return count

    def load_from_code(self, name: str, code: str) -> None:
        """Выполнить код плагина через exec и зарегистрировать его."""
        namespace = self._make_namespace()
        exec(compile(code, f"<plugin:{name}>", "exec"), namespace)
        self._extract_and_register(namespace, code)

    def test_code(self, code: str) -> dict[str, Any]:
        """Тестовый exec — не регистрирует, только проверяет.
        Возвращает namespace или бросает исключение."""
        namespace = self._make_namespace()
        exec(compile(code, "<test>", "exec"), namespace)
        return namespace

    async def run_script(self, code: str, ctx) -> str:
        """Выполнить одноразовый скрипт. Должен определить async def run(ctx)."""
        namespace = self._make_namespace()
        exec(compile(code, "<script>", "exec"), namespace)
        run_fn = namespace.get("run")
        if run_fn is None or not callable(run_fn):
            raise ValueError("Script must define async def run(ctx)")
        result = await run_fn(ctx)
        return str(result) if result is not None else ""

    # ---------- Внутреннее ----------

    @staticmethod
    def _matches(plugin: dict[str, Any], text: str) -> bool:
        tt = plugin["trigger_type"]
        tv = plugin["trigger_value"]
        if tt == "command":
            cmd = text.split()[0] if text.startswith("/") else ""
            return cmd.lower() == tv.lower()
        if tt == "keyword":
            return tv.lower() in text.lower()
        if tt == "regex":
            return bool(re.search(tv, text, re.IGNORECASE))
        return False

    def _save_plugin(self, name: str, source: str) -> None:
        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        path = PLUGINS_DIR / f"{name}.py"
        path.write_text(source, encoding="utf-8")

    def _load_plugin_file(self, path: Path) -> None:
        code = path.read_text(encoding="utf-8")
        namespace = self._make_namespace()
        exec(compile(code, str(path), "exec"), namespace)
        self._extract_and_register(namespace, code, persist=False)

    def _extract_and_register(
        self, ns: dict, source: str, persist: bool = True
    ) -> None:
        name = ns.get("PLUGIN_NAME")
        if not name:
            raise ValueError("Plugin code must define PLUGIN_NAME")
        description = ns.get("PLUGIN_DESCRIPTION", "")
        trigger_type = ns.get("TRIGGER_TYPE", "command")
        trigger_value = ns.get("TRIGGER_VALUE", f"/{name}")
        handler = ns.get("handle")
        if handler is None or not callable(handler):
            raise ValueError("Plugin code must define async function handle(ctx)")
        self.register(
            name=name,
            description=description,
            trigger_type=trigger_type,
            trigger_value=trigger_value,
            handler=handler,
            source=source,
            persist=persist,
        )

    @staticmethod
    def _make_namespace() -> dict[str, Any]:
        """Пространство имён для exec — базовые импорты для плагинов."""
        import aiohttp
        import json
        import random
        import re as _re
        import datetime

        return {
            "__builtins__": __builtins__,
            "aiohttp": aiohttp,
            "json": json,
            "random": random,
            "re": _re,
            "datetime": datetime,
            "asyncio": __import__("asyncio"),
            "pip_install": pip_install,
            "safe_import": safe_import,
            "env_set": env_set,
            "env_get": env_get,
            "read_bot_file": read_bot_file,
            "write_bot_file": write_bot_file,
        }


def pip_install(*packages: str) -> None:
    """Установить pip-пакеты в текущее окружение.

    Вызывается синхронно на этапе загрузки плагина (верхний уровень кода).
    Пример: pip_install("beautifulsoup4", "lxml")
    """
    for pkg in packages:
        # Проверяем, что имя пакета выглядит нормально
        if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.+-]*$", pkg):
            raise ValueError(f"Недопустимое имя пакета: {pkg}")
    logger.info("pip install %s", " ".join(packages))
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--quiet", *packages],
        timeout=120,
    )


def safe_import(module_name: str):
    """Импортировать модуль по имени (после pip_install).

    Пример: bs4 = safe_import("bs4")
    """
    return importlib.import_module(module_name)


# ── .env ─────────────────────────────────────────────────────────────

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def env_get(key: str, default: str = "") -> str:
    """Получить переменную окружения (сначала os.environ, потом .env файл).

    Пример: token = env_get("MY_API_KEY")
    """
    return os.environ.get(key, default)


def env_set(key: str, value: str) -> None:
    """Записать/обновить переменную в .env и сразу применить в процессе.

    Пример: env_set("MY_API_KEY", "abc123")
    """
    # Валидация ключа
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        raise ValueError(f"Недопустимое имя переменной: {key}")

    # 1. Применяем в текущий процесс немедленно
    os.environ[key] = value

    # 2. Обновляем/дописываем в .env файл
    lines: list[str] = []
    found = False

    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            # Ищем строку вида KEY=... или KEY=
            if re.match(rf"^{re.escape(key)}\s*=", line):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)

    if not found:
        lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("env_set: %s=%s", key, "***" if "key" in key.lower() or "token" in key.lower() or "secret" in key.lower() else value)


# ── Файлы бота ───────────────────────────────────────────────────────

BOT_ROOT = Path(__file__).resolve().parent.parent


def read_bot_file(relative_path: str) -> str:
    """Прочитать файл из директории бота."""
    path = (BOT_ROOT / relative_path).resolve()
    if not str(path).startswith(str(BOT_ROOT)):
        raise ValueError(f"Нельзя читать за пределами проекта: {relative_path}")
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {relative_path}")
    return path.read_text(encoding="utf-8")


def write_bot_file(relative_path: str, content: str) -> None:
    """Записать файл в директорию бота."""
    path = (BOT_ROOT / relative_path).resolve()
    if not str(path).startswith(str(BOT_ROOT)):
        raise ValueError(f"Нельзя писать за пределами проекта: {relative_path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("write_bot_file: %s (%d bytes)", relative_path, len(content))


# Глобальный singleton
registry = PluginRegistry()
