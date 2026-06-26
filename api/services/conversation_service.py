import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url

from api.core.settings import get_database_url
from api.schemas.chat import ChatMessagePayload, ConversationShareScope
from api.services.user_service import CREATE_USERS_SQL


CREATE_CONVERSATIONS_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id CHAR(36) NOT NULL,
    owner_user_id BIGINT UNSIGNED NOT NULL,
    title VARCHAR(255) NOT NULL,
    share_scope VARCHAR(16) NOT NULL DEFAULT 'private',
    is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
    pinned_at DATETIME(6) NULL,
    is_visible BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_conversations_owner_updated (owner_user_id, updated_at),
    KEY idx_conversations_owner_visible_pinned (
        owner_user_id,
        is_visible,
        is_pinned,
        pinned_at,
        updated_at
    ),
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
    rag_sources_json JSON NULL,
    reasoning_content MEDIUMTEXT NULL,
    reasoning_duration_ms INT UNSIGNED NULL,
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
    rag_sources: list[dict[str, object]]
    reasoning_content: str | None
    reasoning_duration_ms: int | None
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
    is_pinned: bool
    pinned_at: str | None
    is_visible: bool
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
    is_pinned: bool
    pinned_at: str | None
    is_visible: bool
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class AdminConversationSummary:
    id: str
    title: str
    owner_user_id: int
    owner_username: str
    owner_email: str
    share_scope: str
    is_visible: bool
    message_count: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ConversationTotals:
    total_conversations: int
    visible_conversations: int
    total_messages: int


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


def _isoformat_optional(value: object) -> str | None:
    if value is None:
        return None

    return _isoformat(value)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, bytes):
        return value not in {b"", b"\x00", b"0"}
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}

    return bool(value)


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


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


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


def _normalize_rag_sources(
    sources: Sequence[Mapping[str, object]] | None,
) -> list[dict[str, object]]:
    if not sources:
        return []

    normalized_sources = []
    for source in sources:
        file_name = str(source.get("file_name", "")).strip()
        if not file_name:
            continue

        try:
            confidence = float(source.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            confidence = 0

        normalized_sources.append(
            {
                "file_name": file_name,
                "confidence": max(0, min(1, confidence)),
            }
        )

    return normalized_sources


def _serialize_rag_sources(
    sources: Sequence[Mapping[str, object]] | None,
) -> str | None:
    normalized_sources = _normalize_rag_sources(sources)
    if not normalized_sources:
        return None

    return json.dumps(normalized_sources, ensure_ascii=False)


def _parse_rag_sources(value: object) -> list[dict[str, object]]:
    if value is None:
        return []

    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")

    if isinstance(value, str):
        if not value.strip():
            return []

        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []

    if not isinstance(value, list):
        return []

    return _normalize_rag_sources(
        [source for source in value if isinstance(source, Mapping)]
    )


def _normalize_reasoning_content(value: object) -> str | None:
    if value is None:
        return None

    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")

    if not isinstance(value, str):
        return None

    return value if value.strip() else None


def _normalize_reasoning_duration_ms(value: object) -> int | None:
    if value is None:
        return None

    try:
        duration_ms = int(value)
    except (TypeError, ValueError):
        return None

    return max(0, duration_ms)


class ConversationService:
    def __init__(self) -> None:
        database_url = get_database_url()
        self._ensure_mysql_database(database_url)
        self._engine = create_engine(
            database_url,
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
                    c.is_pinned,
                    c.pinned_at,
                    c.is_visible,
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
                SELECT
                    id,
                    role,
                    content,
                    rag_sources_json,
                    reasoning_content,
                    reasoning_duration_ms,
                    created_at,
                    updated_at
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
                rag_sources=_parse_rag_sources(row["rag_sources_json"]),
                reasoning_content=_normalize_reasoning_content(
                    row["reasoning_content"],
                ),
                reasoning_duration_ms=_normalize_reasoning_duration_ms(
                    row["reasoning_duration_ms"],
                ),
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
            is_pinned=_as_bool(row["is_pinned"]),
            pinned_at=_isoformat_optional(row["pinned_at"]),
            is_visible=_as_bool(row["is_visible"]),
            created_at=_isoformat(row["created_at"]),
            updated_at=_isoformat(row["updated_at"]),
            messages=self._read_messages(connection, conversation_id),
        )

    def list_conversations(
        self,
        user_id: int,
        search_query: str | None = None,
    ) -> list[ConversationSummary]:
        normalized_query = " ".join((search_query or "").split())
        has_query = bool(normalized_query)
        query_like = f"%{_escape_like(normalized_query)}%" if has_query else "%"

        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        c.id,
                        c.owner_user_id,
                        c.title,
                        c.share_scope,
                        c.is_pinned,
                        c.pinned_at,
                        c.is_visible,
                        c.created_at,
                        c.updated_at,
                        cp.permission AS user_permission
                    FROM conversations c
                    LEFT JOIN conversation_permissions cp
                        ON cp.conversation_id = c.id
                        AND cp.user_id = :user_id
                    WHERE c.is_visible = TRUE
                        AND (c.owner_user_id = :user_id OR cp.user_id = :user_id)
                        AND (
                            :has_query = FALSE
                            OR c.title LIKE :query_like ESCAPE '\\\\'
                            OR EXISTS (
                                SELECT 1
                                FROM conversation_messages cm
                                WHERE cm.conversation_id = c.id
                                    AND cm.content LIKE :query_like ESCAPE '\\\\'
                                LIMIT 1
                            )
                        )
                    ORDER BY
                        CASE
                            WHEN :has_query = FALSE THEN 0
                            WHEN c.title LIKE :query_like ESCAPE '\\\\' THEN 0
                            ELSE 1
                        END ASC,
                        c.is_pinned DESC,
                        CASE
                            WHEN c.is_pinned THEN COALESCE(c.pinned_at, c.updated_at)
                            ELSE c.updated_at
                        END DESC
                    LIMIT 100
                    """
                ),
                {
                    "user_id": user_id,
                    "has_query": has_query,
                    "query_like": query_like,
                },
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
                    is_pinned=_as_bool(row["is_pinned"]),
                    pinned_at=_isoformat_optional(row["pinned_at"]),
                    is_visible=_as_bool(row["is_visible"]),
                    created_at=_isoformat(row["created_at"]),
                    updated_at=_isoformat(row["updated_at"]),
                )
            )

        return summaries

    def get_conversation(self, conversation_id: str, user_id: int) -> ConversationData:
        normalized_id = _ensure_uuid(conversation_id)
        with self._engine.connect() as connection:
            row = self._fetch_conversation_row(connection, normalized_id, user_id)
            if row is None or not _as_bool(row["is_visible"]):
                raise ConversationNotFoundError()

            access = _resolve_access(row, user_id)
            return self._to_conversation_data(connection, row, access)

    def conversation_exists(self, conversation_id: str) -> bool:
        normalized_id = _ensure_uuid(conversation_id)
        with self._engine.connect() as connection:
            count = connection.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM conversations
                    WHERE id = :conversation_id
                    """
                ),
                {"conversation_id": normalized_id},
            ).scalar_one()

        return int(count) > 0

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
                if not _as_bool(row["is_visible"]):
                    raise ConversationNotFoundError()

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
                            rag_sources_json,
                            reasoning_content,
                            reasoning_duration_ms,
                            position,
                            created_at,
                            updated_at
                        )
                        VALUES (
                            :message_id,
                            :conversation_id,
                            :role,
                            :content,
                            :rag_sources_json,
                            :reasoning_content,
                            :reasoning_duration_ms,
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
                        "rag_sources_json": _serialize_rag_sources(message.rag_sources),
                        "reasoning_content": _normalize_reasoning_content(
                            message.reasoning_content,
                        ),
                        "reasoning_duration_ms": _normalize_reasoning_duration_ms(
                            message.reasoning_duration_ms,
                        ),
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
        rag_sources: Sequence[Mapping[str, object]],
        reasoning_content: str | None,
        reasoning_duration_ms: int | None,
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
                if not _as_bool(row["is_visible"]):
                    raise ConversationNotFoundError()

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
                rag_sources=[],
                reasoning_content=None,
                reasoning_duration_ms=None,
                position=next_position,
                now=now,
            )
            self._upsert_message(
                connection,
                conversation_id=normalized_id,
                message_id=_ensure_uuid(response_id),
                role="ai",
                content=ai_content,
                rag_sources=rag_sources,
                reasoning_content=reasoning_content,
                reasoning_duration_ms=reasoning_duration_ms,
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
        rag_sources: Sequence[Mapping[str, object]],
        reasoning_content: str | None,
        reasoning_duration_ms: int | None,
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
                    rag_sources_json,
                    reasoning_content,
                    reasoning_duration_ms,
                    position,
                    created_at,
                    updated_at
                )
                VALUES (
                    :message_id,
                    :conversation_id,
                    :role,
                    :content,
                    :rag_sources_json,
                    :reasoning_content,
                    :reasoning_duration_ms,
                    :position,
                    :now,
                    :now
                )
                ON DUPLICATE KEY UPDATE
                    role = VALUES(role),
                    content = VALUES(content),
                    rag_sources_json = VALUES(rag_sources_json),
                    reasoning_content = VALUES(reasoning_content),
                    reasoning_duration_ms = VALUES(reasoning_duration_ms),
                    updated_at = VALUES(updated_at)
                """
            ),
            {
                "message_id": message_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "rag_sources_json": _serialize_rag_sources(rag_sources),
                "reasoning_content": _normalize_reasoning_content(reasoning_content),
                "reasoning_duration_ms": _normalize_reasoning_duration_ms(
                    reasoning_duration_ms,
                ),
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
            if row is None or not _as_bool(row["is_visible"]):
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

    def rename_conversation(
        self,
        conversation_id: str,
        user_id: int,
        title: str,
    ) -> ConversationData:
        normalized_id = _ensure_uuid(conversation_id)
        now = _now_utc()

        with self._engine.begin() as connection:
            row = self._fetch_conversation_row(connection, normalized_id, user_id)
            if row is None or not _as_bool(row["is_visible"]):
                raise ConversationNotFoundError()

            access = _resolve_access(row, user_id)
            if access.permission != "owner":
                raise ConversationPermissionError()

            connection.execute(
                text(
                    """
                    UPDATE conversations
                    SET title = :title,
                        updated_at = :now
                    WHERE id = :conversation_id
                    """
                ),
                {
                    "conversation_id": normalized_id,
                    "title": _clean_title(title),
                    "now": now,
                },
            )

        return self.get_conversation(normalized_id, user_id)

    def update_pin_state(
        self,
        conversation_id: str,
        user_id: int,
        is_pinned: bool,
    ) -> ConversationData:
        normalized_id = _ensure_uuid(conversation_id)
        now = _now_utc()

        with self._engine.begin() as connection:
            row = self._fetch_conversation_row(connection, normalized_id, user_id)
            if row is None or not _as_bool(row["is_visible"]):
                raise ConversationNotFoundError()

            access = _resolve_access(row, user_id)
            if access.permission != "owner":
                raise ConversationPermissionError()

            connection.execute(
                text(
                    """
                    UPDATE conversations
                    SET is_pinned = :is_pinned,
                        pinned_at = :pinned_at,
                        updated_at = :now
                    WHERE id = :conversation_id
                    """
                ),
                {
                    "conversation_id": normalized_id,
                    "is_pinned": is_pinned,
                    "pinned_at": now if is_pinned else None,
                    "now": now,
                },
            )

        return self.get_conversation(normalized_id, user_id)

    def hide_conversation(self, conversation_id: str, user_id: int) -> None:
        normalized_id = _ensure_uuid(conversation_id)
        now = _now_utc()

        with self._engine.begin() as connection:
            row = self._fetch_conversation_row(connection, normalized_id, user_id)
            if row is None or not _as_bool(row["is_visible"]):
                raise ConversationNotFoundError()

            access = _resolve_access(row, user_id)
            if access.permission != "owner":
                raise ConversationPermissionError()

            connection.execute(
                text(
                    """
                    UPDATE conversations
                    SET is_visible = FALSE,
                        updated_at = :now
                    WHERE id = :conversation_id
                    """
                ),
                {"conversation_id": normalized_id, "now": now},
            )

    def list_admin_conversations(self) -> list[AdminConversationSummary]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        c.id,
                        c.title,
                        c.owner_user_id,
                        u.username AS owner_username,
                        u.email AS owner_email,
                        c.share_scope,
                        c.is_visible,
                        c.created_at,
                        c.updated_at,
                        COUNT(cm.id) AS message_count
                    FROM conversations c
                    INNER JOIN users u ON u.id = c.owner_user_id
                    LEFT JOIN conversation_messages cm ON cm.conversation_id = c.id
                    GROUP BY
                        c.id,
                        c.title,
                        c.owner_user_id,
                        u.username,
                        u.email,
                        c.share_scope,
                        c.is_visible,
                        c.created_at,
                        c.updated_at
                    ORDER BY c.updated_at DESC
                    LIMIT 500
                    """
                )
            ).mappings().fetchall()

        return [
            AdminConversationSummary(
                id=str(row["id"]),
                title=str(row["title"]),
                owner_user_id=int(row["owner_user_id"]),
                owner_username=str(row["owner_username"]),
                owner_email=str(row["owner_email"]),
                share_scope=str(row["share_scope"]),
                is_visible=_as_bool(row["is_visible"]),
                message_count=int(row["message_count"] or 0),
                created_at=_isoformat(row["created_at"]),
                updated_at=_isoformat(row["updated_at"]),
            )
            for row in rows
        ]

    def get_admin_conversation(self, conversation_id: str) -> AdminConversationSummary | None:
        normalized_id = _ensure_uuid(conversation_id)
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT
                        c.id,
                        c.title,
                        c.owner_user_id,
                        u.username AS owner_username,
                        u.email AS owner_email,
                        c.share_scope,
                        c.is_visible,
                        c.created_at,
                        c.updated_at,
                        COUNT(cm.id) AS message_count
                    FROM conversations c
                    INNER JOIN users u ON u.id = c.owner_user_id
                    LEFT JOIN conversation_messages cm ON cm.conversation_id = c.id
                    WHERE c.id = :conversation_id
                    GROUP BY
                        c.id,
                        c.title,
                        c.owner_user_id,
                        u.username,
                        u.email,
                        c.share_scope,
                        c.is_visible,
                        c.created_at,
                        c.updated_at
                    """
                ),
                {"conversation_id": normalized_id},
            ).mappings().fetchone()

        if row is None:
            return None

        return AdminConversationSummary(
            id=str(row["id"]),
            title=str(row["title"]),
            owner_user_id=int(row["owner_user_id"]),
            owner_username=str(row["owner_username"]),
            owner_email=str(row["owner_email"]),
            share_scope=str(row["share_scope"]),
            is_visible=_as_bool(row["is_visible"]),
            message_count=int(row["message_count"] or 0),
            created_at=_isoformat(row["created_at"]),
            updated_at=_isoformat(row["updated_at"]),
        )

    def update_admin_visibility(
        self,
        conversation_id: str,
        is_visible: bool,
    ) -> AdminConversationSummary | None:
        normalized_id = _ensure_uuid(conversation_id)
        now = _now_utc()

        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE conversations
                    SET is_visible = :is_visible,
                        updated_at = :now
                    WHERE id = :conversation_id
                    """
                ),
                {
                    "conversation_id": normalized_id,
                    "is_visible": is_visible,
                    "now": now,
                },
            )
            if result.rowcount == 0:
                return None

        return self.get_admin_conversation(normalized_id)

    def delete_admin_conversation(self, conversation_id: str) -> bool:
        normalized_id = _ensure_uuid(conversation_id)
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    DELETE FROM conversations
                    WHERE id = :conversation_id
                    """
                ),
                {"conversation_id": normalized_id},
            )

        return result.rowcount > 0

    def get_conversation_totals(self) -> ConversationTotals:
        with self._engine.connect() as connection:
            conversation_row = connection.execute(
                text(
                    """
                    SELECT
                        COUNT(*) AS total_conversations,
                        SUM(CASE WHEN is_visible THEN 1 ELSE 0 END) AS visible_conversations
                    FROM conversations
                    """
                )
            ).mappings().one()
            message_count = connection.execute(
                text("SELECT COUNT(*) FROM conversation_messages")
            ).scalar_one()

        return ConversationTotals(
            total_conversations=int(conversation_row["total_conversations"] or 0),
            visible_conversations=int(conversation_row["visible_conversations"] or 0),
            total_messages=int(message_count or 0),
        )


@lru_cache(maxsize=1)
def get_conversation_service() -> ConversationService:
    return ConversationService()
