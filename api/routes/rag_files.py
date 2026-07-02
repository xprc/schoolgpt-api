from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.core.security import TokenPayload, get_current_token_payload
from api.schemas.rag_files import RagFileDetailResponse, RagFileSummaryResponse
from api.services.rag_file_service import RagFileRecord, RagFileService, get_rag_file_service
from rag.vector_store import get_vector_store_service

router = APIRouter(prefix="/rag/files", tags=["rag-files"])


def _to_file_summary(record: RagFileRecord) -> RagFileSummaryResponse:
    return RagFileSummaryResponse(
        id=record.id,
        name=record.original_name,
        size=record.size_bytes,
        modified_at=record.updated_at,
        sha256=record.sha256,
        status=record.status,
        error_message=record.error_message,
        indexed=record.status == "ready" and record.chunk_count > 0,
        chunk_count=record.chunk_count,
    )


@router.get("", response_model=list[RagFileSummaryResponse])
async def list_rag_files(
    _: TokenPayload = Depends(get_current_token_payload),
    service: RagFileService = Depends(get_rag_file_service),
) -> list[RagFileSummaryResponse]:
    return [_to_file_summary(record) for record in service.list_files()]


@router.get("/{file_id}", response_model=RagFileDetailResponse)
async def get_rag_file(
    file_id: int,
    chunk_index: int | None = Query(default=None, ge=0),
    _: TokenPayload = Depends(get_current_token_payload),
    service: RagFileService = Depends(get_rag_file_service),
) -> RagFileDetailResponse:
    record = service.get_file(file_id, include_content=True)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在",
        )

    chunk_detail = None
    if chunk_index is not None:
        chunk_detail = get_vector_store_service().get_chunk_detail(file_id, chunk_index)

    summary = _to_file_summary(record)
    return RagFileDetailResponse(
        **summary.model_dump(),
        markdown=record.markdown_content,
        chunk_index=chunk_index,
        snippet=(
            str(chunk_detail.get("snippet"))
            if chunk_detail and chunk_detail.get("snippet")
            else None
        ),
    )
