from contextvars import ContextVar, Token


_current_user_id: ContextVar[int | None] = ContextVar(
    "schoolgpt_agent_user_id",
    default=None,
)


def set_current_agent_user_id(user_id: int | None) -> Token[int | None]:
    return _current_user_id.set(user_id)


def reset_current_agent_user_id(token: Token[int | None]) -> None:
    _current_user_id.reset(token)


def get_current_agent_user_id() -> int | None:
    return _current_user_id.get()
