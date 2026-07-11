import json
import mimetypes
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import create_engine, text

from api.core.settings import get_database_url


CREATE_PADDLE_OCR_CONFIGS_SQL = """
CREATE TABLE IF NOT EXISTS paddle_ocr_configs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    provider VARCHAR(32) NOT NULL DEFAULT 'baidu_aistudio',
    api_key VARCHAR(1024) NOT NULL DEFAULT '',
    model_name VARCHAR(64) NOT NULL DEFAULT 'PaddleOCR-VL-1.5',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_paddle_ocr_configs_provider (provider)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""

PADDLE_OCR_PROVIDER = "baidu_aistudio"
PADDLE_OCR_PROVIDER_LABEL = "百度 AI Studio PaddleOCR"
PADDLE_OCR_MODEL = "PaddleOCR-VL-1.5"
PADDLE_OCR_JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
PADDLE_OCR_LOCAL_FILE_LIMIT = 50 * 1024 * 1024


@dataclass(frozen=True)
class PaddleOcrConfig:
    id: int
    provider: str
    provider_label: str
    api_key: str
    model_name: str
    created_at: str
    updated_at: str


def _isoformat(value: object) -> str:
    if isinstance(value, datetime):
        normalized = value
    else:
        normalized = datetime.now(timezone.utc)

    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)

    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _row_to_config(row: Mapping[str, object]) -> PaddleOcrConfig:
    return PaddleOcrConfig(
        id=int(row["id"]),
        provider=str(row["provider"]),
        provider_label=PADDLE_OCR_PROVIDER_LABEL,
        api_key=str(row["api_key"] or ""),
        model_name=str(row["model_name"] or PADDLE_OCR_MODEL),
        created_at=_isoformat(row["created_at"]),
        updated_at=_isoformat(row["updated_at"]),
    )


class PaddleOcrConfigService:
    def __init__(self) -> None:
        self._engine = create_engine(
            get_database_url(),
            pool_pre_ping=True,
            pool_recycle=1800,
            future=True,
        )
        self._initialize_database()

    def _initialize_database(self) -> None:
        with self._engine.begin() as connection:
            connection.execute(text(CREATE_PADDLE_OCR_CONFIGS_SQL))
            connection.execute(
                text(
                    """
                    INSERT INTO paddle_ocr_configs (provider, api_key, model_name)
                    SELECT :provider, '', :model_name
                    WHERE NOT EXISTS (
                        SELECT 1 FROM paddle_ocr_configs WHERE provider = :provider
                    )
                    """
                ),
                {
                    "provider": PADDLE_OCR_PROVIDER,
                    "model_name": PADDLE_OCR_MODEL,
                },
            )

    def get_config(self) -> PaddleOcrConfig:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id, provider, api_key, model_name, created_at, updated_at
                    FROM paddle_ocr_configs
                    WHERE provider = :provider
                    LIMIT 1
                    """
                ),
                {"provider": PADDLE_OCR_PROVIDER},
            ).mappings().fetchone()

        if row is None:
            self._initialize_database()
            return self.get_config()

        return _row_to_config(row)

    def update_config(self, api_key: str | None) -> PaddleOcrConfig:
        if api_key is not None and len(api_key) > 1024:
            raise ValueError("百度 PaddleOCR API Key 不能超过 1024 个字符")

        with self._engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id, api_key
                    FROM paddle_ocr_configs
                    WHERE provider = :provider
                    LIMIT 1
                    """
                ),
                {"provider": PADDLE_OCR_PROVIDER},
            ).mappings().fetchone()

            next_api_key = api_key.strip() if api_key is not None else ""
            if row is not None and api_key is None:
                next_api_key = str(row["api_key"] or "")

            if row is None:
                connection.execute(
                    text(
                        """
                        INSERT INTO paddle_ocr_configs (provider, api_key, model_name)
                        VALUES (:provider, :api_key, :model_name)
                        """
                    ),
                    {
                        "provider": PADDLE_OCR_PROVIDER,
                        "api_key": next_api_key,
                        "model_name": PADDLE_OCR_MODEL,
                    },
                )
            else:
                connection.execute(
                    text(
                        """
                        UPDATE paddle_ocr_configs
                        SET api_key = :api_key, model_name = :model_name
                        WHERE provider = :provider
                        """
                    ),
                    {
                        "provider": PADDLE_OCR_PROVIDER,
                        "api_key": next_api_key,
                        "model_name": PADDLE_OCR_MODEL,
                    },
                )

        return self.get_config()


class PaddleOcrClient:
    def __init__(
        self,
        api_key: str,
        model_name: str = PADDLE_OCR_MODEL,
        poll_interval_seconds: float = 5.0,
        max_wait_seconds: float = 1800.0,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.model_name = model_name
        self.poll_interval_seconds = poll_interval_seconds
        self.max_wait_seconds = max_wait_seconds
        self.session = session or requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept-Encoding": "gzip, deflate, br",
        }

    @staticmethod
    def _response_payload(response: requests.Response, action: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"PaddleOCR {action}返回了无效 JSON") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"PaddleOCR {action}返回格式不正确")

        code = payload.get("code")
        if not response.ok or code not in (None, 0):
            message = str(payload.get("msg") or payload.get("message") or response.reason)
            data = payload.get("data")
            if isinstance(data, dict) and data.get("errorMsg"):
                message = str(data["errorMsg"])
            raise RuntimeError(f"PaddleOCR {action}失败（{code or response.status_code}）：{message}")

        return payload

    @staticmethod
    def parse_jsonl_pages(jsonl_text: str) -> list[str]:
        pages: list[str] = []
        for line_number, raw_line in enumerate(jsonl_text.splitlines(), 1):
            line = raw_line.strip()
            if not line:
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"PaddleOCR JSONL 第 {line_number} 行格式错误") from exc

            result = payload.get("result") if isinstance(payload, dict) else None
            layout_results = result.get("layoutParsingResults") if isinstance(result, dict) else None
            if not isinstance(layout_results, list):
                continue

            for page_result in layout_results:
                markdown = page_result.get("markdown") if isinstance(page_result, dict) else None
                text_value = markdown.get("text") if isinstance(markdown, dict) else None
                pages.append(str(text_value or "").strip())

        if not pages:
            raise RuntimeError("PaddleOCR 结果中没有 layoutParsingResults 页面数据")

        return pages

    def extract_pages(self, path: Path) -> tuple[str, list[str]]:
        if not self.api_key:
            raise ValueError("请先在 Admin 管理中心配置百度 PaddleOCR API Key（AI Studio Access Token）")
        if path.stat().st_size > PADDLE_OCR_LOCAL_FILE_LIMIT:
            raise ValueError("PaddleOCR 本地文件上传不能超过 50 MB")

        optional_payload = {
            "useDocOrientationClassify": True,
            "useDocUnwarping": True,
            "useChartRecognition": True,
            "showFormulaNumber": True,
            "prettifyMarkdown": True,
            "visualize": False,
        }
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        try:
            with path.open("rb") as source_file:
                response = self.session.post(
                    PADDLE_OCR_JOB_URL,
                    headers=self.headers,
                    data={
                        "model": self.model_name,
                        "optionalPayload": json.dumps(optional_payload, ensure_ascii=False),
                    },
                    files={"file": (path.name, source_file, mime_type)},
                    timeout=(15, 120),
                )
            payload = self._response_payload(response, "任务提交")
            data = payload.get("data")
            job_id = str(data.get("jobId") or "") if isinstance(data, dict) else ""
            if not job_id:
                raise RuntimeError("PaddleOCR 任务提交成功但未返回 jobId")

            deadline = time.monotonic() + self.max_wait_seconds
            while time.monotonic() < deadline:
                result_response = self.session.get(
                    f"{PADDLE_OCR_JOB_URL}/{job_id}",
                    headers=self.headers,
                    timeout=(15, 120),
                )
                result_payload = self._response_payload(result_response, "任务查询")
                result_data = result_payload.get("data")
                if not isinstance(result_data, dict):
                    raise RuntimeError("PaddleOCR 任务查询未返回 data")

                state = str(result_data.get("state") or "")
                if state == "failed":
                    raise RuntimeError(
                        f"PaddleOCR 识别失败：{result_data.get('errorMsg') or '未知错误'}"
                    )
                if state == "done":
                    result_url = result_data.get("resultUrl")
                    json_url = (
                        str(result_url.get("jsonUrl") or "")
                        if isinstance(result_url, dict)
                        else ""
                    )
                    if not json_url:
                        raise RuntimeError("PaddleOCR 任务完成但未返回 jsonUrl")

                    jsonl_response = self.session.get(json_url, timeout=(15, 120))
                    jsonl_response.raise_for_status()
                    return job_id, self.parse_jsonl_pages(jsonl_response.text)

                if state not in {"pending", "running"}:
                    raise RuntimeError(f"PaddleOCR 返回了未知任务状态：{state or '空'}")

                time.sleep(self.poll_interval_seconds)
        except requests.RequestException as exc:
            raise RuntimeError(f"PaddleOCR 网络请求失败：{exc}") from exc

        raise TimeoutError(f"PaddleOCR 任务等待超过 {int(self.max_wait_seconds)} 秒")


@lru_cache(maxsize=1)
def get_paddle_ocr_config_service() -> PaddleOcrConfigService:
    return PaddleOcrConfigService()
