from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url

from api.core.settings import get_database_url


CREATE_MODEL_CONFIGS_SQL = """
CREATE TABLE IF NOT EXISTS model_configs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    provider VARCHAR(32) NOT NULL,
    model_name VARCHAR(120) NOT NULL,
    base_url VARCHAR(255) NOT NULL,
    api_path VARCHAR(120) NOT NULL DEFAULT '/chat/completions',
    api_key VARCHAR(512) NOT NULL DEFAULT '',
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_model_configs_active_updated (is_active, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

MODEL_PROVIDER_DEFAULTS: dict[str, dict[str, object]] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "api_path": "/chat/completions",
        "models": ("deepseek-v4-pro", "deepseek-v4-flash"),
    },
    "qwen": {
        "label": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_path": "/chat/completions",
        "models": ("qwen-plus", "qwen-max", "qwen-turbo"),
    },
}


@dataclass(frozen=True)
class ModelConfig:
    id: int
    provider: str
    provider_label: str
    model_name: str
    base_url: str
    api_path: str
    api_key: str
    is_active: bool
    created_at: str
    updated_at: str

    @property
    def cache_key(self) -> str:
        return f"{self.id}:{self.provider}:{self.model_name}:{self.base_url}:{self.updated_at}"


@dataclass(frozen=True)
class ModelProviderOption:
    provider: str
    label: str
    base_url: str
    api_path: str
    models: tuple[str, ...]


def _quote_mysql_identifier(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def _isoformat(value: object) -> str:
    if isinstance(value, datetime):
        normalized = value
    else:
        normalized = datetime.now(timezone.utc)

    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)

    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _provider_label(provider: str) -> str:
    defaults = MODEL_PROVIDER_DEFAULTS.get(provider)
    if defaults is None:
        return provider

    return str(defaults["label"])


def _row_to_model_config(row: Mapping[str, object]) -> ModelConfig:
    provider = str(row["provider"])
    return ModelConfig(
        id=int(row["id"]),
        provider=provider,
        provider_label=_provider_label(provider),
        model_name=str(row["model_name"]),
        base_url=str(row["base_url"]),
        api_path=str(row["api_path"]),
        api_key=str(row["api_key"] or ""),
        is_active=bool(row["is_active"]),
        created_at=_isoformat(row["created_at"]),
        updated_at=_isoformat(row["updated_at"]),
    )


class ModelConfigService:
    def __init__(self) -> None:
        database_url = get_database_url()
        self._ensure_mysql_database(database_url)
        self._engine = create_engine(
            database_url,
            pool_pre_ping=True,
            pool_recycle=1800,
            future=True,
        )
        self._initialize_database()

    def _ensure_mysql_database(self, database_url: str) -> None:
        url = make_url(database_url)
        if not url.drivername.startswith("mysql") or not url.database:
            return

        server_engine = create_engine(
            url.set(database=None),
            pool_pre_ping=True,
            future=True,
        )

        try:
            with server_engine.begin() as connection:
                connection.execute(
                    text(
                        "CREATE DATABASE IF NOT EXISTS "
                        f"{_quote_mysql_identifier(url.database)} "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                )
        finally:
            server_engine.dispose()

    def _initialize_database(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(text(CREATE_MODEL_CONFIGS_SQL))
            self._ensure_default_config(connection)

    def _mysql_column_exists(
        self,
        connection: Connection,
        table_name: str,
        column_name: str,
    ) -> bool:
        if self._engine.dialect.name != "mysql":
            return True

        count = connection.execute(
            text(
                """
                SELECT COUNT(*)
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                    AND TABLE_NAME = :table_name
                    AND COLUMN_NAME = :column_name
                """
            ),
            {"table_name": table_name, "column_name": column_name},
        ).scalar_one()

        return int(count) > 0

    def _ensure_api_path_column(self, connection: Connection) -> None:
        if self._mysql_column_exists(connection, "model_configs", "api_path"):
            return

        connection.execute(
            text(
                """
                ALTER TABLE model_configs
                ADD COLUMN api_path VARCHAR(120) NOT NULL DEFAULT '/chat/completions' AFTER base_url
                """
            )
        )

    def _ensure_default_config(self, connection: Connection) -> None:
        count = connection.execute(text("SELECT COUNT(*) FROM model_configs")).scalar_one()
        if int(count) > 0:
            return

        defaults = MODEL_PROVIDER_DEFAULTS["deepseek"]
        connection.execute(
            text(
                """
                INSERT INTO model_configs (
                    provider,
                    model_name,
                    base_url,
                    api_path,
                    api_key,
                    is_active
                )
                VALUES (
                    'deepseek',
                    :model_name,
                    :base_url,
                    :api_path,
                    '',
                    TRUE
                )
                """
            ),
            {
                "model_name": str(defaults["models"][0]),
                "base_url": str(defaults["base_url"]),
                "api_path": str(defaults["api_path"]),
            },
        )

    def get_provider_options(self) -> list[ModelProviderOption]:
        return [
            ModelProviderOption(
                provider=provider,
                label=str(defaults["label"]),
                base_url=str(defaults["base_url"]),
                api_path=str(defaults["api_path"]),
                models=tuple(str(model) for model in defaults["models"]),
            )
            for provider, defaults in MODEL_PROVIDER_DEFAULTS.items()
        ]

    def get_active_model_config(self) -> ModelConfig:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        id,
                        provider,
                        model_name,
                        base_url,
                        api_path,
                        api_key,
                        is_active,
                        created_at,
                        updated_at
                    FROM model_configs
                    WHERE is_active = TRUE
                    ORDER BY updated_at DESC, id DESC
                    LIMIT 1
                    """
                )
            ).mappings().fetchone()

        if row is None:
            raise RuntimeError("No active model configuration")

        return _row_to_model_config(row)

    def update_active_model_config(
        self,
        provider: str,
        model_name: str,
        base_url: str,
        api_path: str,
        api_key: str | None,
    ) -> ModelConfig:
        normalized_provider = provider.strip().lower()
        if normalized_provider not in MODEL_PROVIDER_DEFAULTS:
            raise ValueError("Invalid model provider")

        normalized_model_name = model_name.strip()
        normalized_base_url = base_url.strip().rstrip("/")
        normalized_api_path = api_path.strip() or "/chat/completions"

        if not normalized_model_name:
            raise ValueError("Model name is required")
        if not normalized_base_url:
            raise ValueError("Base URL is required")
        if not normalized_api_path.startswith("/"):
            raise ValueError("API path must start with /")

        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id, api_key
                    FROM model_configs
                    WHERE is_active = TRUE
                    ORDER BY updated_at DESC, id DESC
                    LIMIT 1
                    """
                )
            ).mappings().fetchone()

            next_api_key = api_key if api_key is not None else ""
            if row is not None and api_key is None:
                next_api_key = str(row["api_key"] or "")

            connection.execute(
                text("UPDATE model_configs SET is_active = FALSE WHERE is_active = TRUE")
            )
            connection.execute(
                text(
                    """
                    INSERT INTO model_configs (
                        provider,
                        model_name,
                        base_url,
                        api_path,
                        api_key,
                        is_active
                    )
                    VALUES (
                        :provider,
                        :model_name,
                        :base_url,
                        :api_path,
                        :api_key,
                        TRUE
                    )
                    """
                ),
                {
                    "provider": normalized_provider,
                    "model_name": normalized_model_name,
                    "base_url": normalized_base_url,
                    "api_path": normalized_api_path,
                    "api_key": next_api_key,
                },
            )

        return self.get_active_model_config()


@lru_cache(maxsize=1)
def get_model_config_service() -> ModelConfigService:
    return ModelConfigService()
