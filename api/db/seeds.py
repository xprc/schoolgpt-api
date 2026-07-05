from sqlalchemy import text
from sqlalchemy.engine import Connection

from api.db.defaults import MODEL_PROVIDER_DEFAULTS, WEB_SEARCH_PROVIDER


def ensure_default_model_config(connection: Connection) -> None:
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
            SELECT
                'deepseek',
                :model_name,
                :base_url,
                :api_path,
                '',
                TRUE
            WHERE NOT EXISTS (
                SELECT 1 FROM model_configs LIMIT 1
            )
            """
        ),
        {
            "model_name": str(defaults["models"][0]),
            "base_url": str(defaults["base_url"]),
            "api_path": str(defaults["api_path"]),
        },
    )


def ensure_default_web_search_config(connection: Connection) -> None:
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
