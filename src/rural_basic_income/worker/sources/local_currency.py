from __future__ import annotations

import json
import math
import random
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, unquote
from urllib.request import Request, urlopen

from rural_basic_income.config import Settings, get_settings
from rural_basic_income.worker.download import PayloadChunk, SourcePeriodDownload
from rural_basic_income.worker.periods import validate_period

# Source: data.go.kr 한국조폐공사 지역사랑상품권 결제정보.
SOURCE_NAME = "local_currency"
SOURCE_NAME_KOR = "지역사랑상품권 결제정보"
SOURCE_ORG_ID = "B190001"
SOURCE_TABLE_ID = "localGiftsPaymentV3/paymentsV3"
RAW_TABLE = "local_currency"
LOCAL_CURRENCY_PAYMENTS_URL = (
    "https://apis.data.go.kr/B190001/localGiftsPaymentV3/paymentsV3"
)
DEFAULT_PER_PAGE = 10_000
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
)
RAW_COLUMNS = (
    "crtr_ym",
    "usage_rgn_cd",
    "emd_cd",
    "emd_nm",
    "card_use_amt",
    "mbl_use_amt",
    "mbl_user_cnt",
    "par_ag",
    "par_gend",
    "stlm_amt",
    "stlm_nocs",
    "downloaded_at",
)


class DataGoKrApiKeyMissing(RuntimeError):
    """Raised when a data.go.kr API request is attempted without an API key."""


class DataGoKrApiError(RuntimeError):
    """Raised when data.go.kr returns an unusable response."""


def build_data_go_kr_url(
    base_url: str,
    params: Mapping[str, str],
    *,
    api_key: str | None = None,
    settings: Settings | None = None,
) -> str:
    resolved_api_key = api_key or (settings or get_settings()).data_go_kr_api_key
    if not resolved_api_key:
        raise DataGoKrApiKeyMissing("DATA_GO_KR_API_KEY is required")

    query = {
        "serviceKey": unquote(resolved_api_key),
        **params,
        "returnType": "JSON",
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


def validate_payload(payload: Mapping[str, Any]) -> None:
    response_header = payload.get("response", {}).get("header", {})
    result_code = response_header.get("resultCode")
    if result_code is not None and str(result_code) not in {"0", "00"}:
        result_msg = response_header.get("resultMsg")
        raise DataGoKrApiError(f"API rejected request: {result_code} {result_msg}")

    for code_key in ("resultCode", "code", "errorCode"):
        code_value = payload.get(code_key)
        if code_value is None or str(code_value) in {"0", "00", "200"}:
            continue
        message = (
            payload.get("resultMsg")
            or payload.get("message")
            or payload.get("errorMessage")
            or payload.get("msg")
        )
        raise DataGoKrApiError(f"API rejected request: {code_value} {message}")

    success_keys = {"currentCount", "data", "matchCount", "page", "perPage", "totalCount"}
    if not success_keys.intersection(payload):
        raise DataGoKrApiError(f"Unexpected API payload: {payload}")


def normalize_data_rows(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, list):
        return [dict(row) for row in data]
    if isinstance(data, dict):
        return [dict(data)]
    raise DataGoKrApiError(f"Unexpected data field type: {type(data)}")


def fetch_json_payload(
    base_url: str,
    params: Mapping[str, str],
    *,
    timeout: float = 30,
    max_retries: int = 5,
    base_retry_sleep_seconds: float = 1,
    max_retry_sleep_seconds: float = 60,
) -> dict[str, Any]:
    url = build_data_go_kr_url(base_url, params)
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
            message = f"data.go.kr request failed with HTTP {exc.code}"
            if response_text:
                message = f"{message}: {response_text[:300]}"
            raise DataGoKrApiError(message) from exc
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
            raise DataGoKrApiError("data.go.kr request failed") from exc

        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            if is_retryable_message(response_text) and attempt_index < max_retries:
                time.sleep(
                    retry_sleep_seconds(
                        attempt_index,
                        base_sleep_seconds=base_retry_sleep_seconds,
                        max_sleep_seconds=max_retry_sleep_seconds,
                    )
                )
                continue
            raise DataGoKrApiError("data.go.kr response was not valid JSON") from exc

        if not isinstance(payload, dict):
            raise DataGoKrApiError("data.go.kr response JSON was not an object")

        validate_payload(payload)
        return payload

    raise DataGoKrApiError("data.go.kr request failed after retry attempts")


def make_page_params(
    period: str,
    *,
    page: int,
    per_page: int,
    usage_region_code: str | None = None,
) -> dict[str, str]:
    if page < 1:
        raise ValueError("page must be at least 1")
    if per_page < 1:
        raise ValueError("per_page must be at least 1")

    validated_period = validate_period(period)
    params = {
        "page": str(page),
        "perPage": str(per_page),
        "cond[crtr_ym::GTE]": validated_period,
        "cond[crtr_ym::LTE]": validated_period,
    }
    if usage_region_code is not None:
        params["cond[usage_rgn_cd::EQ]"] = usage_region_code
    return params


def fetch_local_currency_page(
    period: str,
    *,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    usage_region_code: str | None = None,
    timeout: float = 30,
    max_retries: int = 5,
) -> tuple[dict[str, str], dict[str, Any]]:
    params = make_page_params(
        period,
        page=page,
        per_page=per_page,
        usage_region_code=usage_region_code,
    )
    payload = fetch_json_payload(
        LOCAL_CURRENCY_PAYMENTS_URL,
        params,
        timeout=timeout,
        max_retries=max_retries,
    )
    return params, payload


def get_match_count(payload: Mapping[str, Any]) -> int:
    return int(payload.get("matchCount") or payload.get("totalCount") or 0)


def iter_local_currency_payloads(
    period: str,
    *,
    per_page: int = DEFAULT_PER_PAGE,
    usage_region_code: str | None = None,
    request_sleep_seconds: float = 0.2,
    timeout: float = 30,
    max_retries: int = 5,
) -> tuple[tuple[dict[str, str], dict[str, Any]], ...]:
    validated_period = validate_period(period)
    chunks: list[tuple[dict[str, str], dict[str, Any]]] = []
    page = 1
    total_pages: int | None = None

    while True:
        params, payload = fetch_local_currency_page(
            validated_period,
            page=page,
            per_page=per_page,
            usage_region_code=usage_region_code,
            timeout=timeout,
            max_retries=max_retries,
        )
        chunks.append((params, payload))

        data_rows = normalize_data_rows(payload.get("data"))
        current_count = int(payload.get("currentCount") or len(data_rows))
        if total_pages is None:
            match_count = get_match_count(payload)
            total_pages = math.ceil(match_count / per_page) if match_count else 1

        if page >= total_pages or current_count < per_page:
            return tuple(chunks)

        page += 1
        if request_sleep_seconds > 0:
            time.sleep(request_sleep_seconds)


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


def download_local_currency(
    period: str,
    *,
    per_page: int = DEFAULT_PER_PAGE,
    usage_region_code: str | None = None,
    request_sleep_seconds: float = 0.2,
    timeout: float = 30,
    max_retries: int = 5,
) -> SourcePeriodDownload:
    validated_period = validate_period(period)
    chunks = iter_local_currency_payloads(
        validated_period,
        per_page=per_page,
        usage_region_code=usage_region_code,
        request_sleep_seconds=request_sleep_seconds,
        timeout=timeout,
        max_retries=max_retries,
    )
    payload_chunks = tuple(
        PayloadChunk(
            request_params=params,
            response_payload=(payload,),
        )
        for params, payload in chunks
    )
    data_rows = [
        row
        for _params, payload in chunks
        for row in normalize_data_rows(payload.get("data"))
    ]
    raw_rows = rows_to_raw_rows(data_rows)

    return SourcePeriodDownload(
        source_name=SOURCE_NAME,
        source_name_kor=SOURCE_NAME_KOR,
        source_org_id=SOURCE_ORG_ID,
        source_table_id=SOURCE_TABLE_ID,
        raw_table=RAW_TABLE,
        period=validated_period,
        payload_chunks=payload_chunks,
        raw_columns=RAW_COLUMNS,
        raw_rows=raw_rows,
    )
