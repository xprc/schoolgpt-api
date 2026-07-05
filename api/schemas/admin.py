from typing import Literal

from pydantic import BaseModel, Field

from api.schemas.rag_files import RagFileSummaryResponse


UserType = Literal["student", "teacher", "maintenance", "admin"]


class AdminUserResponse(BaseModel):
    id: int
    username: str
    email: str
    avatar_sha256: str
    display_name: str
    user_type: UserType
    is_active: bool
    created_at: str
    updated_at: str
    last_login_at: str | None


class AdminUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    email: str = Field(..., min_length=3, max_length=120)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=120)
    user_type: UserType = "student"
    is_active: bool = True


class AdminUserUpdateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    email: str = Field(..., min_length=3, max_length=120)
    display_name: str = Field(..., min_length=1, max_length=120)
    user_type: UserType
    is_active: bool


class AdminUserPasswordRequest(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


class AdminConversationResponse(BaseModel):
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


class AdminConversationVisibilityRequest(BaseModel):
    is_visible: bool


class ModelProviderOptionResponse(BaseModel):
    provider: Literal["deepseek", "qwen"]
    label: str
    base_url: str
    api_path: str
    models: list[str]


class ModelConfigResponse(BaseModel):
    id: int
    provider: Literal["deepseek", "qwen"]
    provider_label: str
    model_name: str
    base_url: str
    api_path: str
    has_api_key: bool
    api_key_mask: str
    is_active: bool
    created_at: str
    updated_at: str


class ModelConfigUpdateRequest(BaseModel):
    provider: Literal["deepseek", "qwen"]
    model_name: str = Field(..., min_length=1, max_length=120)
    base_url: str = Field(..., min_length=1, max_length=255)
    api_path: str = Field("/chat/completions", min_length=1, max_length=120)
    api_key: str | None = Field(None, max_length=512)


class WebSearchConfigResponse(BaseModel):
    id: int
    provider: Literal["tavily"]
    provider_label: str
    has_api_key: bool
    api_key_mask: str
    is_enabled: bool
    created_at: str
    updated_at: str


class WebSearchConfigUpdateRequest(BaseModel):
    api_key: str | None = Field(None, max_length=512)
    is_enabled: bool = True


class RagKnowledgeFileResponse(RagFileSummaryResponse):
    ocr_used: bool = False


class RagStatusResponse(BaseModel):
    collection_name: str
    data_path: str
    persist_directory: str
    allowed_file_types: list[str]
    total_files: int
    indexed_files: int
    vector_count: int
    files: list[RagKnowledgeFileResponse]


class AdminDashboardResponse(BaseModel):
    total_users: int
    active_users: int
    users_by_type: dict[str, int]
    total_conversations: int
    visible_conversations: int
    total_messages: int
    active_model: ModelConfigResponse
