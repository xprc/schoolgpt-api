from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError

from api.core.security import TokenPayload, get_current_token_payload
from api.schemas.admin import (
    AdminConversationResponse,
    AdminConversationVisibilityRequest,
    AdminDashboardResponse,
    AdminUserCreateRequest,
    AdminUserPasswordRequest,
    AdminUserResponse,
    AdminUserUpdateRequest,
    ModelConfigResponse,
    ModelConfigUpdateRequest,
    ModelProviderOptionResponse,
)
from api.services.conversation_service import (
    AdminConversationSummary,
    ConversationService,
    get_conversation_service,
)
from api.services.model_config_service import (
    ModelConfig,
    ModelConfigService,
    ModelProviderOption,
    get_model_config_service,
)
from api.services.user_service import (
    AdminUser,
    User,
    UserService,
    get_user_service,
)

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin_user(
    token_payload: TokenPayload = Depends(get_current_token_payload),
    user_service: UserService = Depends(get_user_service),
) -> User:
    user = user_service.get_user_by_id(token_payload.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
        )

    if user.user_type != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )

    return user


def _api_key_mask(api_key: str) -> str:
    if not api_key:
        return ""

    if len(api_key) <= 8:
        return "********"

    return f"{api_key[:4]}****{api_key[-4:]}"


def _to_admin_user_response(user: AdminUser) -> AdminUserResponse:
    return AdminUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        avatar_sha256=user.avatar_sha256,
        display_name=user.display_name,
        user_type=user.user_type,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


def _to_admin_conversation_response(
    conversation: AdminConversationSummary,
) -> AdminConversationResponse:
    return AdminConversationResponse(
        id=conversation.id,
        title=conversation.title,
        owner_user_id=conversation.owner_user_id,
        owner_username=conversation.owner_username,
        owner_email=conversation.owner_email,
        share_scope=conversation.share_scope,
        is_visible=conversation.is_visible,
        message_count=conversation.message_count,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _to_model_config_response(model_config: ModelConfig) -> ModelConfigResponse:
    return ModelConfigResponse(
        id=model_config.id,
        provider=model_config.provider,
        provider_label=model_config.provider_label,
        model_name=model_config.model_name,
        base_url=model_config.base_url,
        api_path=model_config.api_path,
        has_api_key=bool(model_config.api_key.strip()),
        api_key_mask=_api_key_mask(model_config.api_key.strip()),
        is_active=model_config.is_active,
        created_at=model_config.created_at,
        updated_at=model_config.updated_at,
    )


def _to_provider_option_response(
    option: ModelProviderOption,
) -> ModelProviderOptionResponse:
    return ModelProviderOptionResponse(
        provider=option.provider,
        label=option.label,
        base_url=option.base_url,
        api_path=option.api_path,
        models=list(option.models),
    )


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def get_dashboard(
    _: User = Depends(require_admin_user),
    user_service: UserService = Depends(get_user_service),
    conversation_service: ConversationService = Depends(get_conversation_service),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
) -> AdminDashboardResponse:
    user_totals = user_service.get_user_totals()
    conversation_totals = conversation_service.get_conversation_totals()
    return AdminDashboardResponse(
        total_users=user_totals["total_users"],
        active_users=user_totals["active_users"],
        users_by_type=user_service.get_user_type_counts(),
        total_conversations=conversation_totals.total_conversations,
        visible_conversations=conversation_totals.visible_conversations,
        total_messages=conversation_totals.total_messages,
        active_model=_to_model_config_response(
            model_config_service.get_active_model_config()
        ),
    )


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    _: User = Depends(require_admin_user),
    user_service: UserService = Depends(get_user_service),
) -> list[AdminUserResponse]:
    return [_to_admin_user_response(user) for user in user_service.list_admin_users()]


@router.post("/users", response_model=AdminUserResponse)
async def create_user(
    request: AdminUserCreateRequest,
    _: User = Depends(require_admin_user),
    user_service: UserService = Depends(get_user_service),
) -> AdminUserResponse:
    try:
        user = user_service.create_admin_user(
            username=request.username,
            email=request.email,
            password=request.password,
            display_name=request.display_name,
            user_type=request.user_type,
            is_active=request.is_active,
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名、邮箱或头像哈希已存在",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return _to_admin_user_response(user)


@router.put("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: int,
    request: AdminUserUpdateRequest,
    current_admin: User = Depends(require_admin_user),
    user_service: UserService = Depends(get_user_service),
) -> AdminUserResponse:
    if user_id == current_admin.id and (
        request.user_type != "admin" or not request.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能取消当前账号的管理员权限或禁用当前账号",
        )

    try:
        user = user_service.update_admin_user(
            user_id=user_id,
            username=request.username,
            email=request.email,
            display_name=request.display_name,
            user_type=request.user_type,
            is_active=request.is_active,
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名、邮箱或头像哈希已存在",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    return _to_admin_user_response(user)


@router.patch("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def update_user_password(
    user_id: int,
    request: AdminUserPasswordRequest,
    _: User = Depends(require_admin_user),
    user_service: UserService = Depends(get_user_service),
) -> None:
    if not user_service.update_admin_user_password(user_id, request.password):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )


@router.get("/conversations", response_model=list[AdminConversationResponse])
async def list_conversations(
    _: User = Depends(require_admin_user),
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> list[AdminConversationResponse]:
    return [
        _to_admin_conversation_response(conversation)
        for conversation in conversation_service.list_admin_conversations()
    ]


@router.patch(
    "/conversations/{conversation_id}/visibility",
    response_model=AdminConversationResponse,
)
async def update_conversation_visibility(
    conversation_id: str,
    request: AdminConversationVisibilityRequest,
    _: User = Depends(require_admin_user),
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> AdminConversationResponse:
    try:
        conversation = conversation_service.update_admin_visibility(
            conversation_id,
            request.is_visible,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在",
        ) from exc

    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在",
        )

    return _to_admin_conversation_response(conversation)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    _: User = Depends(require_admin_user),
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> None:
    try:
        deleted = conversation_service.delete_admin_conversation(conversation_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在",
        ) from exc

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="对话不存在",
        )


@router.get("/model-config", response_model=ModelConfigResponse)
async def get_model_config(
    _: User = Depends(require_admin_user),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
) -> ModelConfigResponse:
    return _to_model_config_response(model_config_service.get_active_model_config())


@router.get("/model-config/providers", response_model=list[ModelProviderOptionResponse])
async def get_model_provider_options(
    _: User = Depends(require_admin_user),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
) -> list[ModelProviderOptionResponse]:
    return [
        _to_provider_option_response(option)
        for option in model_config_service.get_provider_options()
    ]


@router.put("/model-config", response_model=ModelConfigResponse)
async def update_model_config(
    request: ModelConfigUpdateRequest,
    _: User = Depends(require_admin_user),
    model_config_service: ModelConfigService = Depends(get_model_config_service),
) -> ModelConfigResponse:
    try:
        model_config = model_config_service.update_active_model_config(
            provider=request.provider,
            model_name=request.model_name,
            base_url=request.base_url,
            api_path=request.api_path,
            api_key=request.api_key,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return _to_model_config_response(model_config)
