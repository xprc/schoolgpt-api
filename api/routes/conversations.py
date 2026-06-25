from fastapi import APIRouter, Depends, HTTPException, status

from api.core.security import TokenPayload, get_current_token_payload
from api.schemas.chat import (
    ConversationPinRequest,
    ConversationMessageResponse,
    ConversationRenameRequest,
    ConversationResponse,
    ConversationShareRequest,
    ConversationSummaryResponse,
    ConversationUpsertRequest,
)
from api.services.conversation_service import (
    ConversationData,
    ConversationMessage,
    ConversationNotFoundError,
    ConversationPermissionError,
    ConversationService,
    ConversationSummary,
    get_conversation_service,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _not_found_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="对话不存在或无权访问",
    )


def _permission_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="没有权限修改该对话",
    )


def _to_message_response(message: ConversationMessage) -> ConversationMessageResponse:
    return ConversationMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        rag_sources=message.rag_sources,
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


def _to_conversation_response(conversation: ConversationData) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        owner_user_id=conversation.owner_user_id,
        share_scope=conversation.share_scope,
        permission=conversation.permission,
        can_write=conversation.can_write,
        is_pinned=conversation.is_pinned,
        pinned_at=conversation.pinned_at,
        is_visible=conversation.is_visible,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[_to_message_response(message) for message in conversation.messages],
    )


def _to_summary_response(summary: ConversationSummary) -> ConversationSummaryResponse:
    return ConversationSummaryResponse(
        id=summary.id,
        title=summary.title,
        share_scope=summary.share_scope,
        permission=summary.permission,
        can_write=summary.can_write,
        is_pinned=summary.is_pinned,
        pinned_at=summary.pinned_at,
        is_visible=summary.is_visible,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


@router.get("", response_model=list[ConversationSummaryResponse])
async def list_conversations(
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: ConversationService = Depends(get_conversation_service),
) -> list[ConversationSummaryResponse]:
    return [
        _to_summary_response(summary)
        for summary in service.list_conversations(token_payload.user_id)
    ]


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationResponse:
    try:
        conversation = service.get_conversation(conversation_id, token_payload.user_id)
    except ConversationNotFoundError as exc:
        raise _not_found_exception() from exc

    return _to_conversation_response(conversation)


@router.put("/{conversation_id}", response_model=ConversationResponse)
async def save_conversation(
    conversation_id: str,
    request: ConversationUpsertRequest,
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationResponse:
    try:
        conversation = service.save_conversation(
            conversation_id=conversation_id,
            user_id=token_payload.user_id,
            title=request.title,
            share_scope=request.share_scope,
            messages=request.messages,
        )
    except ConversationNotFoundError as exc:
        raise _not_found_exception() from exc
    except ConversationPermissionError as exc:
        raise _permission_exception() from exc
    except ValueError as exc:
        raise _not_found_exception() from exc

    return _to_conversation_response(conversation)


@router.patch("/{conversation_id}/rename", response_model=ConversationResponse)
async def rename_conversation(
    conversation_id: str,
    request: ConversationRenameRequest,
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationResponse:
    try:
        conversation = service.rename_conversation(
            conversation_id=conversation_id,
            user_id=token_payload.user_id,
            title=request.title,
        )
    except ConversationNotFoundError as exc:
        raise _not_found_exception() from exc
    except ConversationPermissionError as exc:
        raise _permission_exception() from exc
    except ValueError as exc:
        raise _not_found_exception() from exc

    return _to_conversation_response(conversation)


@router.patch("/{conversation_id}/pin", response_model=ConversationResponse)
async def update_conversation_pin(
    conversation_id: str,
    request: ConversationPinRequest,
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationResponse:
    try:
        conversation = service.update_pin_state(
            conversation_id=conversation_id,
            user_id=token_payload.user_id,
            is_pinned=request.is_pinned,
        )
    except ConversationNotFoundError as exc:
        raise _not_found_exception() from exc
    except ConversationPermissionError as exc:
        raise _permission_exception() from exc
    except ValueError as exc:
        raise _not_found_exception() from exc

    return _to_conversation_response(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: ConversationService = Depends(get_conversation_service),
) -> None:
    try:
        service.hide_conversation(conversation_id, token_payload.user_id)
    except ConversationNotFoundError as exc:
        raise _not_found_exception() from exc
    except ConversationPermissionError as exc:
        raise _permission_exception() from exc
    except ValueError as exc:
        raise _not_found_exception() from exc


@router.patch("/{conversation_id}/share", response_model=ConversationResponse)
async def update_conversation_share(
    conversation_id: str,
    request: ConversationShareRequest,
    token_payload: TokenPayload = Depends(get_current_token_payload),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationResponse:
    try:
        conversation = service.update_share_scope(
            conversation_id=conversation_id,
            user_id=token_payload.user_id,
            share_scope=request.share_scope,
        )
    except ConversationNotFoundError as exc:
        raise _not_found_exception() from exc
    except ConversationPermissionError as exc:
        raise _permission_exception() from exc
    except ValueError as exc:
        raise _not_found_exception() from exc

    return _to_conversation_response(conversation)
