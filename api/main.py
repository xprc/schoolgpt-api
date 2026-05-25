from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.core.settings import get_settings
from api.routes.auth import router as auth_router
from api.routes.chat import router as chat_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.api_version)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(chat_router, prefix=settings.api_prefix)
    return app


app = create_app()
