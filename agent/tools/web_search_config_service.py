from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import text

from db.core import get_database_engine
from db.defaults import WEB_SEARCH_PROVIDER, WEB_SEARCH_PROVIDER_LABEL
from db.schema import initialize_web_search_configs_schema


@dataclass(frozen=True)
class WebSearchConfig:
    id: int
    provider: str
    provider_label: str
    api_key: str
    is_enabled: bool
    created_at: str
    updated_at: str


def _isoformat(value: object) -> str:
    if isinstance(value, datetime):
        normalized = value
    else:
        normalized = datetime.now(timezone.utc)

    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)

    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _row_to_web_search_config(row: Mapping[str, object]) -> WebSearchConfig:
    return WebSearchConfig(
        id=int(row["id"]),
        provider=str(row["provider"]),
        provider_label=WEB_SEARCH_PROVIDER_LABEL,
        api_key=str(row["api_key"] or ""),
        is_enabled=bool(row["is_enabled"]),
        created_at=_isoformat(row["created_at"]),
        updated_at=_isoformat(row["updated_at"]),
    )


class WebSearchConfigService:
    def __init__(self) -> None:
        self._engine = get_database_engine()
        initialize_web_search_configs_schema(self._engine)

    def get_config(self) -> WebSearchConfig:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        id,
                        provider,
                        api_key,
                        is_enabled,
                        created_at,
                        updated_at
                    FROM web_search_configs
                    WHERE provider = :provider
                    LIMIT 1
                    """
                ),
                {"provider": WEB_SEARCH_PROVIDER},
            ).mappings().fetchone()

        if row is None:
            initialize_web_search_configs_schema(self._engine)
            return self.get_config()

        return _row_to_web_search_config(row)

    def update_config(
        self,
        api_key: str | None,
        is_enabled: bool,
    ) -> WebSearchConfig:
        if api_key is not None and len(api_key) > 512:
            raise ValueError("Tavily API Key 不能超过 512 个字符")

        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id, api_key
                    FROM web_search_configs
                    WHERE provider = :provider
                    LIMIT 1
                    """
                ),
                {"provider": WEB_SEARCH_PROVIDER},
            ).mappings().fetchone()

            next_api_key = api_key.strip() if api_key is not None else ""
            if row is not None and api_key is None:
                next_api_key = str(row["api_key"] or "")

            if row is None:
                connection.execute(
                    text(
                        """
                        INSERT INTO web_search_configs (
                            provider,
                            api_key,
                            is_enabled
                        )
                        VALUES (
                            :provider,
                            :api_key,
                            :is_enabled
                        )
                        """
                    ),
                    {
                        "provider": WEB_SEARCH_PROVIDER,
                        "api_key": next_api_key,
                        "is_enabled": is_enabled,
                    },
                )
            else:
                connection.execute(
                    text(
                        """
                        UPDATE web_search_configs
                        SET
                            api_key = :api_key,
                            is_enabled = :is_enabled
                        WHERE provider = :provider
                        """
                    ),
                    {
                        "provider": WEB_SEARCH_PROVIDER,
                        "api_key": next_api_key,
                        "is_enabled": is_enabled,
                    },
                )

        return self.get_config()


@lru_cache(maxsize=1)
def get_web_search_config_service() -> WebSearchConfigService:
    return WebSearchConfigService()
