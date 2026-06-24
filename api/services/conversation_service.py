from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url

from api.core.settings import Settings, get_settings
from api.schemas.chat import ChatMessagePayload, ConversationShareScope
from api.services.user_service import CREATE_USERS_SQL


CREATE_CONVERSATIONS_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id CHAR(36) NOT NULL,
    owner_user_id BIGINT UNSIGNED NOT NULL,
    title VARCHAR(255) NOT NULL,
    share_scope VARCHAR(16) NOT NULL DEFAULT 'private',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_conversations_owner_updated (owner_user_id, updated_at),
    CONSTRAINT fk_conversations_owner
        FOREIGN KEY (owner_user_id) REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

CREATE_CONVERSATION_MESSAGES_SQL = """
CREATE TABLE IF NOT EXISTS conversation_messages (
    id CHAR(36) NOT NULL,
    conversation_id CHAR(36) NOT NULL,
    role VARCHAR(16) NOT NULL,
    content MEDIUMTEXT NOT NULL,
    position INT UNSIGNED NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_conversation_messages_position (conversation_id, position),
    KEY idx_conversation_messages_conversation (conversation_id),
    CONSTRAINT fk_conversation_messages_conversation
        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

CREATE_CONVERSATION_PERMISSIONS_SQL = """
CREATE TABLE IF NOT EXISTS conversation_permissions (
    conversation_id CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    permission VARCHAR(16) NOT NULL DEFAULT 'read',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (conversation_id, user_id),
    KEY idx_conversation_permissions_user (user_id),
    CONSTRAINT fk_conversation_permissions_conversation
        FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_conversation_permissions_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

VALID_SHARE_SCOPES = {"private", "link_read", "link_write"}
VALID_PERMISSIONS = {"read", "write"}
DEFAULT_TITLE = "新对话"


class ConversationNotFoundError(Exception):
    pass


class ConversationPermissionError(Exception):
    pass


@dataclass(frozen=True)
class ConversationMessage:
    id: str
    role: str
    content: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ConversationData:
    id: str
    title: str
    owner_user_id: int
    share_scope: str
    permission: str
    can_write: bool
    created_at: str
    updated_at: str
    messages: list[ConversationMessage]


@dataclass(frozen=True)
class ConversationSummary:
    id: str
    title: str
    share_scope: str
    permission: str
    can_write: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ConversationAccess:
    permission: str
    can_write: bool


def _quote_mysql_identifier(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def _ensure_uuid(value: str | None) -> str:
    if not value:
        return str(uuid4())

    return str(UUID(value))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _isoformat(value: object) -> str:
    if isinstance(value, datetime):
        normalized = value
    else:
        normalized = _now_utc()

    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)

    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_title(title: str | None, messages: Sequence[ChatMessagePayload] = ()) -> str:
    normalized_title = (title or "").strip()
    if normalized_title:
        return normalized_title[:255]

    for message in messages:
        if message.role == "user":
            content = " ".join(message.content.split())
            if content:
                return content[:60]

    return DEFAULT_TITLE


def _normalize_share_scope(share_scope: str | None) -> str:
    if share_scope in VALID_SHARE_SCOPES:
        return share_scope

    return "private"


def _normalize_permission(permission: object) -> str | None:
    if isinstance(permission, str) and permission in VALID_PERMISSIONS:
        return permission

    return None


def _resolve_access(row: Mapping[str, object], user_id: int) -> ConversationAccess:
    if int(row["owner_user_id"]) == user_id:
        return ConversationAccess(permission="owner", can_write=True)

    user_permission = _normalize_permission(row.get("user_permission"))
    if user_permission == "write":
        return ConversationAccess(permission="write", can_write=True)
    if user_permission == "read":
        return ConversationAccess(permission="read", can_write=False)

    share_scope = str(row["share_scope"])
    if share_scope == "link_write":
        return ConversationAccess(permission="write", can_write=True)
    if share_scope == "link_read":
        return ConversationAccess(permission="read", can_write=False)

    raise ConversationNotFoundError()


class ConversationService:
    def __init__(self, settings: Settings) -> None:
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
            connection.execute(text(CREATE_CONVERSATIONS_SQL))
            connection.execute(text(CREATE_CONVERSATION_MESSAGES_SQL))
            connection.execute(text(CREATE_CONVERSATION_PERMISSIONS_SQL))

    def _fetch_conversation_row(
        self,
        connection: Connection,
        conversation_id: str,
        user_id: int,
    ) -> Mapping[str, object] | None:
        return connection.execute(
            text(
                """
                SELECT
                    c.id,
                    c.owner_user_id,
                    c.title,
                    c.share_scope,
                    c.created_at,
                    c.updated_at,
                    cp.permission AS user_permission
                FROM conversations c
                LEFT JOIN conversation_permissions cp
                    ON cp.conversation_id = c.id
                    AND cp.user_id = :user_id
                WHERE c.id = :conversation_id
                """
            ),
            {"conversation_id": conversation_id, "user_id": user_id},
        ).mappings().fetchone()

    def _read_messages(
        self,
        connection: Connection,
        conversation_id: str,
    ) -> list[ConversationMessage]:
        rows = connection.execute(
            text(
                """
                SELECT id, role, content, created_at, updated_at
                FROM conversation_messages
                WHERE conversation_id = :conversation_id
                ORDER BY position ASC, created_at ASC
                """
            ),
            {"conversation_id": conversation_id},
        ).mappings().fetchall()

        return [
            ConversationMessage(
                id=str(row["id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=_isoformat(row["created_at"]),
                updated_at=_isoformat(row["updated_at"]),
            )
            for row in rows
        ]

    def _to_conversation_data(
        self,
        connection: Connection,
        row: Mapping[str, object],
        access: ConversationAccess,
    ) -> ConversationData:
        conversation_id = str(row["id"])
        return ConversationData(
            id=conversation_id,
            title=str(row["title"]),
            owner_user_id=int(row["owner_user_id"]),
            share_scope=str(row["share_scope"]),
            permission=access.permission,
            can_write=access.can_write,
            created_at=_isoformat(row["created_at"]),
            updated_at=_isoformat(row["updated_at"]),
            messages=self._read_messages(connection, conversation_id),
        )

    def list_conversations(self, user_id: int) -> list[ConversationSummary]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        c.id,
                        c.owner_user_id,
                        c.title,
                        c.share_scope,
                        c.created_at,
                        c.updated_at,
                        cp.permission AS user_permission
                    FROM conversations c
                    LEFT JOIN conversation_permissions cp
                        ON cp.conversation_id = c.id
                        AND cp.user_id = :user_id
                    WHERE c.owner_user_id = :user_id OR cp.user_id = :user_id
                    ORDER BY c.updated_at DESC
                    LIMIT 100
                    """
                ),
                {"user_id": user_id},
            ).mappings().fetchall()

        summaries: list[ConversationSummary] = []
        for row in rows:
            access = _resolve_access(row, user_id)
            summaries.append(
                ConversationSummary(
                    id=str(row["id"]),
                    title=str(row["title"]),
                    share_scope=str(row["share_scope"]),
                    permission=access.permission,
                    can_write=access.can_write,
                    created_at=_isoformat(row["created_at"]),
                    updated_at=_isoformat(row["updated_at"]),
                )
            )

        return summaries

    def get_conversation(self, conversation_id: str, user_id: int) -> ConversationData:
        normalized_id = _ensure_uuid(conversation_id)
        with self._engine.connect() as connection:
            row = self._fetch_conversation_row(connection, normalized_id, user_id)
            if row is None:
                raise ConversationNotFoundError()

            access = _resolve_access(row, user_id)
            return self._to_conversation_data(connection, row, access)

    def save_conversation(
        self,
        conversation_id: str,
        user_id: int,
        title: str | None,
        share_scope: ConversationShareScope | None,
        messages: Sequence[ChatMessagePayload],
    ) -> ConversationData:
        normalized_id = _ensure_uuid(conversation_id)
        now = _now_utc()

        with self._engine.begin() as connection:
            row = self._fetch_conversation_row(connection, normalized_id, user_id)
            if row is None:
                normalized_share_scope = _normalize_share_scope(share_scope)
                connection.execute(
                    text(
                        """
                        INSERT INTO conversations (
                            id,
                            owner_user_id,
                            title,
                            share_scope,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :conversation_id,
                            :user_id,
                            :title,
                            :share_scope,
                            :now,
                            :now
                        )
                        """
                    ),
                    {
                        "conversation_id": normalized_id,
                        "user_id": user_id,
                        "title": _clean_title(title, messages),
                        "share_scope": normalized_share_scope,
                        "now": now,
                    },
                )
            else:
                access = _resolve_access(row, user_id)
                if not access.can_write:
                    raise ConversationPermissionError()

                next_share_scope = str(row["share_scope"])
                if share_scope is not None:
                    if access.permission != "owner":
                        raise ConversationPermissionError()
                    next_share_scope = _normalize_share_scope(share_scope)

                connection.execute(
                    text(
                        """
                        UPDATE conversations
                        SET title = :title,
                            share_scope = :share_scope,
                            updated_at = :now
                        WHERE id = :conversation_id
                        """
                    ),
                    {
                        "conversation_id": normalized_id,
                        "title": _clean_title(title, messages),
                        "share_scope": next_share_scope,
                        "now": now,
                    },
                )

            connection.execute(
                text(
                    """
                    DELETE FROM conversation_messages
                    WHERE conversation_id = :conversation_id
                    """
                ),
                {"conversation_id": normalized_id},
            )

            for position, message in enumerate(messages):
                connection.execute(
                    text(
                        """
                        INSERT INTO conversation_messages (
                            id,
                            conversation_id,
                            role,
                            content,
                            position,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :message_id,
                            :conversation_id,
                            :role,
                            :content,
                            :position,
                            :now,
                            :now
                        )
                        """
                    ),
                    {
                        "message_id": _ensure_uuid(message.id),
                        "conversation_id": normalized_id,
                        "role": message.role,
                        "content": message.content,
                        "position": position,
                        "now": now,
                    },
                )

        return self.get_conversation(normalized_id, user_id)

    def append_generated_exchange(
        self,
        conversation_id: str,
        user_id: int,
        query: str,
        ai_content: str,
        message_id: str | None,
        response_id: str | None,
    ) -> None:
        normalized_id = _ensure_uuid(conversation_id)
        now = _now_utc()

        with self._engine.begin() as connection:
            row = self._fetch_conversation_row(connection, normalized_id, user_id)
            if row is None:
                connection.execute(
                    text(
                        """
                        INSERT INTO conversations (
                            id,
                            owner_user_id,
                            title,
                            share_scope,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :conversation_id,
                            :user_id,
                            :title,
                            'private',
                            :now,
                            :now
                        )
                        """
                    ),
                    {
                        "conversation_id": normalized_id,
                        "user_id": user_id,
                        "title": _clean_title(query),
                        "now": now,
                    },
                )
            else:
                access = _resolve_access(row, user_id)
                if not access.can_write:
                    raise ConversationPermissionError()

            next_position = int(
                connection.execute(
                    text(
                        """
                        SELECT COALESCE(MAX(position) + 1, 0)
                        FROM conversation_messages
                        WHERE conversation_id = :conversation_id
                        """
                    ),
                    {"conversation_id": normalized_id},
                ).scalar_one()
            )
            self._upsert_message(
                connection,
                conversation_id=normalized_id,
                message_id=_ensure_uuid(message_id),
                role="user",
                content=query,
                position=next_position,
                now=now,
            )
            self._upsert_message(
                connection,
                conversation_id=normalized_id,
                message_id=_ensure_uuid(response_id),
                role="ai",
                content=ai_content,
                position=next_position + 1,
                now=now,
            )
            connection.execute(
                text(
                    """
                    UPDATE conversations
                    SET title = CASE
                            WHEN title = :default_title THEN :title
                            ELSE title
                        END,
                        updated_at = :now
                    WHERE id = :conversation_id
                    """
                ),
                {
                    "conversation_id": normalized_id,
                    "default_title": DEFAULT_TITLE,
                    "title": _clean_title(query),
                    "now": now,
                },
            )

    def _upsert_message(
        self,
        connection: Connection,
        conversation_id: str,
        message_id: str,
        role: str,
        content: str,
        position: int,
        now: datetime,
    ) -> None:
        connection.execute(
            text(
                """
                INSERT INTO conversation_messages (
                    id,
                    conversation_id,
                    role,
                    content,
                    position,
                    created_at,
                    updated_at
                )
                VALUES (
                    :message_id,
                    :conversation_id,
                    :role,
                    :content,
                    :position,
                    :now,
                    :now
                )
                ON DUPLICATE KEY UPDATE
                    role = VALUES(role),
                    content = VALUES(content),
                    updated_at = VALUES(updated_at)
                """
            ),
            {
                "message_id": message_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "position": position,
                "now": now,
            },
        )

    def update_share_scope(
        self,
        conversation_id: str,
        user_id: int,
        share_scope: ConversationShareScope,
    ) -> ConversationData:
        normalized_id = _ensure_uuid(conversation_id)
        normalized_share_scope = _normalize_share_scope(share_scope)
        now = _now_utc()

        with self._engine.begin() as connection:
            row = self._fetch_conversation_row(connection, normalized_id, user_id)
            if row is None:
                raise ConversationNotFoundError()

            access = _resolve_access(row, user_id)
            if access.permission != "owner":
                raise ConversationPermissionError()

            connection.execute(
                text(
                    """
                    UPDATE conversations
                    SET share_scope = :share_scope,
                        updated_at = :now
                    WHERE id = :conversation_id
                    """
                ),
                {
                    "conversation_id": normalized_id,
                    "share_scope": normalized_share_scope,
                    "now": now,
                },
            )

        return self.get_conversation(normalized_id, user_id)


@lru_cache(maxsize=1)
def get_conversation_service() -> ConversationService:
    return ConversationService(get_settings())
