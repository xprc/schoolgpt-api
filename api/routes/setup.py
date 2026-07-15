from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from api.core.settings import is_setup_complete
from api.schemas.setup import FirstRunSetupRequest, SetupStatusResponse
from api.services.conversation_service import get_conversation_service
from model.config_service import get_model_config_service
from api.services.setup_service import (
    SetupAlreadyCompleteError,
    initialize_first_run,
)
from api.services.user_service import get_user_service

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/status", response_model=SetupStatusResponse)
async def get_setup_status() -> SetupStatusResponse:
    return SetupStatusResponse(is_configured=is_setup_complete())


@router.post("", response_model=SetupStatusResponse)
async def create_first_run_setup(
    request: FirstRunSetupRequest,
) -> SetupStatusResponse:
    try:
        initialize_first_run(request)
    except SetupAlreadyCompleteError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="首次运行配置已完成",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"数据库初始化失败：{exc}",
        ) from exc

    get_user_service.cache_clear()
    get_conversation_service.cache_clear()
    get_model_config_service.cache_clear()
    return SetupStatusResponse(is_configured=True)
