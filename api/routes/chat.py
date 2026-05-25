from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.core.security import verify_token
from api.core.settings import Settings, get_settings
from api.schemas.chat import ChatRequest
from api.services.chat_service import ChatService, get_chat_service

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
    dependencies=[Depends(verify_token)],
)


@router.post("")
async def stream_chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    return StreamingResponse(
        service.stream_response(request.query, settings.stream_delay_seconds),
        media_type="text/event-stream",
    )
