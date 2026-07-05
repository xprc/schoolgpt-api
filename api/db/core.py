from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.url import make_url

from api.core.settings import get_database_url


def quote_mysql_identifier(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def ensure_mysql_database(database_url: str, *, strict: bool = False) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("mysql") or not url.database:
        if strict:
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
) -> Engine:
    resolved_database_url = database_url or get_database_url()
    if ensure_database:
        ensure_mysql_database(resolved_database_url)

    return create_engine(
        resolved_database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        future=True,
    )


def mysql_column_exists(
    connection: Connection,
    dialect_name: str,
    table_name: str,
    column_name: str,
) -> bool:
    if dialect_name != "mysql":
        return True

    count = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = :table_name
                AND COLUMN_NAME = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).scalar_one()

    return int(count) > 0


def mysql_index_exists(
    connection: Connection,
    dialect_name: str,
    table_name: str,
    index_name: str,
) -> bool:
    if dialect_name != "mysql":
        return True

    count = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = :table_name
                AND INDEX_NAME = :index_name
            """
        ),
        {"table_name": table_name, "index_name": index_name},
    ).scalar_one()

    return int(count) > 0


class Database:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        ensure_database: bool = True,
    ) -> None:
        self.engine = create_database_engine(
            database_url,
            ensure_database=ensure_database,
        )

    @property
    def dialect_name(self) -> str:
        return self.engine.dialect.name

    @contextmanager
    def begin(self) -> Iterator[Connection]:
        with self.engine.begin() as connection:
            yield connection

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        with self.engine.connect() as connection:
            yield connection

    def dispose(self) -> None:
        self.engine.dispose()
