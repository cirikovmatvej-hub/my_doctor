import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.security import verify_session_token
from database.db import user_id_exists

_bearer = HTTPBearer(auto_error=True)


async def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> int:
    """Resolves the Bearer token to our internal users.id, or raises 401."""
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = verify_session_token(creds.credentials)
    except jwt.InvalidTokenError:
        raise unauthorized
    # A session token outlives the account it was issued for (180 days), and
    # the endpoints would happily write rows for a user id that no longer
    # exists — so a deleted account's token must stop working.
    if not await user_id_exists(user_id):
        raise unauthorized
    return user_id
