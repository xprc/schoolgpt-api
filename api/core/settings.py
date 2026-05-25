import os
from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import BaseModel


def _split_env_list(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return default

    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or default


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return float(value)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def _default_database_url() -> str:
    username = quote_plus(os.getenv("SCHOOLGPT_MYSQL_USER", "root"))
    password = quote_plus(os.getenv("SCHOOLGPT_MYSQL_PASSWORD", ""))
    host = os.getenv("SCHOOLGPT_MYSQL_HOST", "127.0.0.1")
    port = os.getenv("SCHOOLGPT_MYSQL_PORT", "3306")
    database = quote_plus(os.getenv("SCHOOLGPT_MYSQL_DATABASE", "schoolgpt"))
    credentials = f"{username}:{password}" if password else username
    return f"mysql+pymysql://{credentials}@{host}:{port}/{database}?charset=utf8mb4"


def _env_database_url() -> str:
    return os.getenv("SCHOOLGPT_DATABASE_URL", _default_database_url())


class Settings(BaseModel):
    app_name: str
    api_version: str
    api_prefix: str
    api_token: str
    auth_secret_key: str
    access_token_expire_minutes: int
    database_url: str
    default_username: str
    default_email: str
    default_password: str
    default_display_name: str
    cors_origins: tuple[str, ...]
    stream_delay_seconds: float


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("SCHOOLGPT_APP_NAME", "SchoolGPT API"),
        api_version=os.getenv("SCHOOLGPT_API_VERSION", "0.1.0"),
        api_prefix=os.getenv("SCHOOLGPT_API_PREFIX", "/api"),
        api_token=os.getenv("SCHOOLGPT_API_TOKEN", "my-super-secret-token"),
        auth_secret_key=os.getenv(
            "SCHOOLGPT_AUTH_SECRET_KEY",
            os.getenv("SCHOOLGPT_API_TOKEN", "my-super-secret-token"),
        ),
        access_token_expire_minutes=_int_env("SCHOOLGPT_ACCESS_TOKEN_EXPIRE_MINUTES", 1440),
        database_url=_env_database_url(),
        default_username=os.getenv("SCHOOLGPT_DEFAULT_USERNAME", "admin"),
        default_email=os.getenv("SCHOOLGPT_DEFAULT_EMAIL", "admin@schoolgpt.local"),
        default_password=os.getenv("SCHOOLGPT_DEFAULT_PASSWORD", "admin123456"),
        default_display_name=os.getenv("SCHOOLGPT_DEFAULT_DISPLAY_NAME", "校园百事通管理员"),
        cors_origins=_split_env_list(
            os.getenv("SCHOOLGPT_CORS_ORIGINS"),
            ("http://localhost:5173", "http://127.0.0.1:5173"),
        ),
        stream_delay_seconds=_float_env("SCHOOLGPT_STREAM_DELAY_SECONDS", 0.01),
    )
