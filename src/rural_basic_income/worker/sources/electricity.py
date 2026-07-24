from __future__ import annotations

import json
import random
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rural_basic_income.config import Settings, get_settings
from rural_basic_income.pipeline.kosis_raw import validate_period
from rural_basic_income.worker.download import (
    PayloadChunk,
    SourcePeriodDownload,
)

# Source: KEPCO Bigdata 계약종별 전력사용량.
SOURCE_NAME = "electricity"
SOURCE_NAME_KOR = "계약종별 전력사용량"
SOURCE_ORG_ID = "KEPCO"
SOURCE_TABLE_ID = "powerUsage/contractType.do"
RAW_TABLE = "electricity"
POWER_USAGE_CONTRACT_TYPE_URL = (
    "https://bigdata.kepco.co.kr/openapi/v1/powerUsage/contractType.do"
)
COMMON_CODE_URL = "https://bigdata.kepco.co.kr/openapi/v1/commonCode.do"
RETRYABLE_HTTP_STATUS_CODES = {401, 408, 409, 425, 429, 500, 502, 503, 504}
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
)
RAW_COLUMNS = (
    "year",
    "month",
    "metro",
    "city",
    "cntr",
    "custCnt",
    "powerUsage",
    "bill",
    "unitCost",
    "cntrPwr",
    "downloaded_at",
)


class KepcoApiKeyMissing(RuntimeError):
    """Raised when a KEPCO API request is attempted without an API key."""


class KepcoApiError(RuntimeError):
    """Raised when KEPCO returns an unusable response."""


def build_kepco_url(
    base_url: str,
    params: Mapping[str, str],
    *,
    api_key: str | None = None,
    settings: Settings | None = None,
) -> str:
    resolved_api_key = api_key or (settings or get_settings()).kepco_api_key
    if not resolved_api_key:
        raise KepcoApiKeyMissing("KEPCO_API_KEY is required")

    query = {
        **params,
        "apiKey": resolved_api_key,
        "returnType": "json",
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


def read_http_error_body(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return ""


def parse_concatenated_json_documents(
    response_text: str,
) -> tuple[dict[str, Any], ...]:
    decoder = json.JSONDecoder()
    documents: list[dict[str, Any]] = []
    index = 0

    while index < len(response_text):
        while index < len(response_text) and response_text[index].isspace():
            index += 1
        if index >= len(response_text):
            break

        document, end_index = decoder.raw_decode(response_text, index)
        if not isinstance(document, dict):
            raise KepcoApiError("KEPCO response JSON document was not an object")

        documents.append(document)
        index = end_index

    if not documents:
        raise KepcoApiError("KEPCO response did not contain a JSON document")

    return tuple(documents)


def documents_contain_rows(documents: tuple[Mapping[str, Any], ...]) -> bool:
    for document in documents:
        data_rows = document.get("data") or []
        total_rows = document.get("totData") or []
        if data_rows or total_rows:
            return True
    return False


def fetch_kepco_documents(
    base_url: str,
    params: Mapping[str, str],
    *,
    timeout: float = 30,
    max_retries: int = 5,
    base_retry_sleep_seconds: float = 1,
    max_retry_sleep_seconds: float = 60,
) -> tuple[dict[str, Any], ...]:
    url = build_kepco_url(base_url, params)
    request = Request(
        url,
        headers={"User-Agent": "rural-basic-income/0.2.0"},
    )

    for attempt_index in range(max_retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                response_text = response.read().decode(
                    "utf-8-sig",
                    errors="replace",
                )
        except HTTPError as exc:
            response_text = read_http_error_body(exc)
            try:
                documents = parse_concatenated_json_documents(response_text)
            except (json.JSONDecodeError, KepcoApiError):
                documents = ()
            if documents and documents_contain_rows(documents):
                return documents

            should_retry = (
                exc.code in RETRYABLE_HTTP_STATUS_CODES
                or is_retryable_message(response_text)
            )
            if should_retry and attempt_index < max_retries:
                time.sleep(
                    retry_sleep_seconds(
                        attempt_index,
                        base_sleep_seconds=base_retry_sleep_seconds,
                        max_sleep_seconds=max_retry_sleep_seconds,
                    )
                )
                continue
            message = f"KEPCO request failed with HTTP {exc.code}"
            if response_text:
                message = f"{message}: {response_text[:300]}"
            raise KepcoApiError(message) from exc
        except (TimeoutError, URLError) as exc:
            if attempt_index < max_retries:
                time.sleep(
                    retry_sleep_seconds(
                        attempt_index,
                        base_sleep_seconds=base_retry_sleep_seconds,
                        max_sleep_seconds=max_retry_sleep_seconds,
                    )
                )
                continue
            raise KepcoApiError("KEPCO request failed") from exc

        try:
            documents = parse_concatenated_json_documents(response_text)
        except (json.JSONDecodeError, KepcoApiError) as exc:
            if is_retryable_message(response_text) and attempt_index < max_retries:
                time.sleep(
                    retry_sleep_seconds(
                        attempt_index,
                        base_sleep_seconds=base_retry_sleep_seconds,
                        max_sleep_seconds=max_retry_sleep_seconds,
                    )
                )
                continue
            raise KepcoApiError("KEPCO response was not valid JSON") from exc

        response_summary = json.dumps(documents, ensure_ascii=False)
        if is_retryable_message(response_summary) and attempt_index < max_retries:
            time.sleep(
                retry_sleep_seconds(
                    attempt_index,
                    base_sleep_seconds=base_retry_sleep_seconds,
                    max_sleep_seconds=max_retry_sleep_seconds,
                )
            )
            continue

        return documents

    raise KepcoApiError("KEPCO request failed after retry attempts")


def extract_data_rows(
    documents: tuple[Mapping[str, Any], ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for document in documents:
        data_rows = document.get("data") or []
        if not isinstance(data_rows, list):
            raise KepcoApiError("KEPCO data field was not a list")
        rows.extend(dict(row) for row in data_rows)
    return rows


def rows_to_raw_rows(
    rows: list[Mapping[str, Any]],
    *,
    downloaded_at: str | None = None,
) -> tuple[dict[str, str], ...]:
    resolved_downloaded_at = downloaded_at or datetime.now(UTC).isoformat()
    raw_rows = []
    for row in rows:
        raw_row = {
            column: "" if row.get(column) is None else str(row.get(column))
            for column in RAW_COLUMNS
            if column != "downloaded_at"
        }
        raw_row["downloaded_at"] = resolved_downloaded_at
        raw_rows.append(raw_row)
    return tuple(raw_rows)


def fetch_contract_type_codes(
    *,
    timeout: float = 30,
    max_retries: int = 5,
) -> tuple[dict[str, Any], ...]:
    documents = fetch_kepco_documents(
        COMMON_CODE_URL,
        {"codeTy": "cntrCd"},
        timeout=timeout,
        max_retries=max_retries,
    )
    return tuple(extract_data_rows(documents))


def fetch_electricity_payload(
    period: str,
    *,
    contract_code: str | None = None,
    timeout: float = 30,
    max_retries: int = 5,
) -> tuple[dict[str, str], tuple[dict[str, Any], ...]]:
    validated_period = validate_period(period)
    params = {
        "year": validated_period[:4],
        "month": validated_period[4:6],
    }
    if contract_code:
        params["cntrCd"] = contract_code

    documents = fetch_kepco_documents(
        POWER_USAGE_CONTRACT_TYPE_URL,
        params,
        timeout=timeout,
        max_retries=max_retries,
    )
    return params, documents


def download_electricity(
    period: str,
    *,
    contract_code: str | None = None,
    timeout: float = 30,
    max_retries: int = 5,
) -> SourcePeriodDownload:
    validated_period = validate_period(period)
    request_params, documents = fetch_electricity_payload(
        validated_period,
        contract_code=contract_code,
        timeout=timeout,
        max_retries=max_retries,
    )
    data_rows = extract_data_rows(documents)
    raw_rows = rows_to_raw_rows(data_rows)
    payload_chunk = PayloadChunk(
        request_params=request_params,
        response_payload=documents,
    )

    return SourcePeriodDownload(
        source_name=SOURCE_NAME,
        source_name_kor=SOURCE_NAME_KOR,
        source_org_id=SOURCE_ORG_ID,
        source_table_id=SOURCE_TABLE_ID,
        raw_table=RAW_TABLE,
        period=validated_period,
        payload_chunks=(payload_chunk,),
        raw_columns=RAW_COLUMNS,
        raw_rows=raw_rows,
    )
