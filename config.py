import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_MAX_RETRIES: int = int(os.getenv("GROQ_MAX_RETRIES", "4"))
MAX_QUESTIONS: int = int(os.getenv("MAX_QUESTIONS", "12"))
MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))
UPLOAD_COOLDOWN_SECONDS: float = float(os.getenv("UPLOAD_COOLDOWN_SECONDS", "15"))
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "doctor_bot.db")
FOLLOW_UP_HOURS: float = float(os.getenv("FOLLOW_UP_HOURS", "72"))   # 3 дня по умолчанию
APPOINTMENT_ASK_HOURS: float = float(os.getenv("APPOINTMENT_ASK_HOURS", "2"))  # через сколько спросить "записались?"

# Временно отключено — фокус сейчас на подборе БАД, а не на рекомендациях врача.
# Логика (doctor_specialty, ссылки, follow-up) остаётся в коде нетронутой,
# просто не показывается/не планируется, пока флаг False.
SHOW_DOCTOR_RECOMMENDATIONS: bool = os.getenv("SHOW_DOCTOR_RECOMMENDATIONS", "false").lower() == "true"

# ── iOS API ──────────────────────────────────────────────────────────────────
API_JWT_SECRET: str = os.getenv("API_JWT_SECRET", "")
APPLE_BUNDLE_ID: str = os.getenv("APPLE_BUNDLE_ID", "")
DEV_LOGIN_SECRET: str = os.getenv("DEV_LOGIN_SECRET", "")

# ── Admin ──────────────────────────────────────────────────────────────────
# Telegram user ids allowed to run /stats. Comma-separated in the env var —
# defaults to the owner's own id (from local testing) so it works out of the
# box, but override ADMIN_TELEGRAM_IDS in .env for the real deployment.
ADMIN_TELEGRAM_IDS: set[int] = {
    int(x) for x in os.getenv("ADMIN_TELEGRAM_IDS", "608451729").split(",") if x.strip()
}
