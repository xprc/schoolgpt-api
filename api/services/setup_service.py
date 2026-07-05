from sqlalchemy import text

from api.core.settings import (
    FirstRunDatabaseConfig,
    is_setup_complete,
    save_setup_config,
)
from api.db.core import create_database_engine, ensure_mysql_database
from api.db.schema import create_schema
from api.db.seeds import (
    ensure_default_model_config,
    ensure_default_web_search_config,
)
from api.schemas.setup import FirstRunSetupRequest
from api.services.user_service import (
    _email_to_avatar_sha256,
    _hash_password,
)


class SetupAlreadyCompleteError(Exception):
    pass


def _to_database_config(request: FirstRunSetupRequest) -> FirstRunDatabaseConfig:
    return FirstRunDatabaseConfig(
        host=request.database.host.strip(),
        port=request.database.port,
        username=request.database.username.strip(),
        password=request.database.password,
        database=request.database.database.strip(),
    )


def initialize_first_run(request: FirstRunSetupRequest) -> None:
    if is_setup_complete():
        raise SetupAlreadyCompleteError()

    database_config = _to_database_config(request)
    database_url = database_config.database_url
    ensure_mysql_database(database_url, strict=True)

    engine = create_database_engine(database_url, ensure_database=False)
    try:
        with engine.begin() as connection:
            create_schema(connection)
            ensure_default_model_config(connection)
            ensure_default_web_search_config(connection)
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
