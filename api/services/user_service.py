from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256

import bcrypt
from sqlalchemy import text

from db.core import get_database_engine
from db.schema import initialize_users_schema

VALID_USER_TYPES = {"student", "teacher", "maintenance", "admin"}
VALID_PREFERRED_LANGUAGES = {"en", "zh"}
VALID_LIGHT_BACKGROUNDS = {
    "/backgrounds/light-1.jpg",
    "/backgrounds/light-2.jpg",
    "/backgrounds/light-3.jpg",
}
VALID_DARK_BACKGROUNDS = {
    "/backgrounds/dark-1.jpg",
    "/backgrounds/dark-2.jpg",
}
DEFAULT_PREFERRED_LANGUAGE = "zh"
DEFAULT_LIGHT_BACKGROUND = "/backgrounds/light-1.jpg"
DEFAULT_DARK_BACKGROUND = "/backgrounds/dark-1.jpg"


@dataclass(frozen=True)
class User:
    id: int
    username: str
    email: str
    avatar_sha256: str
    display_name: str
    user_type: str
    preferred_language: str
    light_background: str
    dark_background: str
    is_active: bool


@dataclass(frozen=True)
class AdminUser:
    id: int
    username: str
    email: str
    avatar_sha256: str
    display_name: str
    user_type: str
    is_active: bool
    created_at: str
    updated_at: str
    last_login_at: str | None


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def _email_to_avatar_sha256(email: str) -> str:
    normalized_email = email.strip().lower()
    return sha256(normalized_email.encode("utf-8")).hexdigest()


def _isoformat(value: object) -> str:
    if isinstance(value, datetime):
        normalized = value
    else:
        normalized = datetime.now(timezone.utc)

    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)

    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _isoformat_optional(value: object) -> str | None:
    if value is None:
        return None

    return _isoformat(value)


def _normalize_user_type(user_type: str | None) -> str:
    normalized_user_type = (user_type or "").strip().lower()
    if normalized_user_type not in VALID_USER_TYPES:
        raise ValueError("Invalid user type")

    return normalized_user_type


def _normalize_preferred_language(preferred_language: str | None) -> str:
    normalized_language = (preferred_language or DEFAULT_PREFERRED_LANGUAGE).strip().lower()
    if normalized_language not in VALID_PREFERRED_LANGUAGES:
        raise ValueError("Invalid preferred language")

    return normalized_language


def _normalize_background(
    background: str | None,
    allowed_backgrounds: set[str],
    default_background: str,
) -> str:
    normalized_background = (background or default_background).strip()
    if normalized_background not in allowed_backgrounds:
        raise ValueError("Invalid background")

    return normalized_background


def _row_to_user(row: Mapping[str, object]) -> User:
    return User(
        id=int(row["id"]),
        username=str(row["username"]),
        email=str(row["email"]),
        avatar_sha256=str(row["avatar_sha256"]),
        display_name=str(row["display_name"]),
        user_type=str(row.get("user_type") or "student"),
        preferred_language=str(row.get("preferred_language") or DEFAULT_PREFERRED_LANGUAGE),
        light_background=str(row.get("light_background") or DEFAULT_LIGHT_BACKGROUND),
        dark_background=str(row.get("dark_background") or DEFAULT_DARK_BACKGROUND),
        is_active=bool(row["is_active"]),
    )


def _row_to_admin_user(row: Mapping[str, object]) -> AdminUser:
    return AdminUser(
        id=int(row["id"]),
        username=str(row["username"]),
        email=str(row["email"]),
        avatar_sha256=str(row["avatar_sha256"]),
        display_name=str(row["display_name"]),
        user_type=str(row["user_type"]),
        is_active=bool(row["is_active"]),
        created_at=_isoformat(row["created_at"]),
        updated_at=_isoformat(row["updated_at"]),
        last_login_at=_isoformat_optional(row["last_login_at"]),
    )


class UserService:
    def __init__(self) -> None:
        self._engine = get_database_engine()
        initialize_users_schema(self._engine)

    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        display_name: str,
        user_type: str = "student",
    ) -> User:
        password_hash = _hash_password(password)
        avatar_sha256 = _email_to_avatar_sha256(email)
        normalized_user_type = _normalize_user_type(user_type)

        with self._engine.begin() as connection:
            cursor = connection.execute(
                text(
                    """
                    INSERT INTO users (
                        username,
                        email,
                        avatar_sha256,
                        password_hash,
                        display_name,
                        user_type
                    )
                    VALUES (
                        :username,
                        :email,
                        :avatar_sha256,
                        :password_hash,
                        :display_name,
                        :user_type
                    )
                    """
                ),
                {
                    "username": username,
                    "email": email,
                    "avatar_sha256": avatar_sha256,
                    "password_hash": password_hash,
                    "display_name": display_name,
                    "user_type": normalized_user_type,
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
                    SELECT
                        id,
                        username,
                        email,
                        avatar_sha256,
                        password_hash,
                        display_name,
                        user_type,
                        preferred_language,
                        light_background,
                        dark_background,
                        is_active
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
                    SELECT
                        id,
                        username,
                        email,
                        avatar_sha256,
                        display_name,
                        user_type,
                        preferred_language,
                        light_background,
                        dark_background,
                        is_active
                    FROM users
                    WHERE id = :user_id
                    """
                ),
                {"user_id": user_id},
            ).mappings().fetchone()

        if row is None:
            return None

        return _row_to_user(row)

    def update_user_preferences(
        self,
        user_id: int,
        preferred_language: str,
        light_background: str,
        dark_background: str,
    ) -> User | None:
        normalized_language = _normalize_preferred_language(preferred_language)
        normalized_light_background = _normalize_background(
            light_background,
            VALID_LIGHT_BACKGROUNDS,
            DEFAULT_LIGHT_BACKGROUND,
        )
        normalized_dark_background = _normalize_background(
            dark_background,
            VALID_DARK_BACKGROUNDS,
            DEFAULT_DARK_BACKGROUND,
        )

        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE users
                    SET preferred_language = :preferred_language,
                        light_background = :light_background,
                        dark_background = :dark_background,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :user_id
                    """
                ),
                {
                    "user_id": user_id,
                    "preferred_language": normalized_language,
                    "light_background": normalized_light_background,
                    "dark_background": normalized_dark_background,
                },
            )
            if result.rowcount == 0:
                return None

        return self.get_user_by_id(user_id)

    def list_admin_users(self) -> list[AdminUser]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        id,
                        username,
                        email,
                        avatar_sha256,
                        display_name,
                        user_type,
                        is_active,
                        created_at,
                        updated_at,
                        last_login_at
                    FROM users
                    ORDER BY created_at DESC, id DESC
                    LIMIT 500
                    """
                )
            ).mappings().fetchall()

        return [_row_to_admin_user(row) for row in rows]

    def create_admin_user(
        self,
        username: str,
        email: str,
        password: str,
        display_name: str,
        user_type: str,
        is_active: bool,
    ) -> AdminUser:
        user = self.create_user(
            username=username.strip(),
            email=email.strip(),
            password=password,
            display_name=display_name.strip(),
            user_type=user_type,
        )
        self.update_admin_user(
            user_id=user.id,
            username=user.username,
            email=user.email,
            display_name=user.display_name,
            user_type=user.user_type,
            is_active=is_active,
        )
        admin_user = self.get_admin_user_by_id(user.id)
        if admin_user is None:
            raise RuntimeError("User creation failed")

        return admin_user

    def get_admin_user_by_id(self, user_id: int) -> AdminUser | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        id,
                        username,
                        email,
                        avatar_sha256,
                        display_name,
                        user_type,
                        is_active,
                        created_at,
                        updated_at,
                        last_login_at
                    FROM users
                    WHERE id = :user_id
                    """
                ),
                {"user_id": user_id},
            ).mappings().fetchone()

        if row is None:
            return None

        return _row_to_admin_user(row)

    def update_admin_user(
        self,
        user_id: int,
        username: str,
        email: str,
        display_name: str,
        user_type: str,
        is_active: bool,
    ) -> AdminUser | None:
        normalized_user_type = _normalize_user_type(user_type)
        avatar_sha256 = _email_to_avatar_sha256(email)

        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE users
                    SET username = :username,
                        email = :email,
                        avatar_sha256 = :avatar_sha256,
                        display_name = :display_name,
                        user_type = :user_type,
                        is_active = :is_active,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :user_id
                    """
                ),
                {
                    "user_id": user_id,
                    "username": username.strip(),
                    "email": email.strip(),
                    "avatar_sha256": avatar_sha256,
                    "display_name": display_name.strip(),
                    "user_type": normalized_user_type,
                    "is_active": is_active,
                },
            )
            if result.rowcount == 0:
                return None

        return self.get_admin_user_by_id(user_id)

    def update_admin_user_password(self, user_id: int, password: str) -> bool:
        password_hash = _hash_password(password)
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE users
                    SET password_hash = :password_hash,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :user_id
                    """
                ),
                {"user_id": user_id, "password_hash": password_hash},
            )

        return result.rowcount > 0

    def get_user_type_counts(self) -> dict[str, int]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT user_type, COUNT(*) AS user_count
                    FROM users
                    GROUP BY user_type
                    """
                )
            ).mappings().fetchall()

        counts = {user_type: 0 for user_type in VALID_USER_TYPES}
        for row in rows:
            counts[str(row["user_type"])] = int(row["user_count"])

        return counts

    def get_user_totals(self) -> dict[str, int]:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS total_users,
                        SUM(CASE WHEN is_active THEN 1 ELSE 0 END) AS active_users
                    FROM users
                    """
                )
            ).mappings().one()

        return {
            "total_users": int(row["total_users"] or 0),
            "active_users": int(row["active_users"] or 0),
        }


@lru_cache(maxsize=1)
def get_user_service() -> UserService:
    return UserService()
