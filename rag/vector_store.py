import hashlib
import json
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import tiktoken
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from api.services.rag_file_service import (
    RagFileRecord,
    get_rag_file_service,
    structured_content_text_blocks,
)
from model.factory import embedding_model
from utils.config_handler import chroma_conf
from utils.logger_handler import logger
from utils.path_tools import get_abs_path

_token_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_token_encoder.encode(text))


class VectorStoreService:
    def __init__(self) -> None:
        self.collection_name = chroma_conf["collection_name"]
        self.persist_directory = self._resolve_project_path(chroma_conf["persist_directory"])
        self.data_path = self._resolve_project_path(chroma_conf["data_path"])
        self.rag_file_service = get_rag_file_service()
        self.allowed_file_types = tuple(self.rag_file_service.allowed_file_types())
        self.index_version = (
            f"chunk-{chroma_conf['chunk_size']}-overlap-{chroma_conf['chunk_overlap']}"
        )
        self._lock = threading.RLock()

        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.data_path.mkdir(parents=True, exist_ok=True)

        self.vector_store = Chroma(
            collection_name=self.collection_name,
            embedding_function=embedding_model,
            persist_directory=str(self.persist_directory),
        )
        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf["chunk_size"],
            chunk_overlap=chroma_conf["chunk_overlap"],
            separators=[
                "\n\n",
                "\n",
                "\u3002",
                "\uff01",
                "\uff1f",
                ".",
                "!",
                "?",
                "\uff1b",
                ";",
                "\uff0c",
                ",",
                " ",
                "",
            ],
            is_separator_regex=False,
            length_function=count_tokens,
        )

    @staticmethod
    def _resolve_project_path(path_value: str) -> Path:
        path = Path(path_value)
        if path.is_absolute():
            return path
        return Path(get_abs_path(path_value))

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_retriever(self):
        search_kwargs = {
            "k": chroma_conf["k"],
            "score_threshold": chroma_conf["score_threshold"],
        }

        if chroma_conf["filter"] is not None:
            search_kwargs["filter"] = chroma_conf["filter"]

        return self.vector_store.as_retriever(
            search_type="similarity_score_threshold",
            search_kwargs=search_kwargs,
        )

    def similarity_search_with_sources(self, query: str) -> list[dict[str, Any]]:
        search_kwargs: dict[str, Any] = {
            "k": chroma_conf["k"],
        }

        if chroma_conf["filter"] is not None:
            search_kwargs["filter"] = chroma_conf["filter"]

        try:
            scored_docs = self.vector_store.similarity_search_with_relevance_scores(
                query,
                score_threshold=chroma_conf["score_threshold"],
                **search_kwargs,
            )
            normalize_score = self._normalize_relevance_score
        except Exception:
            scored_docs = self.vector_store.similarity_search_with_score(
                query,
                **search_kwargs,
            )
            normalize_score = self._distance_to_confidence

        results = []

        for document, raw_score in scored_docs:
            metadata = document.metadata
            if not self._is_current_rag_metadata(metadata):
                continue

            confidence = normalize_score(float(raw_score))
            if confidence < float(chroma_conf["score_threshold"]):
                continue

            results.append(
                {
                    "document": document,
                    "file_id": self._metadata_file_id(metadata),
                    "file_name": self._metadata_file_name(metadata),
                    "chunk_index": self._metadata_chunk_index(metadata),
                    "page_number": self._metadata_page_number(metadata),
                    "snippet": self._snippet(document.page_content),
                    "confidence": confidence,
                }
            )

        return results

    def get_chunk_detail(self, file_id: int, chunk_index: int) -> dict[str, Any] | None:
        try:
            result = self.vector_store.get(where={"file_id": int(file_id)})
        except Exception as exc:
            logger.warning("[RAG] Failed to read chunk %s:%s: %s", file_id, chunk_index, str(exc))
            return None

        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])

        for document_text, metadata in zip(documents, metadatas):
            if not metadata:
                continue

            if (
                metadata.get("chunk_index") == int(chunk_index)
                and metadata.get("index_version") == self.index_version
            ):
                return {
                    "file_id": int(file_id),
                    "file_name": self._metadata_file_name(metadata),
                    "chunk_index": int(chunk_index),
                    "page_number": self._metadata_page_number(metadata),
                    "snippet": self._snippet(str(document_text or ""), limit=1200),
                    "metadata": metadata,
                }

        return None

    def get_status(self) -> dict[str, Any]:
        files = self.list_knowledge_files()
        indexed_files = sum(1 for file_info in files if file_info["indexed"])

        return {
            "collection_name": self.collection_name,
            "data_path": chroma_conf["data_path"],
            "persist_directory": chroma_conf["persist_directory"],
            "allowed_file_types": list(self.allowed_file_types),
            "total_files": len(files),
            "indexed_files": indexed_files,
            "vector_count": self._vector_count(),
            "files": files,
        }

    def list_knowledge_files(self) -> list[dict[str, Any]]:
        return [self._file_info(file_record) for file_record in self.rag_file_service.list_files()]

    def delete_knowledge_file(self, file_id: int) -> None:
        self.rag_file_service.delete_file(file_id)
        self.sync_documents()

    def sync_file(self, file_id: int) -> dict[str, int]:
        with self._lock:
            file_record = self.rag_file_service.get_file(file_id, include_content=True)
            if file_record is None:
                raise FileNotFoundError("文件不存在")

            indexed_chunks, skipped_files, _ = self._sync_file_record(file_record)
            if skipped_files:
                raise ValueError("文件未生成可入库分片")

            return {
                "indexed_chunks": indexed_chunks,
                "skipped_files": skipped_files,
            }

    def sync_documents(self) -> dict[str, Any]:
        with self._lock:
            indexed_chunks = 0
            skipped_files = 0
            expected_document_ids: set[str] = set()
            sync_had_errors = False
            failed_file_ids: list[int] = []

            for file_record in self.rag_file_service.list_indexable_files():
                try:
                    synced_chunks, skipped_count, document_ids = self._sync_file_record(
                        file_record
                    )
                    indexed_chunks += synced_chunks
                    skipped_files += skipped_count
                    expected_document_ids.update(document_ids)
                except Exception as exc:
                    sync_had_errors = True
                    failed_file_ids.append(file_record.id)
                    self.rag_file_service.mark_file_failed(file_record.id, str(exc))
                    logger.error(
                        "[RAG] Failed to sync %s: %s",
                        file_record.original_name,
                        str(exc),
                        exc_info=True,
                    )

            if not sync_had_errors:
                self._delete_unexpected_vectors(expected_document_ids)

            return {
                "indexed_chunks": indexed_chunks,
                "skipped_files": skipped_files,
                "failed_files": len(failed_file_ids),
                "failed_file_ids": failed_file_ids,
            }

    def rebuild_database(self) -> dict[str, Any]:
        with self._lock:
            deleted_vectors = self._delete_all_vectors()
            sync_result = self.sync_documents()
            return {
                "deleted_vectors": deleted_vectors,
                **sync_result,
            }

    def _sync_file_record(
        self,
        file_record: RagFileRecord,
    ) -> tuple[int, int, list[str]]:
        split_documents, document_ids = self._build_documents(file_record)

        if not split_documents:
            self.rag_file_service.update_chunk_count(file_record.id, 0)
            logger.warning(
                "[RAG] Skip %s because it has no valid chunks.",
                file_record.original_name,
            )
            return 0, 1, []

        if self._vectors_exist(document_ids):
            self.rag_file_service.update_chunk_count(
                file_record.id,
                len(split_documents),
            )
            return 0, 0, document_ids

        self._delete_vectors_for_file(file_record.id)
        self.vector_store.add_documents(split_documents, ids=document_ids)
        self.rag_file_service.update_chunk_count(file_record.id, len(split_documents))
        logger.info(
            "[RAG] Synced %s to %s.",
            file_record.original_name,
            chroma_conf["persist_directory"],
        )

        return len(split_documents), 0, document_ids

    def _file_info(self, file_record: RagFileRecord) -> dict[str, Any]:
        chunk_count = self._chunk_count_for_file(file_record.id, file_record.sha256)

        return {
            "id": file_record.id,
            "name": file_record.original_name,
            "size": file_record.size_bytes,
            "modified_at": file_record.updated_at,
            "sha256": file_record.sha256,
            "status": file_record.status,
            "error_message": file_record.error_message,
            "indexed": file_record.status == "ready" and chunk_count > 0,
            "chunk_count": chunk_count,
            "used_ocr": file_record.used_ocr,
        }

    def _build_documents(self, file_record: RagFileRecord) -> tuple[list[Document], list[str]]:
        blocks = structured_content_text_blocks(file_record.content_json)
        if not blocks:
            return [], []

        source_ref = f"rag_files/{file_record.id}"
        documents = []
        for block in blocks:
            documents.append(
                Document(
                    page_content=str(block["text"]),
                    metadata={
                        "source": source_ref,
                        "file_path": file_record.preview_pdf_path,
                        "file_id": file_record.id,
                        "file_name": file_record.original_name,
                        "file_sha256": file_record.sha256,
                        "source_format": "structured-json",
                        "page_number": int(block["page_number"]),
                        "block_id": str(block["id"]),
                        "block_type": str(block["type"]),
                        "bbox_json": (
                            json.dumps(block["bbox"], ensure_ascii=False)
                            if block.get("bbox") is not None
                            else ""
                        ),
                    },
                )
            )

        split_documents = self.spliter.split_documents(documents)
        source_key = hashlib.sha1(str(file_record.id).encode("utf-8")).hexdigest()[:16]
        indexed_at = self._utc_now()
        document_ids = []

        for index, document in enumerate(split_documents):
            document.metadata = {
                **document.metadata,
                "source": source_ref,
                "file_path": file_record.preview_pdf_path,
                "file_id": file_record.id,
                "file_name": file_record.original_name,
                "file_sha256": file_record.sha256,
                "source_format": "structured-json",
                "chunk_index": index,
                "index_version": self.index_version,
                "indexed_at": indexed_at,
            }
            document_ids.append(
                f"{source_key}:{file_record.sha256}:{self.index_version}:{index}"
            )

        return split_documents, document_ids

    @staticmethod
    def _metadata_file_name(metadata: dict[str, Any]) -> str:
        file_name = metadata.get("file_name")
        if isinstance(file_name, str) and file_name.strip():
            return file_name

        return "unknown"

    @staticmethod
    def _metadata_file_id(metadata: dict[str, Any]) -> int | None:
        file_id = metadata.get("file_id")
        try:
            return int(file_id)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _metadata_chunk_index(metadata: dict[str, Any]) -> int | None:
        chunk_index = metadata.get("chunk_index")
        try:
            return int(chunk_index)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _metadata_page_number(metadata: dict[str, Any]) -> int | None:
        page_number = metadata.get("page_number")
        try:
            return int(page_number)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _snippet(text: str, limit: int = 280) -> str:
        normalized = " ".join(str(text or "").split())
        if len(normalized) <= limit:
            return normalized

        return normalized[:limit].rstrip() + "..."

    def _is_current_rag_metadata(self, metadata: dict[str, Any]) -> bool:
        return (
            self._metadata_file_id(metadata) is not None
            and self._metadata_chunk_index(metadata) is not None
            and isinstance(metadata.get("file_sha256"), str)
            and bool(str(metadata.get("file_sha256")).strip())
            and metadata.get("source_format") == "structured-json"
            and metadata.get("index_version") == self.index_version
        )

    @staticmethod
    def _normalize_relevance_score(score: float) -> float:
        return max(0, min(1, score))

    @staticmethod
    def _distance_to_confidence(distance: float) -> float:
        return 1 / (1 + max(0, distance))

    def _vectors_exist(self, document_ids: list[str]) -> bool:
        if not document_ids:
            return False

        result = self.vector_store.get(ids=document_ids)
        return set(result.get("ids", [])) == set(document_ids)

    def _chunk_count_for_file(self, file_id: int, sha256: str) -> int:
        try:
            result = self.vector_store.get(where={"file_id": file_id})
        except Exception as exc:
            logger.warning("[RAG] Failed to inspect vectors for %s: %s", file_id, str(exc))
            return 0

        metadatas = result.get("metadatas", [])
        chunk_count = sum(
            1
            for metadata in metadatas
            if metadata
            and metadata.get("file_sha256") == sha256
            and metadata.get("source_format") == "structured-json"
            and metadata.get("index_version") == self.index_version
        )
        self.rag_file_service.update_chunk_count(file_id, chunk_count)
        return chunk_count

    def _vector_count(self) -> int:
        try:
            metadatas = self.vector_store.get().get("metadatas", [])
        except Exception as exc:
            logger.warning("[RAG] Failed to count vectors: %s", str(exc))
            return 0

        return sum(
            1
            for metadata in metadatas
            if metadata and self._is_current_rag_metadata(metadata)
        )

    def _delete_vectors_for_file(self, file_id: int) -> None:
        collection = getattr(self.vector_store, "_collection", None)

        if collection is None:
            return

        collection.delete(where={"file_id": file_id})

    def _delete_unexpected_vectors(self, expected_document_ids: set[str]) -> None:
        try:
            result = self.vector_store.get()
            existing_ids = set(result.get("ids", []))
        except Exception as exc:
            logger.warning("[RAG] Failed to inspect existing vectors: %s", str(exc))
            return

        stale_ids = sorted(existing_ids - expected_document_ids)

        if not stale_ids:
            return

        self.vector_store.delete(ids=stale_ids)
        logger.info("[RAG] Pruned %s stale vectors from %s.", len(stale_ids), chroma_conf["persist_directory"])

    def _delete_all_vectors(self) -> int:
        result = self.vector_store.get()
        vector_ids = result.get("ids", [])

        if not vector_ids:
            return 0

        self.vector_store.delete(ids=vector_ids)
        return len(vector_ids)


@lru_cache(maxsize=1)
def get_vector_store_service() -> VectorStoreService:
    return VectorStoreService()
