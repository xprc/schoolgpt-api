from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

import bcrypt
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

from api.core.settings import Settings, get_settings


CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL,
    email VARCHAR(120) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP NULL DEFAULT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_username (username),
    UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


@dataclass(frozen=True)
class User:
    id: int
    username: str
    email: str
    display_name: str
    is_active: bool


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _quote_mysql_identifier(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def _row_to_user(row: Mapping[str, object]) -> User:
    return User(
        id=int(row["id"]),
        username=str(row["username"]),
        email=str(row["email"]),
        display_name=str(row["display_name"]),
        is_active=bool(row["is_active"]),
    )


class UserService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ensure_mysql_database(settings.database_url)
        self._engine = create_engine(
            settings.database_url,
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
            connection.execute(text(CREATE_USERS_SQL))

        self._ensure_default_user()

    def _ensure_default_user(self) -> None:
        with self._engine.connect() as connection:
            user_count = connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one()

        if user_count > 0:
            return

        self.create_user(
            username=self._settings.default_username,
            email=self._settings.default_email,
            password=self._settings.default_password,
            display_name=self._settings.default_display_name,
        )

    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        display_name: str,
    ) -> User:
        password_hash = _hash_password(password)

        with self._engine.begin() as connection:
            cursor = connection.execute(
                text(
                    """
                    INSERT INTO users (username, email, password_hash, display_name)
                    VALUES (:username, :email, :password_hash, :display_name)
                    """
                ),
                {
                    "username": username,
                    "email": email,
                    "password_hash": password_hash,
                    "display_name": display_name,
                },
            )
            user_id = int(cursor.lastrowid or 0)

        user = self.get_user_by_id(user_id)
        if user is None:
            raise RuntimeError("User creation failed")

        return user

    def authenticate_user(self, identifier: str, password: str) -> User | None:
        normalized_identifier = identifier.strip()
        if not normalized_identifier or not password:
            return None

        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id, username, email, password_hash, display_name, is_active
                    FROM users
                    WHERE username = :identifier OR email = :identifier
                    """
                ),
                {"identifier": normalized_identifier},
            ).mappings().fetchone()

            if row is None or not bool(row["is_active"]):
                return None

            if not _verify_password(password, str(row["password_hash"])):
                return None

            connection.execute(
                text(
                    """
                    UPDATE users
                    SET last_login_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :user_id
                    """
                ),
                {"user_id": int(row["id"])},
            )

            return _row_to_user(row)

    def get_user_by_id(self, user_id: int) -> User | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id, username, email, display_name, is_active
                    FROM users
                    WHERE id = :user_id
                    """
                ),
                {"user_id": user_id},
            ).mappings().fetchone()

        if row is None:
            return None

        return _row_to_user(row)


@lru_cache(maxsize=1)
def get_user_service() -> UserService:
    return UserService(get_settings())
