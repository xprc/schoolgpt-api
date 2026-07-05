import os
import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any


STRUCTURED_CONTENT_VERSION = 1

OCR_BLOCK_TYPE_BY_LABEL = {
    "doc_title": "heading",
    "paragraph_title": "heading",
    "title": "heading",
    "text": "paragraph",
    "table": "table",
    "formula": "formula",
    "algorithm": "code",
}


def _clean_text(value: object) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _clean_cell(value: object) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


def _normalize_table_rows(rows: Iterable[Iterable[object]]) -> list[list[str]]:
    cleaned_rows = [[_clean_cell(cell) for cell in row] for row in rows]
    cleaned_rows = [row for row in cleaned_rows if any(row)]
    if not cleaned_rows:
        return []

    max_columns = max(len(row) for row in cleaned_rows)
    padded_rows = [row + [""] * (max_columns - len(row)) for row in cleaned_rows]
    keep_columns = [
        column_index
        for column_index in range(max_columns)
        if any(row[column_index] for row in padded_rows)
    ]
    if not keep_columns:
        return []

    return [[row[column_index] for column_index in keep_columns] for row in padded_rows]


def _table_to_text(rows: Iterable[Iterable[object]]) -> str:
    lines = []
    for row in _normalize_table_rows(rows):
        cells = [cell for cell in row if cell]
        if cells:
            lines.append(" | ".join(cells))

    return "\n".join(lines).strip()


def _make_block(
    page_number: int,
    block_index: int,
    block_type: str,
    text_value: str,
    bbox: list[float] | None = None,
) -> dict[str, Any] | None:
    normalized_text = _clean_text(text_value)
    if not normalized_text:
        return None

    return {
        "id": f"p{page_number}-b{block_index}",
        "type": block_type,
        "text": normalized_text,
        "page_number": max(1, int(page_number)),
        "bbox": bbox,
    }


def _new_structured_content(
    original_name: str,
    extension: str,
    sha256: str,
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "version": STRUCTURED_CONTENT_VERSION,
        "file": {
            "name": original_name,
            "extension": extension.lstrip("."),
            "sha256": sha256,
        },
        "pages": pages,
    }


def _normalize_ocr_block_type(block_label: object) -> str:
    normalized_label = str(block_label or "").strip().lower()
    return OCR_BLOCK_TYPE_BY_LABEL.get(normalized_label, normalized_label or "paragraph")


def _to_plain_json_value(value: object) -> object:
    if hasattr(value, "tolist"):
        return value.tolist()

    if isinstance(value, dict):
        return {
            str(key): _to_plain_json_value(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [_to_plain_json_value(item) for item in value]

    return value


def _number_sequence(value: object) -> list[float]:
    normalized = _to_plain_json_value(value)
    if not isinstance(normalized, list):
        return []

    numbers = []
    for item in normalized:
        if isinstance(item, (list, tuple)):
            numbers.extend(_number_sequence(item))
            continue

        try:
            numbers.append(float(item))
        except (TypeError, ValueError):
            continue

    return numbers


def _normalize_ocr_bbox(value: object) -> list[float] | None:
    normalized = _to_plain_json_value(value)
    if not isinstance(normalized, list):
        return None

    if (
        len(normalized) == 4
        and all(isinstance(item, (int, float)) for item in normalized)
    ):
        return [float(item) for item in normalized]

    if normalized and all(isinstance(item, list) for item in normalized):
        points = []
        for item in normalized:
            if len(item) < 2:
                continue
            try:
                points.append((float(item[0]), float(item[1])))
            except (TypeError, ValueError):
                continue

        if points:
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            return [min(xs), min(ys), max(xs), max(ys)]

    numbers = _number_sequence(normalized)
    if len(numbers) >= 4:
        xs = numbers[0::2]
        ys = numbers[1::2]
        if xs and ys:
            return [min(xs), min(ys), max(xs), max(ys)]

    return None


def _html_table_to_text(html_value: object) -> str:
    html_text = str(html_value or "").strip()
    if not html_text:
        return ""

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return re.sub(r"<[^>]+>", " ", html_text)

    soup = BeautifulSoup(html_text, "html.parser")
    rows = []
    for row in soup.find_all("tr"):
        cells = [
            cell.get_text(" ", strip=True)
            for cell in row.find_all(["th", "td"])
        ]
        if any(cells):
            rows.append(cells)

    return _table_to_text(rows)


def _ocr_result_payload(result: object) -> dict[str, Any]:
    payload = getattr(result, "json", None)
    if callable(payload):
        payload = payload()

    payload = _to_plain_json_value(payload)
    if not isinstance(payload, dict):
        return {}

    nested_payload = payload.get("res")
    if isinstance(nested_payload, dict):
        return nested_payload

    return payload


def _ocr_page_number(payload: Mapping[str, Any], fallback_page_number: int) -> int:
    page_index = payload.get("page_index")
    try:
        normalized_page_index = int(page_index)
        if normalized_page_index >= 0:
            return normalized_page_index + 1
    except (TypeError, ValueError):
        pass

    return max(1, fallback_page_number)


def _ocr_blocks_from_payload(
    payload: Mapping[str, Any],
    page_number: int,
) -> list[dict[str, Any]]:
    blocks = []
    parsing_results = payload.get("parsing_res_list")
    if isinstance(parsing_results, list):
        for item in parsing_results:
            if not isinstance(item, dict):
                continue

            block = _make_block(
                page_number,
                len(blocks) + 1,
                _normalize_ocr_block_type(item.get("block_label")),
                str(item.get("block_content") or ""),
                bbox=_normalize_ocr_bbox(item.get("block_bbox")),
            )
            if block:
                blocks.append(block)

    has_table_block = any(block.get("type") == "table" for block in blocks)
    table_results = payload.get("table_res_list")
    if not has_table_block and isinstance(table_results, list):
        for item in table_results:
            if not isinstance(item, dict):
                continue

            block = _make_block(
                page_number,
                len(blocks) + 1,
                "table",
                _html_table_to_text(item.get("pred_html")),
                bbox=_normalize_ocr_bbox(item.get("cell_box_list")),
            )
            if block:
                blocks.append(block)

    has_formula_block = any(block.get("type") == "formula" for block in blocks)
    formula_results = payload.get("formula_res_list")
    if not has_formula_block and isinstance(formula_results, list):
        for item in formula_results:
            if not isinstance(item, dict):
                continue

            block = _make_block(
                page_number,
                len(blocks) + 1,
                "formula",
                str(item.get("rec_formula") or ""),
                bbox=_normalize_ocr_bbox(item.get("rec_polys")),
            )
            if block:
                blocks.append(block)

    if blocks:
        return blocks

    overall_ocr = payload.get("overall_ocr_res")
    if not isinstance(overall_ocr, dict):
        return []

    rec_texts = [
        str(text_value).strip()
        for text_value in overall_ocr.get("rec_texts", []) or []
        if str(text_value or "").strip()
    ]
    fallback_text = "\n".join(rec_texts)
    block = _make_block(page_number, 1, "page_text", fallback_text)
    return [block] if block else []


@lru_cache(maxsize=1)
def _get_pp_structure_v3_pipeline() -> Any:
    try:
        from paddleocr import PPStructureV3
    except ImportError as exc:
        raise ValueError(
            "OCR 解析需要安装 paddleocr[doc-parser]、PaddlePaddle 推理引擎及其模型依赖"
        ) from exc

    device = (
        os.environ.get("SCHOOLGPT_RAG_OCR_DEVICE")
        or os.environ.get("PADDLEOCR_DEVICE")
        or ""
    ).strip()
    pipeline_options: dict[str, Any] = {
        "use_table_recognition": True,
        "use_formula_recognition": True,
        "format_block_content": True,
    }
    if device:
        pipeline_options["device"] = device

    return PPStructureV3(**pipeline_options)


def extract_ocr_structured_content(
    path: Path,
    original_name: str,
    extension: str,
    sha256: str,
) -> dict[str, Any]:
    pipeline = _get_pp_structure_v3_pipeline()
    pages = []

    for fallback_page_number, result in enumerate(
        pipeline.predict(input=str(path)),
        1,
    ):
        payload = _ocr_result_payload(result)
        page_number = _ocr_page_number(payload, fallback_page_number)
        pages.append(
            {
                "page_number": page_number,
                "blocks": _ocr_blocks_from_payload(payload, page_number),
            }
        )

    if not pages:
        pages.append({"page_number": 1, "blocks": []})

    pages.sort(key=lambda page: int(page.get("page_number") or 1))
    return _new_structured_content(original_name, extension, sha256, pages)
