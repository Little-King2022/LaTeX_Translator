from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_username: str = "admin"
    app_password: str = "admin"
    app_password_hash: str | None = None
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    session_expire_hours: int = 24
    database_url: str = "sqlite:///./data/app.db"
    workspace_dir: Path = Path("./workspace/tasks")
    compile_timeout_seconds: int = 300
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

