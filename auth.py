"""JWT authentication — token creation, verification, and login endpoint."""
import os
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException
from fastapi.routing import APIRouter
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext

router = APIRouter()

_JWT_SECRET   = os.getenv("JWT_SECRET", "change-me-in-production")
_JWT_ALGO     = "HS256"
_JWT_EXP_MINS = 60 * 8

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_oauth2  = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

_DASH_USER = os.getenv("DASHBOARD_USER")
_DASH_PASS = os.getenv("DASHBOARD_PASS")
_DASH_HASH = _pwd_ctx.hash(_DASH_PASS) if _DASH_PASS else None


def _create_token(username: str) -> str:
    exp = datetime.utcnow() + timedelta(minutes=_JWT_EXP_MINS)
    return jwt.encode({"sub": username, "exp": exp}, _JWT_SECRET, algorithm=_JWT_ALGO)


async def require_auth(token: str = Depends(_oauth2)):
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
        if not payload.get("sub"):
            raise HTTPException(401, "Invalid token")
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")


@router.post("/api/auth/token")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    if (not _DASH_USER or not _DASH_HASH
            or form.username != _DASH_USER
            or not _pwd_ctx.verify(form.password, _DASH_HASH)):
        raise HTTPException(401, "Incorrect username or password")
    return {"access_token": _create_token(form.username), "token_type": "bearer"}
