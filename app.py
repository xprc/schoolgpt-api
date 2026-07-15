import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.core.settings import SetupRequiredError, get_settings
from api.routes.admin import router as admin_router
from api.routes.auth import router as auth_router
from api.routes.chat import router as chat_router
from api.routes.conversations import router as conversations_router
from api.routes.memories import router as memories_router
from api.routes.rag_files import router as rag_files_router
from api.routes.setup import router as setup_router


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

    @app.exception_handler(SetupRequiredError)
    async def setup_required_handler(_, exc: SetupRequiredError) -> JSONResponse:
        return JSONResponse(
            status_code=428,
            content={"detail": str(exc)},
        )

    app.include_router(setup_router, prefix=settings.api_prefix)
    app.include_router(auth_router, prefix=settings.api_prefix)
    app.include_router(admin_router, prefix=settings.api_prefix)
    app.include_router(chat_router, prefix=settings.api_prefix)
    app.include_router(conversations_router, prefix=settings.api_prefix)
    app.include_router(memories_router, prefix=settings.api_prefix)
    app.include_router(rag_files_router, prefix=settings.api_prefix)
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8000)
