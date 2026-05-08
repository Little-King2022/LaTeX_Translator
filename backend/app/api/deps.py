from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.utils.security import decode_access_token


def get_current_user(authorization: str | None = Header(default=None), token: str | None = Query(default=None)) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        raw_token = authorization.split(" ", 1)[1]
    elif token:
        raw_token = token
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    username = decode_access_token(raw_token)
    if username != settings.app_username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return username


def db_session(db: Session = Depends(get_db)) -> Session:
    return db
