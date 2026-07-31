import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
MAX_QUESTIONS: int = int(os.getenv("MAX_QUESTIONS", "3"))
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "doctor_bot.db")
FOLLOW_UP_HOURS: float = float(os.getenv("FOLLOW_UP_HOURS", "72"))   # 3 дня по умолчанию
APPOINTMENT_ASK_HOURS: float = float(os.getenv("APPOINTMENT_ASK_HOURS", "2"))  # через сколько спросить "записались?"

# ── iOS API ──────────────────────────────────────────────────────────────────
API_JWT_SECRET: str = os.getenv("API_JWT_SECRET", "")
APPLE_BUNDLE_ID: str = os.getenv("APPLE_BUNDLE_ID", "")
DEV_LOGIN_SECRET: str = os.getenv("DEV_LOGIN_SECRET", "")
