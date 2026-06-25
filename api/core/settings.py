import json
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETUP_CONFIG_PATH = PROJECT_ROOT / "config" / "runtime_setup.json"


class SetupRequiredError(Exception):
    pass


class FirstRunDatabaseConfig(BaseModel):
    host: str
    port: int
    username: str
    password: str
    database: str

    @property
    def database_url(self) -> str:
        username = quote_plus(self.username)
        password = quote_plus(self.password)
        database = quote_plus(self.database)
        credentials = f"{username}:{password}" if password else username
        return (
            f"mysql+pymysql://{credentials}@{self.host}:{self.port}/"
            f"{database}?charset=utf8mb4"
        )


class FirstRunSetupConfig(BaseModel):
    database: FirstRunDatabaseConfig


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


def load_setup_config() -> FirstRunSetupConfig | None:
    if not SETUP_CONFIG_PATH.exists():
        return None

    with SETUP_CONFIG_PATH.open("r", encoding="utf-8") as config_file:
        payload = json.load(config_file)

    return FirstRunSetupConfig(**payload)


def is_setup_complete() -> bool:
    return load_setup_config() is not None


def save_setup_config(database_config: FirstRunDatabaseConfig) -> None:
    SETUP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "database": {
            "host": database_config.host,
            "port": database_config.port,
            "username": database_config.username,
            "password": database_config.password,
            "database": database_config.database,
        }
    }
    with SETUP_CONFIG_PATH.open("w", encoding="utf-8") as config_file:
        json.dump(payload, config_file, ensure_ascii=False, indent=2)
        config_file.write("\n")


def get_database_url() -> str:
    setup_config = load_setup_config()
    if setup_config is None:
        raise SetupRequiredError("首次运行配置未完成")

    return setup_config.database.database_url


class Settings(BaseModel):
    app_name: str
    api_version: str
    api_prefix: str
    api_token: str
    auth_secret_key: str
    access_token_expire_minutes: int
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
        cors_origins=_split_env_list(
            os.getenv("SCHOOLGPT_CORS_ORIGINS"),
            ("http://localhost:5173", "http://127.0.0.1:5173"),
        ),
        stream_delay_seconds=_float_env("SCHOOLGPT_STREAM_DELAY_SECONDS", 0.01),
    )
