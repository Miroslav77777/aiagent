import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN")

if not OPENWEATHER_API_KEY:
    raise RuntimeError("Не задан OPENWEATHER_API_KEY")

if not ADMIN_USER_ID:
    raise RuntimeError("Не задан ADMIN_USER_ID")