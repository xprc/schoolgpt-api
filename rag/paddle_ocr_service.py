import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import text

from db.core import get_database_engine
from db.defaults import (
    PADDLE_OCR_JOB_URL,
    PADDLE_OCR_MODEL,
    PADDLE_OCR_PROVIDER,
    PADDLE_OCR_PROVIDER_LABEL,
)
from db.schema import initialize_paddle_ocr_configs_schema

PADDLE_OCR_LOCAL_FILE_LIMIT = 50 * 1024 * 1024
PADDLE_OCR_UPLOAD_TIMEOUT_SECONDS = 300
PADDLE_OCR_REQUEST_TIMEOUT_SECONDS = 120
PADDLE_OCR_DOWNLOAD_MAX_ATTEMPTS = 4
PADDLE_OCR_DOWNLOAD_RETRY_DELAY_SECONDS = 2.0


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
        self._engine = get_database_engine()
        initialize_paddle_ocr_configs_schema(self._engine)

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
            initialize_paddle_ocr_configs_schema(self._engine)
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
        session: Any | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.model_name = model_name
        self.poll_interval_seconds = poll_interval_seconds
        self.max_wait_seconds = max_wait_seconds
        if session is None:
            self._urlopen = urllib.request.urlopen
        elif callable(session):
            self._urlopen = session
        elif hasattr(session, "urlopen"):
            self._urlopen = session.urlopen
        else:
            raise TypeError("session must be urlopen-compatible")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    def _open_text(
        self,
        request: urllib.request.Request,
        action: str,
        timeout: int,
    ) -> str:
        try:
            with self._urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"PaddleOCR {action}失败（HTTP {exc.code}）：{text}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"PaddleOCR {action}网络请求失败：{exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError(f"PaddleOCR {action}网络请求超时：{exc}") from exc
        except OSError as exc:
            raise RuntimeError(f"PaddleOCR {action}网络请求失败：{exc}") from exc

    def _send_json_request(
        self,
        request: urllib.request.Request,
        action: str,
        timeout: int,
    ) -> dict[str, Any]:
        text_value = self._open_text(request, action, timeout)
        try:
            payload = json.loads(text_value)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"PaddleOCR {action}返回了无效 JSON") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"PaddleOCR {action}返回格式不正确")

        code = payload.get("code")
        if code not in (None, 0):
            message = str(payload.get("msg") or payload.get("message") or "未知错误")
            data = payload.get("data")
            if isinstance(data, dict) and data.get("errorMsg"):
                message = str(data["errorMsg"])
            raise RuntimeError(f"PaddleOCR {action}失败（{code}）：{message}")

        return payload

    def _get_json(self, url: str, action: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers=self.headers, method="GET")
        return self._send_json_request(
            request,
            action,
            PADDLE_OCR_REQUEST_TIMEOUT_SECONDS,
        )

    def _download_text(self, url: str, action: str) -> str:
        last_error: BaseException | None = None
        for attempt in range(1, PADDLE_OCR_DOWNLOAD_MAX_ATTEMPTS + 1):
            request = urllib.request.Request(url, method="GET")
            try:
                with self._urlopen(
                    request,
                    timeout=PADDLE_OCR_REQUEST_TIMEOUT_SECONDS,
                ) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"PaddleOCR {action}失败（HTTP {exc.code}）：{text}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt >= PADDLE_OCR_DOWNLOAD_MAX_ATTEMPTS:
                    break
                time.sleep(PADDLE_OCR_DOWNLOAD_RETRY_DELAY_SECONDS * attempt)

        raise RuntimeError(f"PaddleOCR {action}网络请求失败：{last_error}")

    def _post_multipart(
        self,
        url: str,
        fields: Mapping[str, object],
        file_field_name: str,
        file_path: Path,
    ) -> dict[str, Any]:
        boundary = "----PythonOCRDemo" + uuid.uuid4().hex
        body = bytearray()

        for name, value in fields.items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(str(value).encode("utf-8"))
            body.extend(b"\r\n")

        filename = file_path.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        file_bytes = file_path.read_bytes()

        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="{file_field_name}"; '
                f'filename="{filename}"\r\n'
            ).encode()
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
        body.extend(file_bytes)
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        request = urllib.request.Request(
            url,
            data=bytes(body),
            method="POST",
            headers={
                **self.headers,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        return self._send_json_request(
            request,
            "任务提交",
            PADDLE_OCR_UPLOAD_TIMEOUT_SECONDS,
        )

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
            "prettifyMarkdown": True,
            "showFormulaNumber": True,
            "visualize": False,
        }

        payload = self._post_multipart(
            PADDLE_OCR_JOB_URL,
            fields={
                "model": self.model_name,
                "optionalPayload": json.dumps(optional_payload, ensure_ascii=False),
            },
            file_field_name="file",
            file_path=path,
        )
        data = payload.get("data")
        job_id = str(data.get("jobId") or "") if isinstance(data, dict) else ""
        if not job_id:
            raise RuntimeError("PaddleOCR 任务提交成功但未返回 jobId")

        deadline = time.monotonic() + self.max_wait_seconds
        while time.monotonic() < deadline:
            quoted_job_id = urllib.parse.quote(job_id, safe="")
            result_payload = self._get_json(
                f"{PADDLE_OCR_JOB_URL}/{quoted_job_id}",
                "任务查询",
            )
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
                markdown_url = (
                    str(result_url.get("markdownUrl") or "")
                    if isinstance(result_url, dict)
                    else ""
                )
                if not json_url and not markdown_url:
                    raise RuntimeError("PaddleOCR 任务完成但未返回 resultUrl")

                download_errors: list[str] = []
                if json_url:
                    try:
                        jsonl_text = self._download_text(json_url, "JSONL 结果下载")
                        return job_id, self.parse_jsonl_pages(jsonl_text)
                    except RuntimeError as exc:
                        download_errors.append(str(exc))

                if markdown_url:
                    try:
                        markdown_text = self._download_text(markdown_url, "Markdown 结果下载")
                    except RuntimeError as exc:
                        download_errors.append(str(exc))
                    else:
                        normalized_markdown = markdown_text.strip()
                        if normalized_markdown:
                            return job_id, [normalized_markdown]
                        download_errors.append("PaddleOCR Markdown 结果为空")

                raise RuntimeError("；".join(download_errors))

            if state not in {"pending", "running"}:
                raise RuntimeError(f"PaddleOCR 返回了未知任务状态：{state or '空'}")

            time.sleep(self.poll_interval_seconds)

        raise TimeoutError(f"PaddleOCR 任务等待超过 {int(self.max_wait_seconds)} 秒")


@lru_cache(maxsize=1)
def get_paddle_ocr_config_service() -> PaddleOcrConfigService:
    return PaddleOcrConfigService()
