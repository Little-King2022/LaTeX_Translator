from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.config import settings
from app.schemas import LoginRequest, TokenResponse
from app.utils.security import create_access_token, verify_password


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    if payload.username != settings.app_username or not verify_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return TokenResponse(access_token=create_access_token(payload.username))


@router.post("/logout")
def logout() -> dict[str, bool]:
    return {"ok": True}


@router.get("/me")
def me(username: str = Depends(get_current_user)) -> dict[str, str]:
    return {"username": username}

