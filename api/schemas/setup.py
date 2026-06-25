from pydantic import BaseModel, Field


class SetupStatusResponse(BaseModel):
    is_configured: bool


class SetupDatabaseRequest(BaseModel):
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(3306, ge=1, le=65535)
    username: str = Field(..., min_length=1, max_length=120)
    password: str = Field("", max_length=255)
    database: str = Field(..., min_length=1, max_length=64)


class FirstRunSetupRequest(BaseModel):
    database: SetupDatabaseRequest
    admin_username: str = Field(..., min_length=1, max_length=64)
    admin_email: str = Field(..., min_length=3, max_length=120)
    admin_password: str = Field(..., min_length=6, max_length=128)
    admin_display_name: str = Field(..., min_length=1, max_length=120)
