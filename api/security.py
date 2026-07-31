"""
Auth for the iOS API.

Two distinct JWTs are involved:
  - Apple's identity token — sent by the app after Sign in with Apple, verified
    here against Apple's public JWKS.
  - Our own session token — issued after Apple verification succeeds, HS256
    signed with API_JWT_SECRET, sent back on every subsequent request.
"""
import time

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from config import API_JWT_SECRET, APPLE_BUNDLE_ID

APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"
JWKS_CACHE_TTL = 24 * 60 * 60  # 24h

OUR_JWT_ALGORITHM = "HS256"
OUR_JWT_TTL_SECONDS = 180 * 24 * 60 * 60  # 180 days

_jwks_cache: dict | None = None
_jwks_cache_at: float = 0.0


class AppleTokenError(Exception):
    """Raised when an Apple identity token fails verification."""


async def _get_apple_jwks() -> dict:
    global _jwks_cache, _jwks_cache_at
    now = time.time()
    if _jwks_cache is not None and (now - _jwks_cache_at) < JWKS_CACHE_TTL:
        return _jwks_cache

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(APPLE_JWKS_URL)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_cache_at = now
        return _jwks_cache


async def verify_apple_identity_token(identity_token: str) -> dict:
    """Verify an Apple Sign-in identity token. Returns {"sub": ..., "email": str|None}."""
    try:
        header = jwt.get_unverified_header(identity_token)
    except jwt.InvalidTokenError as e:
        raise AppleTokenError(f"Malformed identity token: {e}") from e

    kid = header.get("kid")
    if not kid:
        raise AppleTokenError("Identity token header has no 'kid'")

    jwks = await _get_apple_jwks()
    jwk = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if jwk is None:
        # Key rotation on Apple's side — refresh once and retry.
        global _jwks_cache
        _jwks_cache = None
        jwks = await _get_apple_jwks()
        jwk = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if jwk is None:
            raise AppleTokenError(f"No matching Apple JWK for kid={kid}")

    public_key = RSAAlgorithm.from_jwk(jwk)

    try:
        payload = jwt.decode(
            identity_token,
            key=public_key,
            algorithms=["RS256"],
            audience=APPLE_BUNDLE_ID,
            issuer=APPLE_ISSUER,
        )
    except jwt.InvalidTokenError as e:
        raise AppleTokenError(f"Identity token verification failed: {e}") from e

    sub = payload.get("sub")
    if not sub:
        raise AppleTokenError("Identity token has no 'sub' claim")

    return {"sub": sub, "email": payload.get("email")}


def issue_session_token(user_id: int) -> str:
    now = int(time.time())
    payload = {"sub": str(user_id), "iat": now, "exp": now + OUR_JWT_TTL_SECONDS}
    return jwt.encode(payload, API_JWT_SECRET, algorithm=OUR_JWT_ALGORITHM)


def verify_session_token(token: str) -> int:
    """Returns the internal user_id. Raises jwt.InvalidTokenError on failure."""
    payload = jwt.decode(token, API_JWT_SECRET, algorithms=[OUR_JWT_ALGORITHM])
    return int(payload["sub"])
