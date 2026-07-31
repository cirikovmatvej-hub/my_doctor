import secrets

from fastapi import APIRouter, Header, HTTPException, status

from api.schemas import AppleAuthRequest, AuthResponse
from api.security import AppleTokenError, issue_session_token, verify_apple_identity_token
from config import DEV_LOGIN_SECRET
from database.db import get_or_create_user_by_apple_sub, get_user_profile_by_id

router = APIRouter(prefix="/auth", tags=["auth"])


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
