import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from api.core.settings import Settings, get_settings


@dataclass(frozen=True)
class TokenPayload:
    user_id: int
    username: str


def _encode_json(data: dict[str, object]) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_json(data: str) -> dict[str, object]:
    padded = data + "=" * (-len(data) % 4)
    payload = base64.urlsafe_b64decode(padded.encode("ascii"))
    decoded = json.loads(payload.decode("utf-8"))

    if not isinstance(decoded, dict):
        raise ValueError("Invalid token payload")

    return decoded


def _sign(value: str, secret_key: str) -> str:
    digest = hmac.new(secret_key.encode("utf-8"), value.encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def create_access_token(
    user_id: int,
    username: str,
    secret_key: str,
    expires_delta: timedelta,
) -> str:
    expires_at = int(time.time() + expires_delta.total_seconds())
    payload = _encode_json({"sub": user_id, "username": username, "exp": expires_at})
    signature = _sign(payload, secret_key)
    return f"{payload}.{signature}"


def decode_access_token(token: str, secret_key: str) -> TokenPayload:
    try:
        payload_part, signature_part = token.split(".", maxsplit=1)
    except ValueError as exc:
        raise ValueError("Invalid token format") from exc

    expected_signature = _sign(payload_part, secret_key)
    if not hmac.compare_digest(signature_part, expected_signature):
        raise ValueError("Invalid token signature")

    payload = _decode_json(payload_part)
    expires_at = payload.get("exp")
    user_id = payload.get("sub")
    username = payload.get("username")

    if not isinstance(expires_at, int) or expires_at < int(time.time()):
        raise ValueError("Token expired")

    if not isinstance(user_id, int) or not isinstance(username, str):
        raise ValueError("Invalid token claims")

    return TokenPayload(user_id=user_id, username=username)


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="登录已过期或缺失，请重新登录",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_token_payload(
    authorization: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> TokenPayload:
    if authorization is None or not authorization.startswith("Bearer "):
        raise _credentials_exception()

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise _credentials_exception()

    try:
        return decode_access_token(token, settings.auth_secret_key)
    except ValueError as exc:
        raise _credentials_exception() from exc


async def verify_token(
    authorization: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    await get_current_token_payload(authorization=authorization, settings=settings)
