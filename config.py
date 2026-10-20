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

# ── Web app (email sign-in) ──────────────────────────────────────────────────
# SMTP account the one-time codes are sent from. Port 465 = implicit TLS, any
# other port = STARTTLS. Leave SMTP_HOST empty to disable sending (the request
# endpoint then answers 503) — except with WEB_DEV_PRINT_CODES=true, which logs
# the code to the server log instead and must never be set in production.
SMTP_HOST: str = os.getenv("SMTP_HOST", "")
SMTP_PORT: int = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER: str = os.getenv("SMTP_USER", "")
SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM: str = os.getenv("SMTP_FROM", SMTP_USER)
WEB_DEV_PRINT_CODES: bool = os.getenv("WEB_DEV_PRINT_CODES", "false").lower() == "true"
# Set true only when the API sits behind a reverse proxy that overwrites
# X-Forwarded-For (Caddy/nginx do) — the per-IP limits then use the real client IP.
TRUST_PROXY_HEADERS: bool = os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true"
# Cap on consultation messages one account can send per day — the model calls cost money.
WEB_DAILY_MESSAGE_LIMIT: int = int(os.getenv("WEB_DAILY_MESSAGE_LIMIT", "100"))
# Serve /docs and /openapi.json (off by default on a public deployment).
API_DOCS_ENABLED: bool = os.getenv("API_DOCS_ENABLED", "false").lower() == "true"

# ── Admin ──────────────────────────────────────────────────────────────────
# Telegram user ids allowed to run /stats. Comma-separated in the env var —
# defaults to the owner's own id (from local testing) so it works out of the
# box, but override ADMIN_TELEGRAM_IDS in .env for the real deployment.
ADMIN_TELEGRAM_IDS: set[int] = {
    int(x) for x in os.getenv("ADMIN_TELEGRAM_IDS", "608451729").split(",") if x.strip()
}
