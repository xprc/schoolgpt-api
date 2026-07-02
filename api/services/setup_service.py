from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

from api.core.settings import (
    FirstRunDatabaseConfig,
    is_setup_complete,
    save_setup_config,
)
from api.schemas.setup import FirstRunSetupRequest
from api.services.conversation_service import (
    CREATE_CONVERSATIONS_SQL,
    CREATE_CONVERSATION_MESSAGES_SQL,
    CREATE_CONVERSATION_PERMISSIONS_SQL,
)
from api.services.model_config_service import (
    CREATE_MODEL_CONFIGS_SQL,
    MODEL_PROVIDER_DEFAULTS,
)
from api.services.rag_file_service import CREATE_RAG_FILES_SQL
from api.services.user_memory_service import CREATE_USER_MEMORIES_SQL
from api.services.user_service import (
    CREATE_USERS_SQL,
    _email_to_avatar_sha256,
    _hash_password,
)
from api.services.web_search_config_service import CREATE_WEB_SEARCH_CONFIGS_SQL


class SetupAlreadyCompleteError(Exception):
    pass


def _quote_mysql_identifier(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def _to_database_config(request: FirstRunSetupRequest) -> FirstRunDatabaseConfig:
    return FirstRunDatabaseConfig(
        host=request.database.host.strip(),
        port=request.database.port,
        username=request.database.username.strip(),
        password=request.database.password,
        database=request.database.database.strip(),
    )


def _ensure_mysql_database(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("mysql") or not url.database:
        raise ValueError("仅支持 MySQL 初始化")

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


def initialize_first_run(request: FirstRunSetupRequest) -> None:
    if is_setup_complete():
        raise SetupAlreadyCompleteError()

    database_config = _to_database_config(request)
    database_url = database_config.database_url
    _ensure_mysql_database(database_url)

    engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )
    try:
        with engine.begin() as connection:
            connection.execute(text(CREATE_USERS_SQL))
            connection.execute(text(CREATE_CONVERSATIONS_SQL))
            connection.execute(text(CREATE_CONVERSATION_MESSAGES_SQL))
            connection.execute(text(CREATE_CONVERSATION_PERMISSIONS_SQL))
            connection.execute(text(CREATE_USER_MEMORIES_SQL))
            connection.execute(text(CREATE_MODEL_CONFIGS_SQL))
            connection.execute(text(CREATE_WEB_SEARCH_CONFIGS_SQL))
            connection.execute(text(CREATE_RAG_FILES_SQL))

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
            connection.execute(
                text(
                    """
                    INSERT INTO web_search_configs (
                        provider,
                        api_key,
                        is_enabled
                    )
                    SELECT
                        'tavily',
                        '',
                        TRUE
                    WHERE NOT EXISTS (
                        SELECT 1 FROM web_search_configs WHERE provider = 'tavily'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO users (
                        username,
                        email,
                        avatar_sha256,
                        password_hash,
                        display_name,
                        user_type,
                        is_active
                    )
                    VALUES (
                        :username,
                        :email,
                        :avatar_sha256,
                        :password_hash,
                        :display_name,
                        'admin',
                        TRUE
                    )
                    """
                ),
                {
                    "username": request.admin_username.strip(),
                    "email": request.admin_email.strip(),
                    "avatar_sha256": _email_to_avatar_sha256(request.admin_email),
                    "password_hash": _hash_password(request.admin_password),
                    "display_name": request.admin_display_name.strip(),
                },
            )
    finally:
        engine.dispose()

    save_setup_config(database_config)
