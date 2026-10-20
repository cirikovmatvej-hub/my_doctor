import hashlib
import hmac
import logging
import re
import secrets
import time
from collections import deque

from fastapi import APIRouter, Header, HTTPException, Request, status

from api.mailer import MailNotConfigured, MailSendError, send_login_code
from api.schemas import AppleAuthRequest, AuthResponse, EmailRequestIn, EmailVerifyIn, OkOut
from api.security import AppleTokenError, issue_session_token, verify_apple_identity_token
from config import API_JWT_SECRET, DEV_LOGIN_SECRET, TRUST_PROXY_HEADERS
from database.db import (
    consume_email_code, get_or_create_user_by_apple_sub, get_or_create_user_by_email,
    get_user_profile_by_id, store_email_code,
)

router = APIRouter(prefix="/auth", tags=["auth"])

CODE_TTL_SECONDS = 10 * 60
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


class _IpLimiter:
    """Sliding-window hit counter per client IP, in memory (single API process).
    Protects the mail relay (one address can't be spammed — the DB cooldown does
    that — but many addresses could) and slows guessing across addresses."""

    def __init__(self, max_hits: int, window: float) -> None:
        self.max_hits, self.window = max_hits, window
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.max_hits:
            return False
        hits.append(now)
        if len(self._hits) > 10_000:  # bound memory: drop idle keys
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                del self._hits[k]
        return True


_request_limiter = _IpLimiter(max_hits=10, window=3600)
_verify_limiter = _IpLimiter(max_hits=60, window=3600)


def _client_ip(request: Request) -> str:
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()  # the entry our own proxy appended
    return request.client.host if request.client else "unknown"


def _normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Укажите корректный адрес почты")
    return email


def _code_hash(email: str, code: str) -> str:
    return hmac.new(API_JWT_SECRET.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


@router.post("/email/request", response_model=OkOut)
async def auth_email_request(body: EmailRequestIn, request: Request) -> OkOut:
    """Send a 6-digit code. Always answers the same way whether or not the
    address already has an account, so it can't be used to look people up."""
    if not API_JWT_SECRET:
        raise HTTPException(status_code=503, detail="Server is not configured")
    if not _request_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Слишком много запросов. Попробуйте позже.")
    email = _normalize_email(body.email)

    code = f"{secrets.randbelow(1_000_000):06d}"
    outcome = await store_email_code(email, _code_hash(email, code), time.time(), CODE_TTL_SECONDS)
    if outcome != "ok":
        detail = (
            "Код уже отправлен. Повторить можно через минуту." if outcome == "cooldown"
            else "Слишком много кодов для этого адреса. Попробуйте через час."
        )
        raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": "60"})
    try:
        await send_login_code(email, code, CODE_TTL_SECONDS // 60)
    except MailNotConfigured:
        raise HTTPException(status_code=503, detail="Отправка писем не настроена") from None
    except MailSendError as exc:
        logging.error("Could not send sign-in code: %s", exc)
        raise HTTPException(status_code=502, detail="Не удалось отправить письмо. Попробуйте позже.") from exc
    return OkOut()


@router.post("/email/verify", response_model=AuthResponse)
async def auth_email_verify(body: EmailVerifyIn, request: Request) -> AuthResponse:
    if not API_JWT_SECRET:
        raise HTTPException(status_code=503, detail="Server is not configured")
    if not _verify_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Слишком много попыток. Попробуйте позже.")
    email = _normalize_email(body.email)
    if not await consume_email_code(email, _code_hash(email, body.code), time.time()):
        raise HTTPException(status_code=401, detail="Неверный или просроченный код")

    user_id = await get_or_create_user_by_email(email)
    profile = await get_user_profile_by_id(user_id)
    return AuthResponse(
        access_token=issue_session_token(user_id), user_id=user_id,
        onboarding_done=bool(profile and profile.get("onboarding_done")),
    )


@router.post("/apple", response_model=AuthResponse)
async def auth_apple(body: AppleAuthRequest) -> AuthResponse:
    try:
        claims = await verify_apple_identity_token(body.identity_token)
    except AppleTokenError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    # Apple only sends the email on the user's very first authorization ever —
    # prefer the request body's copy (from that first authorization) if the
    # token itself doesn't carry it (e.g. on subsequent sign-ins).
    email = claims.get("email") or body.email

    user_id = await get_or_create_user_by_apple_sub(claims["sub"], email)
    token = issue_session_token(user_id)

    profile = await get_user_profile_by_id(user_id)
    onboarding_done = bool(profile and profile.get("onboarding_done"))

    return AuthResponse(
        access_token=token, user_id=user_id, onboarding_done=onboarding_done
    )


@router.post("/dev", response_model=AuthResponse)
async def auth_dev(x_dev_secret: str = Header(default="")) -> AuthResponse:
    """
    Bypass for Simulator/device testing, where real Apple Sign-In is either
    unreliable (Simulator 2FA) or unavailable (free personal-team builds
    can't get the Sign In with Apple capability). Gated behind a shared
    secret since this is now reachable through the Cloudflare tunnel — the
    tunnel URL is obscure but not itself an access control.
    """
    if not DEV_LOGIN_SECRET or not secrets.compare_digest(x_dev_secret, DEV_LOGIN_SECRET):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    user_id = await get_or_create_user_by_apple_sub("dev-simulator-user", None)
    token = issue_session_token(user_id)

    profile = await get_user_profile_by_id(user_id)
    onboarding_done = bool(profile and profile.get("onboarding_done"))

    return AuthResponse(
        access_token=token, user_id=user_id, onboarding_done=onboarding_done
    )
