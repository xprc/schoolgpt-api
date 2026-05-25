from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from api.core.security import create_access_token, get_current_token_payload
from api.core.settings import Settings, get_settings
from api.schemas.auth import LoginRequest, LoginResponse, UserProfile
from api.services.user_service import User, UserService, get_user_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_user_profile(user: User) -> UserProfile:
    return UserProfile(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    settings: Settings = Depends(get_settings),
    user_service: UserService = Depends(get_user_service),
) -> LoginResponse:
    user = user_service.authenticate_user(request.identifier, request.password)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        user_id=user.id,
        username=user.username,
        secret_key=settings.auth_secret_key,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )

    return LoginResponse(access_token=access_token, user=_to_user_profile(user))


@router.get("/me", response_model=UserProfile)
async def read_current_user(
    token_payload=Depends(get_current_token_payload),
    user_service: UserService = Depends(get_user_service),
) -> UserProfile:
    user = user_service.get_user_by_id(token_payload.user_id)

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _to_user_profile(user)
