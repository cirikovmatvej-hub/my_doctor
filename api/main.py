from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from api.routers import (
    appointment, auth, bad_advisor, consultation, diary, family, history, profile, sources, tracker,
)
from config import API_DOCS_ENABLED
from database.db import init_db

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Scripts, styles and XHR only from our own origin: the web app stores its
# session token in localStorage, so a script injected from anywhere else is the
# thing to rule out. Links out to shops are plain navigation and unaffected.
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


# The interactive docs list every endpoint — off unless asked for (API_DOCS_ENABLED=true).
app = FastAPI(
    title="Мой Доктор API", lifespan=lifespan,
    docs_url="/docs" if API_DOCS_ENABLED else None,
    redoc_url=None,
    openapi_url="/openapi.json" if API_DOCS_ENABLED else None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.endswith((".html", ".js", ".css")) or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache"      # always revalidate, so a deploy shows up at once
    elif not request.url.path.startswith("/health"):
        response.headers["Cache-Control"] = "no-store"      # API answers hold personal health data
    return response

app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(consultation.router)
app.include_router(bad_advisor.router)
app.include_router(tracker.router)
app.include_router(diary.router)
app.include_router(family.router)
app.include_router(appointment.router)
app.include_router(history.router)
app.include_router(sources.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# Last on purpose: the web app owns "/", and every API route above must win.
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
