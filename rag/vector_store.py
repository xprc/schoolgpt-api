import hashlib
import threading
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import tiktoken
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from model.factory import embedding_model
from utils.config_handler import chroma_conf
from utils.file_handler import (
    csv_loader,
    get_file_md5_hex,
    listdir_with_allowed_type,
    pdf_loader,
    txt_loader,
)
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
        self.allowed_file_types = tuple(chroma_conf["allow_knowledge_file_type"])
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

    @property
    def _allowed_exts(self) -> tuple[str, ...]:
        return tuple(
            file_type.lower() if file_type.startswith(".") else f".{file_type.lower()}"
            for file_type in self.allowed_file_types
        )

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
            confidence = normalize_score(float(raw_score))
            if confidence < float(chroma_conf["score_threshold"]):
                continue

            results.append(
                {
                    "document": document,
                    "file_name": self._metadata_file_name(document.metadata),
                    "confidence": confidence,
                }
            )

        return results

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
        files = listdir_with_allowed_type(self.data_path, self.allowed_file_types)
        return [self._file_info(path) for path in sorted(files, key=lambda item: item.name)]

    def resolve_upload_target(self, filename: str) -> Path:
        safe_name = Path(filename).name.strip()

        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("文件名无效")

        suffix = Path(safe_name).suffix.lower()
        if suffix not in self._allowed_exts:
            allowed = ", ".join(self.allowed_file_types)
            raise ValueError(f"仅支持上传以下文件类型: {allowed}")

        target_path = (self.data_path / safe_name).resolve()
        data_root = self.data_path.resolve()

        if target_path.parent != data_root:
            raise ValueError("文件名无效")

        return target_path

    def delete_knowledge_file(self, filename: str) -> None:
        target_path = self.resolve_upload_target(filename)

        if not target_path.exists() or not target_path.is_file():
            raise FileNotFoundError("文件不存在")

        target_path.unlink()
        self.sync_documents()

    def sync_documents(self) -> dict[str, int]:
        with self._lock:
            indexed_chunks = 0
            skipped_files = 0
            expected_document_ids: set[str] = set()
            sync_had_errors = False

            for path in self._list_data_files():
                md5_hex = get_file_md5_hex(path)

                if not md5_hex:
                    skipped_files += 1
                    logger.warning("[RAG] Skip %s because MD5 calculation failed.", path.name)
                    continue

                try:
                    split_documents, document_ids = self._build_documents(path, md5_hex)

                    if not split_documents:
                        skipped_files += 1
                        logger.warning("[RAG] Skip %s because it has no valid chunks.", path.name)
                        continue

                    expected_document_ids.update(document_ids)

                    if self._vectors_exist(document_ids):
                        continue

                    self._delete_vectors_for_file(path.name)
                    self.vector_store.add_documents(split_documents, ids=document_ids)
                    indexed_chunks += len(split_documents)
                    logger.info("[RAG] Synced %s to %s.", path.name, chroma_conf["persist_directory"])

                except Exception as exc:
                    sync_had_errors = True
                    logger.error("[RAG] Failed to sync %s: %s", path.name, str(exc), exc_info=True)

            if not sync_had_errors:
                self._delete_unexpected_vectors(expected_document_ids)

            return {
                "indexed_chunks": indexed_chunks,
                "skipped_files": skipped_files,
            }

    def rebuild_database(self) -> dict[str, int]:
        with self._lock:
            deleted_vectors = self._delete_all_vectors()
            sync_result = self.sync_documents()
            return {
                "deleted_vectors": deleted_vectors,
                **sync_result,
            }

    def _list_data_files(self) -> tuple[Path, ...]:
        return listdir_with_allowed_type(self.data_path, self.allowed_file_types)

    def _file_info(self, path: Path) -> dict[str, Any]:
        md5_hex = get_file_md5_hex(path) or ""
        chunk_count = self._chunk_count_for_file(path.name, md5_hex)
        stat = path.stat()

        return {
            "name": path.name,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "md5": md5_hex,
            "indexed": chunk_count > 0,
            "chunk_count": chunk_count,
        }

    def _build_documents(self, path: Path, md5_hex: str) -> tuple[list[Document], list[str]]:
        documents = self._load_file_documents(path)

        if not documents:
            return [], []

        split_documents = self.spliter.split_documents(documents)
        source_ref = f"{Path(chroma_conf['data_path']).name}/{path.name}"
        source_key = hashlib.sha1(path.name.encode("utf-8")).hexdigest()[:16]
        indexed_at = self._utc_now()
        document_ids = []

        for index, document in enumerate(split_documents):
            document.metadata = {
                **document.metadata,
                "source": source_ref,
                "file_path": source_ref,
                "file_name": path.name,
                "file_md5": md5_hex,
                "chunk_index": index,
                "index_version": self.index_version,
                "indexed_at": indexed_at,
            }
            document_ids.append(f"{source_key}:{md5_hex}:{self.index_version}:{index}")

        return split_documents, document_ids

    @staticmethod
    def _metadata_file_name(metadata: dict[str, Any]) -> str:
        file_name = metadata.get("file_name")
        if isinstance(file_name, str) and file_name.strip():
            return file_name

        source = metadata.get("source") or metadata.get("file_path")
        if isinstance(source, str) and source.strip():
            return Path(source).name

        return "unknown"

    @staticmethod
    def _normalize_relevance_score(score: float) -> float:
        return max(0, min(1, score))

    @staticmethod
    def _distance_to_confidence(distance: float) -> float:
        return 1 / (1 + max(0, distance))

    @staticmethod
    def _load_file_documents(path: Path) -> list[Document]:
        suffix = path.suffix.lower()

        if suffix == ".txt":
            return txt_loader(path)
        if suffix == ".pdf":
            return pdf_loader(path)
        if suffix == ".csv":
            return csv_loader(path, source_column="source")

        logger.warning("[RAG] Unsupported file type skipped: %s", suffix)
        return []

    def _vectors_exist(self, document_ids: list[str]) -> bool:
        if not document_ids:
            return False

        result = self.vector_store.get(ids=document_ids)
        return set(result.get("ids", [])) == set(document_ids)

    def _chunk_count_for_file(self, filename: str, md5_hex: str) -> int:
        try:
            result = self.vector_store.get(where={"file_name": filename})
        except Exception as exc:
            logger.warning("[RAG] Failed to inspect vectors for %s: %s", filename, str(exc))
            return 0

        metadatas = result.get("metadatas", [])
        return sum(
            1
            for metadata in metadatas
            if metadata
            and metadata.get("file_md5") == md5_hex
            and metadata.get("index_version") == self.index_version
        )

    def _vector_count(self) -> int:
        collection = getattr(self.vector_store, "_collection", None)

        if collection is None:
            return len(self.vector_store.get().get("ids", []))

        return collection.count()

    def _delete_vectors_for_file(self, filename: str) -> None:
        collection = getattr(self.vector_store, "_collection", None)

        if collection is None:
            return

        collection.delete(where={"file_name": filename})

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
