from pydantic import BaseModel


class RagFileSummaryResponse(BaseModel):
    id: int
    name: str
    size: int
    modified_at: str
    sha256: str
    status: str
    error_message: str | None = None
    indexed: bool
    chunk_count: int


class RagFileDetailResponse(RagFileSummaryResponse):
    markdown: str
    chunk_index: int | None = None
    snippet: str | None = None
