from contextvars import ContextVar, Token
from typing import Any

RagSource = dict[str, Any]

_rag_sources: ContextVar[list[RagSource] | None] = ContextVar(
    "rag_sources",
    default=None,
)


def reset_rag_sources() -> Token[list[RagSource] | None]:
    return _rag_sources.set([])


def restore_rag_sources(token: Token[list[RagSource] | None]) -> None:
    _rag_sources.reset(token)


def add_rag_sources(sources: list[RagSource]) -> None:
    if not sources:
        return

    current_sources = _rag_sources.get()
    if current_sources is None:
        current_sources = []
        _rag_sources.set(current_sources)

    by_file = {
        str(source.get("file_name", "")): dict(source)
        for source in current_sources
        if source.get("file_name")
    }

    for source in sources:
        file_name = str(source.get("file_name", "")).strip()
        if not file_name:
            continue

        confidence = float(source.get("confidence", 0) or 0)
        current = by_file.get(file_name)

        if current is None or confidence > float(current.get("confidence", 0) or 0):
            by_file[file_name] = {
                "file_name": file_name,
                "confidence": max(0, min(1, confidence)),
            }

    current_sources[:] = sorted(
        by_file.values(),
        key=lambda source: float(source.get("confidence", 0) or 0),
        reverse=True,
    )


def get_rag_sources() -> list[RagSource]:
    return [dict(source) for source in (_rag_sources.get() or [])]
