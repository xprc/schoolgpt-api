import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from api.core.security import TokenPayload, get_current_token_payload
from api.core.settings import Settings, get_settings
from api.schemas.chat import ChatRequest
from api.services.conversation_service import (
    ConversationNotFoundError,
    ConversationService,
    get_conversation_service,
)
from api.services.chat_service import ChatService, get_chat_service
from model.factory import ModelConfigurationError

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
)


@router.post("")
async def stream_chat(
    request: ChatRequest,
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: ChatService = Depends(get_chat_service),
    conversation_service: ConversationService = Depends(get_conversation_service),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    try:
        service.ensure_ready()
    except ModelConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if request.conversation_id:
        try:
            conversation = conversation_service.get_conversation(
                request.conversation_id,
                token_payload.user_id,
            )
            if not conversation.can_write:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="没有权限修改该对话",
                )
        except ConversationNotFoundError:
            pass
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="对话不存在或无权访问",
            ) from exc

    async def stream_events() -> AsyncIterator[str]:
        ai_content = ""
        async for char in service.stream_content(request.query, settings.stream_delay_seconds):
            ai_content += char
            yield f"data: {json.dumps(char, ensure_ascii=False)}\n\n"

        if request.conversation_id:
            conversation_service.append_generated_exchange(
                conversation_id=request.conversation_id,
                user_id=token_payload.user_id,
                query=request.query,
                ai_content=ai_content,
                message_id=request.message_id,
                response_id=request.response_id,
            )

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_events(),
        media_type="text/event-stream",
    )
