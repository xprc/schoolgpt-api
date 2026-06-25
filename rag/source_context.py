from contextvars import ContextVar, Token
from typing import Any

RagSource = dict[str, Any]

_rag_sources: ContextVar[list[RagSource]] = ContextVar("rag_sources", default=[])


def reset_rag_sources() -> Token[list[RagSource]]:
    return _rag_sources.set([])


def restore_rag_sources(token: Token[list[RagSource]]) -> None:
    _rag_sources.reset(token)


def add_rag_sources(sources: list[RagSource]) -> None:
    if not sources:
        return

    by_file = {
        str(source.get("file_name", "")): dict(source)
        for source in _rag_sources.get()
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

    _rag_sources.set(
        sorted(
            by_file.values(),
            key=lambda source: float(source.get("confidence", 0) or 0),
            reverse=True,
        )
    )


def get_rag_sources() -> list[RagSource]:
    return [dict(source) for source in _rag_sources.get()]
