from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routers import (
    appointment, auth, bad_advisor, consultation, diary, family, history, profile, sources, tracker,
)
from database.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Мой Доктор API", lifespan=lifespan)

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
