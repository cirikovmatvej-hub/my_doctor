"""The user's calendar date, as their device sees it.

Intake logs and diary entries are keyed by day. The server used to stamp them
with its own local date, which is the wrong day for a phone in another
timezone for part of every day — so the app sends its local date and the
server only sanity-checks it (a wildly wrong clock shouldn't rewrite history).
"""
from datetime import date, datetime

from fastapi import HTTPException

# Real timezone skew between server and device never exceeds a day or so;
# anything further out is a bad request, not a timezone.
MAX_SKEW_DAYS = 2


def resolve_client_date(client_date: str | None) -> str:
    today = datetime.now().date()
    if not client_date:
        return today.isoformat()
    try:
        parsed = date.fromisoformat(client_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    if abs((parsed - today).days) > MAX_SKEW_DAYS:
        raise HTTPException(status_code=400, detail="date is too far from the server date")
    return parsed.isoformat()
