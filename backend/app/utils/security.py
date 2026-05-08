from datetime import datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_configured_password_hash() -> str:
    if settings.app_password_hash:
        return settings.app_password_hash
    return pwd_context.hash(settings.app_password)


def verify_password(plain_password: str) -> bool:
    return pwd_context.verify(plain_password, get_configured_password_hash())


def create_access_token(subject: str) -> str:
    expire = datetime.utcnow() + timedelta(hours=settings.session_expire_hours)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except JWTError:
        return None

