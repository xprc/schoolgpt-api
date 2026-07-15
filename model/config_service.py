from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import text

from db.core import get_database_engine
from db.defaults import MODEL_PROVIDER_DEFAULTS
from db.schema import initialize_model_configs_schema


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
        self._engine = get_database_engine()
        initialize_model_configs_schema(self._engine)

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
