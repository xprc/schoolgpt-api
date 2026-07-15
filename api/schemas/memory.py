from pydantic import BaseModel, Field

from agent.tools.user_memory_service import MAX_MEMORY_CONTENT_LENGTH


class UserMemoryCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=MAX_MEMORY_CONTENT_LENGTH)


class UserMemoryUpdateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=MAX_MEMORY_CONTENT_LENGTH)


class UserMemoryResponse(BaseModel):
    id: str
    content: str
    created_at: str
    updated_at: str
