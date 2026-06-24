from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1)
    conversation_id: str | None = None
    message_id: str | None = None
    response_id: str | None = None


ChatMessageRole = Literal["user", "ai"]
ConversationShareScope = Literal["private", "link_read", "link_write"]
ConversationPermission = Literal["owner", "read", "write"]


class ChatMessagePayload(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    role: ChatMessageRole
    content: str


class ConversationUpsertRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    share_scope: ConversationShareScope | None = None
    client_updated_at: str | None = None
    messages: list[ChatMessagePayload] = Field(default_factory=list)


class ConversationShareRequest(BaseModel):
    share_scope: ConversationShareScope


class ConversationRenameRequest(BaseModel):
    title: str = Field(..., max_length=255)


class ConversationPinRequest(BaseModel):
    is_pinned: bool


class ConversationMessageResponse(BaseModel):
    id: str
    role: ChatMessageRole
    content: str
    created_at: str
    updated_at: str


class ConversationResponse(BaseModel):
    id: str
    title: str
    owner_user_id: int
    share_scope: ConversationShareScope
    permission: ConversationPermission
    can_write: bool
    is_pinned: bool
    pinned_at: str | None = None
    is_visible: bool
    created_at: str
    updated_at: str
    messages: list[ConversationMessageResponse]


class ConversationSummaryResponse(BaseModel):
    id: str
    title: str
    share_scope: ConversationShareScope
    permission: ConversationPermission
    can_write: bool
    is_pinned: bool
    pinned_at: str | None = None
    is_visible: bool
    created_at: str
    updated_at: str
