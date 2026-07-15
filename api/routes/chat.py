import json
from collections.abc import AsyncIterator
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from api.core.security import TokenPayload, get_current_token_payload
from api.core.settings import Settings, get_settings
from api.schemas.chat import ChatRequest
from api.services.conversation_service import (
    ConversationNotFoundError,
    ConversationService,
    get_conversation_service,
)
from api.services.user_service import UserService, get_user_service
from agent.chat_service import ChatService, get_chat_service
from model.factory import ModelConfigurationError
from rag.source_context import get_rag_sources, reset_rag_sources, restore_rag_sources
from prompts.prompt_loader import build_user_runtime_context, resolve_client_ip

router = APIRouter(
    prefix="/chat",
    tags=["chat"],
)


MAX_CONTEXT_MESSAGES = 40


def _to_model_role(role: str) -> str:
    return "assistant" if role == "ai" else "user"


def _build_context_messages(
    request: ChatRequest,
    conversation_messages: list[object],
) -> list[dict[str, str]]:
    source_messages = request.messages or conversation_messages
    context_messages: list[dict[str, str]] = []

    for message in source_messages:
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        if role not in {"user", "ai"} or not isinstance(content, str):
            continue

        normalized_content = content.strip()
        if not normalized_content:
            continue

        context_messages.append(
            {
                "role": _to_model_role(role),
                "content": normalized_content,
            }
        )

    query = request.query.strip()
    if (
        not context_messages
        or context_messages[-1]["role"] != "user"
        or context_messages[-1]["content"] != query
    ):
        context_messages.append(
            {
                "role": "user",
                "content": query,
            }
        )

    return context_messages[-MAX_CONTEXT_MESSAGES:]


@router.post("")
async def stream_chat(
    chat_request: ChatRequest,
    http_request: Request,
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: ChatService = Depends(get_chat_service),
    conversation_service: ConversationService = Depends(get_conversation_service),
    user_service: UserService = Depends(get_user_service),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    try:
        service.ensure_ready(chat_request.enable_thinking)
    except ModelConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    conversation_messages: list[object] = []
    if chat_request.conversation_id:
        try:
            conversation = conversation_service.get_conversation(
                chat_request.conversation_id,
                token_payload.user_id,
            )
            if not conversation.can_write:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="没有权限修改该对话",
                )
            conversation_messages = list(conversation.messages)
        except ConversationNotFoundError as exc:
            if conversation_service.conversation_exists(chat_request.conversation_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="对话不存在或无权访问",
                ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="对话不存在或无权访问",
            ) from exc

    context_messages = _build_context_messages(chat_request, conversation_messages)
    client_ip = resolve_client_ip(
        http_request.headers,
        http_request.client.host if http_request.client else None,
    )
    user_runtime_context = build_user_runtime_context(
        user_service.get_user_by_id(token_payload.user_id),
        client_ip,
    )

    async def stream_events() -> AsyncIterator[str]:
        rag_token = reset_rag_sources()
        ai_content = ""
        reasoning_content = ""
        reasoning_duration_ms: int | None = None
        request_started_at = perf_counter()
        try:
            async for event in service.stream_events(
                context_messages,
                settings.stream_delay_seconds,
                chat_request.enable_thinking,
                token_payload.user_id,
                user_runtime_context,
            ):
                event_type = event["type"]
                content = event["content"]

                if event_type == "reasoning":
                    reasoning_content += content
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "type": "reasoning",
                                "content": content,
                            },
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )
                    continue

                if reasoning_content and reasoning_duration_ms is None:
                    reasoning_duration_ms = int((perf_counter() - request_started_at) * 1000)
                    yield (
                        "data: "
                        + json.dumps(
                            {
                                "type": "reasoning_done",
                                "duration_ms": reasoning_duration_ms,
                            },
                            ensure_ascii=False,
                        )
                        + "\n\n"
                    )

                ai_content += content
                yield f"data: {json.dumps(content, ensure_ascii=False)}\n\n"

            if reasoning_content and reasoning_duration_ms is None:
                reasoning_duration_ms = int((perf_counter() - request_started_at) * 1000)
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "reasoning_done",
                            "duration_ms": reasoning_duration_ms,
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )

            rag_sources = get_rag_sources()
            if rag_sources:
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "rag_sources",
                            "sources": rag_sources,
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )

            if chat_request.conversation_id:
                conversation_service.append_generated_exchange(
                    conversation_id=chat_request.conversation_id,
                    user_id=token_payload.user_id,
                    query=chat_request.query,
                    ai_content=ai_content,
                    rag_sources=rag_sources,
                    reasoning_content=reasoning_content or None,
                    reasoning_duration_ms=reasoning_duration_ms,
                    message_id=chat_request.message_id,
                    response_id=chat_request.response_id,
                )

            yield "data: [DONE]\n\n"
        finally:
            restore_rag_sources(rag_token)

    return StreamingResponse(
        stream_events(),
        media_type="text/event-stream",
    )
