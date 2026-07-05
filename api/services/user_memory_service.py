from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import Connection

from api.db.core import Database
from api.db.schema import create_schema


MAX_MEMORY_CONTENT_LENGTH = 4000
DEFAULT_MEMORY_LIMIT = 50
MAX_MEMORY_LIMIT = 100
DEFAULT_IDENTITY_MEMORY_PREFIX = "[默认记忆] 用户身份："
DEFAULT_IDENTITY_MEMORY_CONTENT: dict[str, str] = {
    "student": (
        f"{DEFAULT_IDENTITY_MEMORY_PREFIX}学生。回答校园问题时优先关注选课、"
        "学籍、奖助、考试、宿舍、办事流程等学生视角。"
    ),
    "teacher": (
        f"{DEFAULT_IDENTITY_MEMORY_PREFIX}老师。回答校园问题时优先关注教学管理、"
        "课程安排、学生指导、教务流程等教师视角。"
    ),
    "maintenance": (
        f"{DEFAULT_IDENTITY_MEMORY_PREFIX}运维人员。回答校园问题时优先关注系统维护、"
        "服务保障、故障处理和后勤流程等运维视角。"
    ),
    "admin": (
        f"{DEFAULT_IDENTITY_MEMORY_PREFIX}管理员。回答校园问题时优先关注管理配置、"
        "数据权限、系统运营和校内事务协调。"
    ),
}

@dataclass(frozen=True)
class UserMemory:
    id: str
    user_id: int
    content: str
    created_at: str
    updated_at: str


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


def _clean_content(content: str) -> str:
    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("Memory content is required")
    if len(normalized_content) > MAX_MEMORY_CONTENT_LENGTH:
        raise ValueError("Memory content is too long")

    return normalized_content


def _normalize_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_MEMORY_LIMIT

    return max(1, min(MAX_MEMORY_LIMIT, int(limit)))


def _row_to_memory(row: Mapping[str, object]) -> UserMemory:
    return UserMemory(
        id=str(row["id"]),
        user_id=int(row["user_id"]),
        content=str(row["content"]),
        created_at=_isoformat(row["created_at"]),
        updated_at=_isoformat(row["updated_at"]),
    )


def _memory_match_score(memory: UserMemory, query: str) -> float:
    normalized_query = " ".join(query.lower().split())
    if not normalized_query:
        return 0

    content = " ".join(memory.content.lower().split())
    if not content:
        return 0

    score = 0.0
    if normalized_query in content:
        score += 20
    if content in normalized_query:
        score += 8

    terms = [term for term in normalized_query.split(" ") if len(term) > 1]
    for term in terms:
        if term in content:
            score += 5

    query_chars = {char for char in normalized_query if not char.isspace()}
    content_chars = {char for char in content if not char.isspace()}
    if query_chars:
        score += len(query_chars & content_chars) / len(query_chars) * 3

    return score


class UserMemoryService:
    def __init__(self) -> None:
        self._db = Database()
        self._initialize_database()

    def _initialize_database(self) -> None:
        with self._db.begin() as connection:
            create_schema(connection, ("users", "user_memories"))

    def _get_memory_row(
        self,
        connection: Connection,
        memory_id: str,
        user_id: int,
    ) -> Mapping[str, object] | None:
        return connection.execute(
            text(
                """
                SELECT id, user_id, content, created_at, updated_at
                FROM user_memories
                WHERE id = :memory_id AND user_id = :user_id
                """
            ),
            {"memory_id": memory_id, "user_id": user_id},
        ).mappings().fetchone()

    def get_memory(self, user_id: int, memory_id: str) -> UserMemory | None:
        normalized_id = _ensure_uuid(memory_id)
        with self._db.connect() as connection:
            row = self._get_memory_row(connection, normalized_id, user_id)

        if row is None:
            return None

        return _row_to_memory(row)

    def list_memories(
        self,
        user_id: int,
        query: str | None = None,
        limit: int | None = None,
        fallback_to_recent: bool = False,
    ) -> list[UserMemory]:
        normalized_limit = _normalize_limit(limit)
        normalized_query = " ".join((query or "").split())
        fetch_limit = max(normalized_limit, 500) if normalized_query else normalized_limit

        with self._db.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT id, user_id, content, created_at, updated_at
                    FROM user_memories
                    WHERE user_id = :user_id
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT :limit
                    """
                ),
                {"user_id": user_id, "limit": fetch_limit},
            ).mappings().fetchall()

        memories = [_row_to_memory(row) for row in rows]
        if not normalized_query:
            return memories[:normalized_limit]

        scored_memories = [
            (_memory_match_score(memory, normalized_query), index, memory)
            for index, memory in enumerate(memories)
        ]
        positive_matches = [
            (score, index, memory)
            for score, index, memory in scored_memories
            if score > 0
        ]
        if not positive_matches:
            if fallback_to_recent:
                return memories[:normalized_limit]

            return []

        positive_matches.sort(key=lambda item: (-item[0], item[1]))
        return [memory for _, _, memory in positive_matches[:normalized_limit]]

    def create_memory(self, user_id: int, content: str) -> UserMemory:
        normalized_content = _clean_content(content)
        now = _now_utc()

        with self._db.begin() as connection:
            existing_row = connection.execute(
                text(
                    """
                    SELECT id, user_id, content, created_at, updated_at
                    FROM user_memories
                    WHERE user_id = :user_id AND content = :content
                    LIMIT 1
                    """
                ),
                {"user_id": user_id, "content": normalized_content},
            ).mappings().fetchone()
            if existing_row is not None:
                return _row_to_memory(existing_row)

            memory_id = _ensure_uuid(None)
            connection.execute(
                text(
                    """
                    INSERT INTO user_memories (
                        id,
                        user_id,
                        content,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :memory_id,
                        :user_id,
                        :content,
                        :now,
                        :now
                    )
                    """
                ),
                {
                    "memory_id": memory_id,
                    "user_id": user_id,
                    "content": normalized_content,
                    "now": now,
                },
            )

        created_memory = self.get_memory(user_id, memory_id)
        if created_memory is None:
            raise RuntimeError("Memory creation failed")

        return created_memory

    def ensure_default_identity_memory(
        self,
        user_id: int,
        user_type: str,
    ) -> UserMemory:
        normalized_user_type = user_type.strip().lower()
        content = DEFAULT_IDENTITY_MEMORY_CONTENT.get(
            normalized_user_type,
            DEFAULT_IDENTITY_MEMORY_CONTENT["student"],
        )
        now = _now_utc()

        with self._db.begin() as connection:
            existing_row = connection.execute(
                text(
                    """
                    SELECT id, user_id, content, created_at, updated_at
                    FROM user_memories
                    WHERE user_id = :user_id
                        AND (
                            content = :content
                            OR content LIKE :prefix_like
                        )
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT 1
                    """
                ),
                {
                    "user_id": user_id,
                    "content": content,
                    "prefix_like": f"{DEFAULT_IDENTITY_MEMORY_PREFIX}%",
                },
            ).mappings().fetchone()

            if existing_row is not None:
                memory_id = str(existing_row["id"])
                if str(existing_row["content"]) != content:
                    connection.execute(
                        text(
                            """
                            UPDATE user_memories
                            SET content = :content,
                                updated_at = :now
                            WHERE id = :memory_id AND user_id = :user_id
                            """
                        ),
                        {
                            "memory_id": memory_id,
                            "user_id": user_id,
                            "content": content,
                            "now": now,
                        },
                    )
                memory_row = self._get_memory_row(connection, memory_id, user_id)
                if memory_row is None:
                    raise RuntimeError("Default identity memory update failed")

                return _row_to_memory(memory_row)

            memory_id = _ensure_uuid(None)
            connection.execute(
                text(
                    """
                    INSERT INTO user_memories (
                        id,
                        user_id,
                        content,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :memory_id,
                        :user_id,
                        :content,
                        :now,
                        :now
                    )
                    """
                ),
                {
                    "memory_id": memory_id,
                    "user_id": user_id,
                    "content": content,
                    "now": now,
                },
            )

        memory = self.get_memory(user_id, memory_id)
        if memory is None:
            raise RuntimeError("Default identity memory creation failed")

        return memory

    def update_memory(
        self,
        user_id: int,
        memory_id: str,
        content: str,
    ) -> UserMemory | None:
        normalized_id = _ensure_uuid(memory_id)
        normalized_content = _clean_content(content)
        now = _now_utc()

        with self._db.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE user_memories
                    SET content = :content,
                        updated_at = :now
                    WHERE id = :memory_id AND user_id = :user_id
                    """
                ),
                {
                    "memory_id": normalized_id,
                    "user_id": user_id,
                    "content": normalized_content,
                    "now": now,
                },
            )
            if result.rowcount == 0:
                return None

        return self.get_memory(user_id, normalized_id)

    def delete_memory(self, user_id: int, memory_id: str) -> bool:
        normalized_id = _ensure_uuid(memory_id)
        with self._db.begin() as connection:
            result = connection.execute(
                text(
                    """
                    DELETE FROM user_memories
                    WHERE id = :memory_id AND user_id = :user_id
                    """
                ),
                {"memory_id": normalized_id, "user_id": user_id},
            )

        return result.rowcount > 0

    def format_memories_for_agent(self, memories: Sequence[UserMemory]) -> str:
        if not memories:
            return "没有找到可用的用户记忆。"

        lines = ["找到以下用户记忆："]
        for index, memory in enumerate(memories, 1):
            lines.append(
                f"{index}. id={memory.id} | updated_at={memory.updated_at} | "
                f"content={memory.content}"
            )

        return "\n".join(lines)


@lru_cache(maxsize=1)
def get_user_memory_service() -> UserMemoryService:
    return UserMemoryService()
