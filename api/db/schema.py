from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection


CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL,
    email VARCHAR(120) NOT NULL,
    avatar_sha256 CHAR(64) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    user_type VARCHAR(16) NOT NULL DEFAULT 'student',
    preferred_language VARCHAR(16) NOT NULL DEFAULT 'zh',
    light_background VARCHAR(255) NOT NULL DEFAULT '/backgrounds/light-1.jpg',
    dark_background VARCHAR(255) NOT NULL DEFAULT '/backgrounds/dark-1.jpg',
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP NULL DEFAULT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_username (username),
    UNIQUE KEY uq_users_email (email),
    UNIQUE KEY uq_users_avatar_sha256 (avatar_sha256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

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

CREATE_USER_MEMORIES_SQL = """
CREATE TABLE IF NOT EXISTS user_memories (
    id CHAR(36) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY idx_user_memories_user_updated (user_id, updated_at),
    CONSTRAINT fk_user_memories_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

CREATE_MODEL_CONFIGS_SQL = """
CREATE TABLE IF NOT EXISTS model_configs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    provider VARCHAR(32) NOT NULL,
    model_name VARCHAR(120) NOT NULL,
    base_url VARCHAR(255) NOT NULL,
    api_path VARCHAR(120) NOT NULL DEFAULT '/chat/completions',
    api_key VARCHAR(512) NOT NULL DEFAULT '',
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_model_configs_active_updated (is_active, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

CREATE_WEB_SEARCH_CONFIGS_SQL = """
CREATE TABLE IF NOT EXISTS web_search_configs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    provider VARCHAR(32) NOT NULL DEFAULT 'tavily',
    api_key VARCHAR(512) NOT NULL DEFAULT '',
    is_enabled TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_web_search_configs_provider (provider),
    KEY idx_web_search_configs_enabled_updated (is_enabled, updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

CREATE_RAG_FILES_SQL = """
CREATE TABLE IF NOT EXISTS rag_files (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    original_name VARCHAR(255) NOT NULL,
    original_extension VARCHAR(16) NOT NULL,
    mime_type VARCHAR(255) NOT NULL DEFAULT '',
    size_bytes BIGINT UNSIGNED NOT NULL,
    sha256 CHAR(64) NOT NULL,
    source_path VARCHAR(512) NOT NULL,
    content_json_path VARCHAR(512) NOT NULL,
    preview_pdf_path VARCHAR(512) NOT NULL,
    content_json LONGTEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    error_message TEXT NULL,
    ocr_used BOOLEAN NOT NULL DEFAULT FALSE,
    chunk_count INT UNSIGNED NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_rag_files_sha256 (sha256),
    KEY idx_rag_files_status_updated (status, updated_at),
    KEY idx_rag_files_name (original_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

SCHEMA_SQL_BY_TABLE = {
    "users": CREATE_USERS_SQL,
    "conversations": CREATE_CONVERSATIONS_SQL,
    "conversation_messages": CREATE_CONVERSATION_MESSAGES_SQL,
    "conversation_permissions": CREATE_CONVERSATION_PERMISSIONS_SQL,
    "user_memories": CREATE_USER_MEMORIES_SQL,
    "model_configs": CREATE_MODEL_CONFIGS_SQL,
    "web_search_configs": CREATE_WEB_SEARCH_CONFIGS_SQL,
    "rag_files": CREATE_RAG_FILES_SQL,
}

SCHEMA_TABLE_ORDER = (
    "users",
    "conversations",
    "conversation_messages",
    "conversation_permissions",
    "user_memories",
    "model_configs",
    "web_search_configs",
    "rag_files",
)


def create_schema(
    connection: Connection,
    tables: Iterable[str] = SCHEMA_TABLE_ORDER,
) -> None:
    for table_name in tables:
        connection.execute(text(SCHEMA_SQL_BY_TABLE[table_name]))
