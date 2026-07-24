from __future__ import annotations

import json
import random
import time
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rural_basic_income.config import Settings, get_settings
from rural_basic_income.worker.download import PayloadChunk, SourcePeriodDownload

KOSIS_STATISTICS_PARAMETER_URL = (
    "https://kosis.kr/openapi/Param/statisticsParameterData.do"
)
RETRYABLE_HTTP_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
RETRYABLE_MESSAGE_MARKERS = (
    "too many",
    "rate limit",
    "ratelimit",
    "quota",
    "exceeded",
    "timeout",
    "timed out",
    "temporarily",
    "try again",
    "잠시",
    "초과",
)

KosisPayloadChunks = list[tuple[dict[str, str], list[dict[str, Any]]]]


@dataclass(frozen=True)
class KosisRawSpec:
    source_name: str
    source_name_kor: str
    source_org_id: str
    source_table_id: str
    raw_table: str


HOUSEHOLD_SPEC = KosisRawSpec(
    source_name="household",
    source_name_kor="행정구역(시군구)별 주민등록세대수",
    source_org_id="101",
    source_table_id="DT_1B040B3",
    raw_table="household",
)
POPULATION_SPEC = KosisRawSpec(
    source_name="population",
    source_name_kor="행정구역(시군구)별/1세별 주민등록인구",
    source_org_id="101",
    source_table_id="DT_1B04006",
    raw_table="population",
)
MOVER_SPEC = KosisRawSpec(
    source_name="mover",
    source_name_kor="시군구/성/연령(5세)별 이동자수",
    source_org_id="101",
    source_table_id="DT_1B26001",
    raw_table="mover",
)


class KosisApiKeyMissing(RuntimeError):
    """Raised when a KOSIS API request is attempted without an API key."""


class KosisApiError(RuntimeError):
    """Raised when KOSIS returns an unusable response."""


class KosisDownloadError(RuntimeError):
    """Raised when KOSIS data cannot be downloaded into an in-memory batch."""


def make_chunks(values: list[str] | tuple[str, ...], chunk_size: int) -> list[list[str]]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")

    return [
        list(values[start : start + chunk_size])
        for start in range(0, len(values), chunk_size)
    ]


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def base_params(spec: KosisRawSpec, period: str) -> dict[str, str]:
    return {
        "orgId": spec.source_org_id,
        "tblId": spec.source_table_id,
        "prdSe": "M",
        "startPrdDe": period,
        "endPrdDe": period,
        "itmId": "ALL",
    }


def build_statistics_parameter_url(
    params: Mapping[str, str],
    *,
    api_key: str | None = None,
    settings: Settings | None = None,
    base_url: str = KOSIS_STATISTICS_PARAMETER_URL,
) -> str:
    resolved_api_key = api_key or (settings or get_settings()).kosis_api_key
    if not resolved_api_key:
        raise KosisApiKeyMissing("KOSIS_API_KEY is required")

    query = {
        "method": "getList",
        "apiKey": resolved_api_key,
        "format": "json",
        "jsonVD": "Y",
        **params,
    }
    return f"{base_url}?{urlencode(query)}"


def is_retryable_message(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in RETRYABLE_MESSAGE_MARKERS)


def retry_sleep_seconds(
    attempt_index: int,
    *,
    base_sleep_seconds: float,
    max_sleep_seconds: float,
) -> float:
    exponential_sleep = base_sleep_seconds * (2 ** attempt_index)
    jitter = random.uniform(0, base_sleep_seconds)
    return min(exponential_sleep + jitter, max_sleep_seconds)


def sleep_before_retry(
    attempt_index: int,
    *,
    base_sleep_seconds: float,
    max_sleep_seconds: float,
) -> None:
    time.sleep(
        retry_sleep_seconds(
            attempt_index,
            base_sleep_seconds=base_sleep_seconds,
            max_sleep_seconds=max_sleep_seconds,
        )
    )


def read_http_error_body(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return ""


def fetch_statistics_parameter_data(
    params: Mapping[str, str],
    *,
    api_key: str | None = None,
    timeout: float = 30,
    max_retries: int = 5,
    base_retry_sleep_seconds: float = 1,
    max_retry_sleep_seconds: float = 60,
) -> list[dict[str, Any]]:
    url = build_statistics_parameter_url(params, api_key=api_key)
    request = Request(
        url,
        headers={"User-Agent": "rural-basic-income/0.2.0"},
    )

    for attempt_index in range(max_retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                response_text = response.read().decode("utf-8-sig", errors="replace")
        except HTTPError as exc:
            response_text = read_http_error_body(exc)
            should_retry = (
                exc.code in RETRYABLE_HTTP_STATUS_CODES
                or is_retryable_message(response_text)
            )
            if should_retry and attempt_index < max_retries:
                sleep_before_retry(
                    attempt_index,
                    base_sleep_seconds=base_retry_sleep_seconds,
                    max_sleep_seconds=max_retry_sleep_seconds,
                )
                continue
            message = f"KOSIS request failed with HTTP {exc.code}"
            if response_text:
                message = f"{message}: {response_text[:300]}"
            raise KosisApiError(message) from exc
        except (TimeoutError, URLError) as exc:
            if attempt_index < max_retries:
                sleep_before_retry(
                    attempt_index,
                    base_sleep_seconds=base_retry_sleep_seconds,
                    max_sleep_seconds=max_retry_sleep_seconds,
                )
                continue
            raise KosisApiError("KOSIS request failed") from exc

        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            if is_retryable_message(response_text) and attempt_index < max_retries:
                sleep_before_retry(
                    attempt_index,
                    base_sleep_seconds=base_retry_sleep_seconds,
                    max_sleep_seconds=max_retry_sleep_seconds,
                )
                continue
            raise KosisApiError("KOSIS response was not valid JSON") from exc

        if isinstance(payload, list):
            return payload

        payload_text = json.dumps(payload, ensure_ascii=False)
        if is_retryable_message(payload_text) and attempt_index < max_retries:
            sleep_before_retry(
                attempt_index,
                base_sleep_seconds=base_retry_sleep_seconds,
                max_sleep_seconds=max_retry_sleep_seconds,
            )
            continue

        raise KosisApiError("KOSIS response JSON was not a list")

    raise KosisApiError("KOSIS request failed after retry attempts")


def get_dimension_specs(rows: list[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
    if not rows:
        return []

    first_row = rows[0]
    dimensions = []
    for index in range(1, 9):
        obj_key = f"C{index}_OBJ_NM"
        code_key = f"C{index}"
        name_key = f"C{index}_NM"
        obj_name = first_row.get(obj_key)
        if not obj_name or code_key not in first_row or name_key not in first_row:
            continue
        dimensions.append((code_key, name_key, str(obj_name)))

    return dimensions


def get_item_column_name(row: Mapping[str, Any]) -> str:
    item_name = str(row.get("ITM_NM") or "값")
    unit_name = row.get("UNIT_NM")
    if unit_name:
        return f"{item_name} ({unit_name})"
    return item_name


def kosis_rows_to_raw_rows(
    rows: list[Mapping[str, Any]],
) -> tuple[list[str], list[dict[str, str]]]:
    if not rows:
        return ["시점"], []

    dimension_specs = get_dimension_specs(rows)
    base_columns = ["시점"]
    for code_key, _name_key, obj_name in dimension_specs:
        base_columns.extend([f"C{obj_name}", obj_name])

    item_columns: OrderedDict[str, None] = OrderedDict()
    grouped_rows: OrderedDict[tuple[str, ...], dict[str, str]] = OrderedDict()

    for row in rows:
        item_column = get_item_column_name(row)
        item_columns.setdefault(item_column, None)

        output_row: dict[str, str] = {"시점": str(row.get("PRD_DE") or "")}
        key_parts = [output_row["시점"]]
        for code_key, name_key, obj_name in dimension_specs:
            code_column = f"C{obj_name}"
            name_column = obj_name
            output_row[code_column] = str(row.get(code_key) or "")
            output_row[name_column] = str(row.get(name_key) or "")
            key_parts.extend([output_row[code_column], output_row[name_column]])

        key = tuple(key_parts)
        if key not in grouped_rows:
            grouped_rows[key] = output_row
        grouped_rows[key][item_column] = str(row.get("DT") or "")

    columns = base_columns + list(item_columns.keys()) + ["downloaded_at"]
    downloaded_at = datetime.now(UTC).isoformat()
    output_rows = []
    for row in grouped_rows.values():
        complete_row = {column: row.get(column, "") for column in columns}
        complete_row["downloaded_at"] = downloaded_at
        output_rows.append(complete_row)

    return columns, output_rows


def fetch_rows(
    params: Mapping[str, str],
    *,
    request_sleep_seconds: float,
    timeout: float,
    max_retries: int,
) -> list[dict[str, Any]]:
    try:
        rows = fetch_statistics_parameter_data(
            params,
            timeout=timeout,
            max_retries=max_retries,
        )
    except Exception as exc:
        table_id = params.get("tblId", "unknown")
        period = params.get("startPrdDe", "unknown")
        obj_l1 = params.get("objL1")
        if obj_l1 and obj_l1 != "ALL":
            obj_l1_summary = f"{len(obj_l1.split('+'))} region code(s)"
        else:
            obj_l1_summary = obj_l1 or "not set"
        raise KosisDownloadError(
            "KOSIS fetch failed "
            f"(tblId={table_id}, period={period}, objL1={obj_l1_summary})"
        ) from exc

    if request_sleep_seconds > 0:
        time.sleep(request_sleep_seconds)
    return rows


def make_payload_chunk(
    params: Mapping[str, str],
    payload: Iterable[Mapping[str, Any]],
) -> PayloadChunk:
    return PayloadChunk(
        request_params=dict(params),
        response_payload=tuple(dict(row) for row in payload),
    )


def make_source_period_download(
    spec: KosisRawSpec,
    period: str,
    chunks: Iterable[tuple[Mapping[str, str], Iterable[Mapping[str, Any]]]],
) -> SourcePeriodDownload:
    payload_chunks = tuple(
        make_payload_chunk(params, payload)
        for params, payload in chunks
    )
    long_rows = [
        row
        for chunk in payload_chunks
        for row in chunk.response_payload
    ]
    raw_columns, raw_rows = kosis_rows_to_raw_rows(long_rows)

    return SourcePeriodDownload(
        source_name=spec.source_name,
        source_name_kor=spec.source_name_kor,
        source_org_id=spec.source_org_id,
        source_table_id=spec.source_table_id,
        raw_table=spec.raw_table,
        period=period,
        payload_chunks=payload_chunks,
        raw_columns=tuple(raw_columns),
        raw_rows=tuple(dict(row) for row in raw_rows),
    )
