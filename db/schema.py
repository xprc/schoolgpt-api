from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from db.seeds import (
    seed_default_model_config,
    seed_default_paddle_ocr_config,
    seed_default_web_search_config,
)


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
    chunk_count INT UNSIGNED NOT NULL DEFAULT 0,
    used_ocr TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_rag_files_sha256 (sha256),
    KEY idx_rag_files_status_updated (status, updated_at),
    KEY idx_rag_files_name (original_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

CREATE_PADDLE_OCR_CONFIGS_SQL = """
CREATE TABLE IF NOT EXISTS paddle_ocr_configs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    provider VARCHAR(32) NOT NULL DEFAULT 'baidu_aistudio',
    api_key VARCHAR(1024) NOT NULL DEFAULT '',
    model_name VARCHAR(64) NOT NULL DEFAULT 'PaddleOCR-VL-1.5',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_paddle_ocr_configs_provider (provider)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def execute_schema(connection: Connection, statements: Iterable[str]) -> None:
    for statement in statements:
        connection.execute(text(statement))


def mysql_column_exists(
    connection: Connection,
    table_name: str,
    column_name: str,
) -> bool:
    if connection.dialect.name != "mysql":
        return True

    count = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.COLUMNS
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
    table_name: str,
    index_name: str,
) -> bool:
    if connection.dialect.name != "mysql":
        return True

    count = connection.execute(
        text(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = :table_name
                AND INDEX_NAME = :index_name
            """
        ),
        {"table_name": table_name, "index_name": index_name},
    ).scalar_one()

    return int(count) > 0


def mysql_column_is_nullable(
    connection: Connection,
    table_name: str,
    column_name: str,
) -> bool:
    if connection.dialect.name != "mysql":
        return False

    row = connection.execute(
        text(
            """
            SELECT IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = :table_name
                AND COLUMN_NAME = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).scalar_one_or_none()

    return str(row or "").upper() == "YES"


def ensure_users_compatibility(connection: Connection) -> None:
    if connection.dialect.name != "mysql":
        return

    if not mysql_column_exists(connection, "users", "avatar_sha256"):
        connection.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN avatar_sha256 CHAR(64) NULL AFTER email
                """
            )
        )

    connection.execute(
        text(
            """
            UPDATE users
            SET avatar_sha256 = SHA2(LOWER(TRIM(email)), 256)
            WHERE avatar_sha256 IS NULL OR avatar_sha256 = ''
            """
        )
    )
    if mysql_column_is_nullable(connection, "users", "avatar_sha256"):
        connection.execute(
            text(
                """
                ALTER TABLE users
                MODIFY avatar_sha256 CHAR(64) NOT NULL
                """
            )
        )

    if not mysql_index_exists(connection, "users", "uq_users_avatar_sha256"):
        connection.execute(
            text(
                """
                ALTER TABLE users
                ADD UNIQUE KEY uq_users_avatar_sha256 (avatar_sha256)
                """
            )
        )

    if not mysql_column_exists(connection, "users", "user_type"):
        connection.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN user_type VARCHAR(16) NOT NULL DEFAULT 'student' AFTER display_name
                """
            )
        )

    connection.execute(
        text(
            """
            UPDATE users
            SET user_type = 'admin'
            WHERE username = 'admin' OR email = 'admin@schoolgpt.local'
            """
        )
    )

    if not mysql_column_exists(connection, "users", "preferred_language"):
        connection.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN preferred_language VARCHAR(16) NOT NULL DEFAULT 'zh' AFTER user_type
                """
            )
        )

    if not mysql_column_exists(connection, "users", "light_background"):
        connection.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN light_background VARCHAR(255) NOT NULL DEFAULT '/backgrounds/light-1.jpg' AFTER preferred_language
                """
            )
        )

    if not mysql_column_exists(connection, "users", "dark_background"):
        connection.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN dark_background VARCHAR(255) NOT NULL DEFAULT '/backgrounds/dark-1.jpg' AFTER light_background
                """
            )
        )

    admin_count = connection.execute(
        text("SELECT COUNT(*) FROM users WHERE user_type = 'admin'")
    ).scalar_one()
    if int(admin_count) > 0:
        return

    first_user_id = connection.execute(
        text("SELECT id FROM users ORDER BY id ASC LIMIT 1")
    ).scalar_one_or_none()
    if first_user_id is None:
        return

    connection.execute(
        text(
            """
            UPDATE users
            SET user_type = 'admin'
            WHERE id = :user_id
            """
        ),
        {"user_id": int(first_user_id)},
    )


def ensure_conversation_messages_compatibility(connection: Connection) -> None:
    if connection.dialect.name != "mysql":
        return

    if not mysql_column_exists(connection, "conversation_messages", "reasoning_content"):
        connection.execute(
            text(
                """
                ALTER TABLE conversation_messages
                ADD COLUMN reasoning_content MEDIUMTEXT NULL AFTER rag_sources_json
                """
            )
        )

    if not mysql_column_exists(connection, "conversation_messages", "reasoning_duration_ms"):
        connection.execute(
            text(
                """
                ALTER TABLE conversation_messages
                ADD COLUMN reasoning_duration_ms INT UNSIGNED NULL AFTER reasoning_content
                """
            )
        )


def ensure_model_configs_compatibility(connection: Connection) -> None:
    if connection.dialect.name != "mysql":
        return

    if mysql_column_exists(connection, "model_configs", "api_path"):
        return

    connection.execute(
        text(
            """
            ALTER TABLE model_configs
            ADD COLUMN api_path VARCHAR(120) NOT NULL DEFAULT '/chat/completions' AFTER base_url
            """
        )
    )


def ensure_rag_files_compatibility(connection: Connection) -> None:
    if connection.dialect.name != "mysql":
        return

    if mysql_column_exists(connection, "rag_files", "used_ocr"):
        return

    if mysql_column_exists(connection, "rag_files", "ocr_used"):
        connection.execute(
            text(
                """
                ALTER TABLE rag_files
                CHANGE COLUMN ocr_used used_ocr TINYINT(1) NOT NULL DEFAULT 0 AFTER chunk_count
                """
            )
        )
        return

    connection.execute(
        text(
            """
            ALTER TABLE rag_files
            ADD COLUMN used_ocr TINYINT(1) NOT NULL DEFAULT 0 AFTER chunk_count
            """
        )
    )


def create_users_schema(connection: Connection) -> None:
    execute_schema(connection, (CREATE_USERS_SQL,))
    ensure_users_compatibility(connection)


def create_user_memories_schema(connection: Connection) -> None:
    create_users_schema(connection)
    execute_schema(connection, (CREATE_USER_MEMORIES_SQL,))


def create_conversations_schema(connection: Connection) -> None:
    create_users_schema(connection)
    execute_schema(
        connection,
        (
            CREATE_CONVERSATIONS_SQL,
            CREATE_CONVERSATION_MESSAGES_SQL,
            CREATE_CONVERSATION_PERMISSIONS_SQL,
        ),
    )
    ensure_conversation_messages_compatibility(connection)


def create_model_configs_schema(connection: Connection) -> None:
    execute_schema(connection, (CREATE_MODEL_CONFIGS_SQL,))
    ensure_model_configs_compatibility(connection)


def create_web_search_configs_schema(connection: Connection) -> None:
    execute_schema(connection, (CREATE_WEB_SEARCH_CONFIGS_SQL,))


def create_rag_files_schema(connection: Connection) -> None:
    execute_schema(connection, (CREATE_RAG_FILES_SQL,))
    ensure_rag_files_compatibility(connection)


def create_paddle_ocr_configs_schema(connection: Connection) -> None:
    execute_schema(connection, (CREATE_PADDLE_OCR_CONFIGS_SQL,))


def create_first_run_schema(connection: Connection) -> None:
    create_users_schema(connection)
    execute_schema(
        connection,
        (
            CREATE_CONVERSATIONS_SQL,
            CREATE_CONVERSATION_MESSAGES_SQL,
            CREATE_CONVERSATION_PERMISSIONS_SQL,
            CREATE_USER_MEMORIES_SQL,
            CREATE_MODEL_CONFIGS_SQL,
            CREATE_WEB_SEARCH_CONFIGS_SQL,
            CREATE_RAG_FILES_SQL,
            CREATE_PADDLE_OCR_CONFIGS_SQL,
        ),
    )
    ensure_conversation_messages_compatibility(connection)
    ensure_model_configs_compatibility(connection)
    ensure_rag_files_compatibility(connection)


def initialize_users_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        create_users_schema(connection)


def initialize_user_memories_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        create_user_memories_schema(connection)


def initialize_conversations_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        create_conversations_schema(connection)


def initialize_model_configs_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        create_model_configs_schema(connection)
        seed_default_model_config(connection)


def initialize_web_search_configs_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        create_web_search_configs_schema(connection)
        seed_default_web_search_config(connection)


def initialize_rag_files_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        create_rag_files_schema(connection)


def initialize_paddle_ocr_configs_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        create_paddle_ocr_configs_schema(connection)
        seed_default_paddle_ocr_config(connection)
