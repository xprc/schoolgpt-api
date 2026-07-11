from sqlalchemy import text
from sqlalchemy.engine import Connection

from api.db.defaults import (
    DEFAULT_MODEL_PROVIDER,
    MODEL_PROVIDER_DEFAULTS,
    PADDLE_OCR_MODEL,
    PADDLE_OCR_PROVIDER,
    WEB_SEARCH_PROVIDER,
)


def seed_default_model_config(connection: Connection) -> None:
    defaults = MODEL_PROVIDER_DEFAULTS[DEFAULT_MODEL_PROVIDER]
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
                :provider,
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
            "provider": DEFAULT_MODEL_PROVIDER,
            "model_name": str(defaults["models"][0]),
            "base_url": str(defaults["base_url"]),
            "api_path": str(defaults["api_path"]),
        },
    )


def seed_default_web_search_config(connection: Connection) -> None:
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


def seed_default_paddle_ocr_config(connection: Connection) -> None:
    connection.execute(
        text(
            """
            INSERT INTO paddle_ocr_configs (provider, api_key, model_name)
            SELECT :provider, '', :model_name
            WHERE NOT EXISTS (
                SELECT 1 FROM paddle_ocr_configs WHERE provider = :provider
            )
            """
        ),
        {
            "provider": PADDLE_OCR_PROVIDER,
            "model_name": PADDLE_OCR_MODEL,
        },
    )
