from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url

from api.core.settings import get_database_url


def quote_mysql_identifier(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def ensure_mysql_database(database_url: str, require_mysql: bool = False) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("mysql") or not url.database:
        if require_mysql:
            raise ValueError("仅支持 MySQL 初始化")
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
                    f"{quote_mysql_identifier(url.database)} "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            )
    finally:
        server_engine.dispose()


def create_database_engine(
    database_url: str | None = None,
    *,
    ensure_database: bool = True,
    require_mysql: bool = False,
) -> Engine:
    resolved_database_url = database_url or get_database_url()
    if ensure_database:
        ensure_mysql_database(resolved_database_url, require_mysql=require_mysql)

    return create_engine(
        resolved_database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )


@lru_cache(maxsize=1)
def get_database_engine() -> Engine:
    return create_database_engine()
