from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.core.security import TokenPayload, get_current_token_payload
from api.schemas.memory import (
    UserMemoryCreateRequest,
    UserMemoryResponse,
    UserMemoryUpdateRequest,
)
from agent.tools.user_memory_service import (
    UserMemory,
    UserMemoryService,
    get_user_memory_service,
)

router = APIRouter(prefix="/memories", tags=["memories"])


def _to_memory_response(memory: UserMemory) -> UserMemoryResponse:
    return UserMemoryResponse(
        id=memory.id,
        content=memory.content,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


def _not_found_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="记忆不存在或无权访问",
    )


@router.get("", response_model=list[UserMemoryResponse])
async def list_memories(
    query: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: UserMemoryService = Depends(get_user_memory_service),
) -> list[UserMemoryResponse]:
    return [
        _to_memory_response(memory)
        for memory in service.list_memories(
            user_id=token_payload.user_id,
            query=query,
            limit=limit,
        )
    ]


@router.post("", response_model=UserMemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    request: UserMemoryCreateRequest,
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: UserMemoryService = Depends(get_user_memory_service),
) -> UserMemoryResponse:
    try:
        memory = service.create_memory(token_payload.user_id, request.content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return _to_memory_response(memory)


@router.put("/{memory_id}", response_model=UserMemoryResponse)
async def update_memory(
    memory_id: str,
    request: UserMemoryUpdateRequest,
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: UserMemoryService = Depends(get_user_memory_service),
) -> UserMemoryResponse:
    try:
        memory = service.update_memory(
            user_id=token_payload.user_id,
            memory_id=memory_id,
            content=request.content,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if memory is None:
        raise _not_found_exception()

    return _to_memory_response(memory)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: str,
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: UserMemoryService = Depends(get_user_memory_service),
) -> None:
    try:
        deleted = service.delete_memory(token_payload.user_id, memory_id)
    except ValueError as exc:
        raise _not_found_exception() from exc

    if not deleted:
        raise _not_found_exception()
