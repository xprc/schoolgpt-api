from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import create_engine, text

from api.core.settings import get_database_url


CREATE_WEB_SEARCH_CONFIGS_SQL = """
CREATE TABLE IF NOT EXISTS web_search_configs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    provider VARCHAR(32) NOT NULL DEFAULT 'tavily',
    api_key VARCHAR(512) NOT NULL DEFAULT '',
    is_enabled TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_web_search_configs_provider (provider),
    KEY idx_web_search_configs_enabled_updated (is_enabled, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

WEB_SEARCH_PROVIDER = "tavily"
WEB_SEARCH_PROVIDER_LABEL = "Tavily"


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
        self._engine = create_engine(
            get_database_url(),
            pool_pre_ping=True,
            pool_recycle=1800,
            future=True,
        )
        self._initialize_database()

    def _initialize_database(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(text(CREATE_WEB_SEARCH_CONFIGS_SQL))
            connection.execute(
                text(
                    """
                    INSERT INTO web_search_configs (
                        provider,
                        api_key,
                        is_enabled
                    )
                    SELECT
                        :provider,
                        '',
                        TRUE
                    WHERE NOT EXISTS (
                        SELECT 1 FROM web_search_configs WHERE provider = :provider
                    )
                    """
                ),
                {"provider": WEB_SEARCH_PROVIDER},
            )

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
            self._initialize_database()
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
