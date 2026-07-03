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

    by_source = {
        _source_key(source): dict(source)
        for source in current_sources
        if _source_key(source)
    }

    for source in sources:
        file_name = str(source.get("file_name", "")).strip()
        if not file_name:
            continue

        confidence = float(source.get("confidence", 0) or 0)
        normalized_source = _normalize_source(source, file_name, confidence)
        source_key = _source_key(normalized_source)
        if not source_key:
            continue

        current = by_source.get(source_key)

        if current is None or confidence > float(current.get("confidence", 0) or 0):
            by_source[source_key] = normalized_source

    current_sources[:] = sorted(
        by_source.values(),
        key=lambda source: float(source.get("confidence", 0) or 0),
        reverse=True,
    )[:10]


def get_rag_sources() -> list[RagSource]:
    return [dict(source) for source in (_rag_sources.get() or [])]


def _source_key(source: RagSource) -> str:
    file_id = source.get("file_id")
    chunk_index = source.get("chunk_index")
    if file_id is not None and chunk_index is not None:
        return f"{file_id}:{chunk_index}"

    return str(source.get("file_name", "")).strip()


def _normalize_source(
    source: RagSource,
    file_name: str,
    confidence: float,
) -> RagSource:
    normalized_source: RagSource = {
        "file_name": file_name,
        "confidence": max(0, min(1, confidence)),
    }

    try:
        file_id = int(source.get("file_id"))
        normalized_source["file_id"] = file_id
    except (TypeError, ValueError):
        pass

    try:
        chunk_index = int(source.get("chunk_index"))
        normalized_source["chunk_index"] = chunk_index
    except (TypeError, ValueError):
        pass

    try:
        page_number = int(source.get("page_number"))
        normalized_source["page_number"] = page_number
    except (TypeError, ValueError):
        pass

    snippet = str(source.get("snippet", "") or "").strip()
    if snippet:
        normalized_source["snippet"] = snippet[:800]

    return normalized_source
