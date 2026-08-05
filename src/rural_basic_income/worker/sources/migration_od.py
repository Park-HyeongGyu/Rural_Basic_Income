from __future__ import annotations

import csv
import json
import logging
import math
import random
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, unquote
from urllib.request import Request, urlopen

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from rural_basic_income.config import Settings, get_settings
from rural_basic_income.db.connection import get_engine
from rural_basic_income.worker import raw_writer
from rural_basic_income.worker.download import (
    PayloadChunk,
    SourcePeriodDownload,
    SourcePeriodUnavailable,
)
from rural_basic_income.worker.periods import validate_period

# Source: data.go.kr 행정안전부 지역별 인구이동 현황.
SOURCE_NAME = "migration_od"
SOURCE_NAME_KOR = "지역별 인구이동 현황"
SOURCE_ORG_ID = "1741000"
SOURCE_TABLE_ID = "ppltnDataStus"
RAW_TABLE = "migration_od"
MIGRATION_OD_URL = (
    "https://apis.data.go.kr/1741000/ppltnDataStus/selectPpltnDataStus"
)
PROJECT_ROOT = Path(__file__).resolve().parents[4]
SIDO_CODES_PATH = (
    PROJECT_ROOT
    / "src"
    / "rural_basic_income"
    / "worker"
    / "resources"
    / "migration_od_sido_codes.csv"
)
DEFAULT_PER_PAGE = 1_000
DEFAULT_PAGE_WORKERS = 1
DEFAULT_SCOPE_WORKERS = 1
DEFAULT_REQUEST_SLEEP_SECONDS = 0.05
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
BASIC_RAW_COLUMNS = (
    "statsYm",
    "mvinAdmmCd",
    "mvinCtpvNm",
    "mvinSggNm",
    "mvinDongNm",
    "mvtAdmmCd",
    "mvtCtpvNm",
    "mvtSggNm",
    "mvtDongNm",
    "totNmprCnt",
    "maleNmprCnt",
    "femlNmprCnt",
)
AGE_RAW_COLUMNS = tuple(
    f"{sex}{age}AgeNmprCnt"
    for sex in ("male", "feml")
    for age in range(111)
)
RAW_COLUMNS = (*BASIC_RAW_COLUMNS, *AGE_RAW_COLUMNS, "downloaded_at")
LOGGER = logging.getLogger(__name__)


class MigrationOdApiKeyMissing(RuntimeError):
    """Raised when DATA_GO_KR_API_KEY is missing."""


class MigrationOdApiError(RuntimeError):
    """Raised when the migration OD API response violates the source contract."""


@dataclass(frozen=True)
class SidoCode:
    api_code: str
    region_sido: str
    request_order: int

    @property
    def prefix(self) -> str:
        return self.api_code[:2]


@dataclass(frozen=True)
class MigrationOdPage:
    request_params: dict[str, str]
    payload: dict[str, Any]
    rows: tuple[dict[str, Any], ...]
    total_count: int
    result_code: str
    result_msg: str

    @property
    def nodata(self) -> bool:
        return self.result_code == "3"


def load_sido_codes(path: Path = SIDO_CODES_PATH) -> tuple[SidoCode, ...]:
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    required_columns = ["api_code", "region_sido", "request_order"]
    if not rows:
        raise MigrationOdApiError(f"{path} must contain at least one sido code")
    if list(rows[0]) != required_columns:
        raise MigrationOdApiError(f"{path} must have columns {required_columns}")

    codes = tuple(
        sorted(
            (
                SidoCode(
                    api_code=row["api_code"].strip(),
                    region_sido=row["region_sido"].strip(),
                    request_order=int(row["request_order"]),
                )
                for row in rows
            ),
            key=lambda item: item.request_order,
        )
    )
    if len(codes) != 17:
        raise MigrationOdApiError(f"{path} must contain 17 sido codes")
    if any(len(code.api_code) != 10 or not code.api_code.isdigit() for code in codes):
        raise MigrationOdApiError("migration OD sido codes must be 10 digit strings")
    return codes


def build_migration_od_url(
    params: Mapping[str, str],
    *,
    api_key: str | None = None,
    settings: Settings | None = None,
) -> str:
    resolved_api_key = api_key or (settings or get_settings()).data_go_kr_api_key
    if not resolved_api_key:
        raise MigrationOdApiKeyMissing("DATA_GO_KR_API_KEY is required")

    query = {
        "serviceKey": unquote(resolved_api_key),
        **params,
        "type": "json",
    }
    return f"{MIGRATION_OD_URL}?{urlencode(query)}"


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


def parse_response_head(payload: Mapping[str, Any]) -> dict[str, Any]:
    response = payload.get("Response")
    if not isinstance(response, Mapping):
        raise MigrationOdApiError("migration OD response missing Response object")
    head = response.get("head")
    if not isinstance(head, Mapping):
        raise MigrationOdApiError("migration OD response missing Response.head")
    return dict(head)


def parse_response_items(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    response = payload.get("Response")
    if not isinstance(response, Mapping):
        raise MigrationOdApiError("migration OD response missing Response object")

    items = response.get("items")
    if items in ("", None):
        return ()
    if not isinstance(items, Mapping):
        raise MigrationOdApiError("migration OD Response.items was not an object")

    item = items.get("item")
    if item in ("", None):
        return ()
    if isinstance(item, list):
        return tuple(dict(row) for row in item)
    if isinstance(item, Mapping):
        return (dict(item),)
    raise MigrationOdApiError(
        f"migration OD Response.items.item had unexpected type: {type(item)}"
    )


def fetch_json_payload(
    params: Mapping[str, str],
    *,
    timeout: float = 30,
    max_retries: int = 5,
    base_retry_sleep_seconds: float = 1,
    max_retry_sleep_seconds: float = 60,
) -> dict[str, Any]:
    url = build_migration_od_url(params)
    request = Request(
        url,
        headers={"User-Agent": "rural-basic-income/0.3.1"},
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
            message = f"migration OD request failed with HTTP {exc.code}"
            if response_text:
                message = f"{message}: {response_text[:300]}"
            raise SourcePeriodUnavailable(message) from exc
        except (TimeoutError, URLError) as exc:
            if attempt_index < max_retries:
                LOGGER.warning(
                    "migration OD request retryable network error attempt=%d/%d "
                    "error=%s",
                    attempt_index + 1,
                    max_retries + 1,
                    exc,
                )
                time.sleep(
                    retry_sleep_seconds(
                        attempt_index,
                        base_sleep_seconds=base_retry_sleep_seconds,
                        max_sleep_seconds=max_retry_sleep_seconds,
                    )
                )
                continue
            raise SourcePeriodUnavailable(
                f"migration OD request failed after retries: {exc}"
            ) from exc

        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            if is_retryable_message(response_text) and attempt_index < max_retries:
                LOGGER.warning(
                    "migration OD request retryable non-JSON response "
                    "attempt=%d/%d body=%s",
                    attempt_index + 1,
                    max_retries + 1,
                    response_text[:200],
                )
                time.sleep(
                    retry_sleep_seconds(
                        attempt_index,
                        base_sleep_seconds=base_retry_sleep_seconds,
                        max_sleep_seconds=max_retry_sleep_seconds,
                    )
                )
                continue
            raise SourcePeriodUnavailable(
                "migration OD response was not valid JSON: "
                f"{response_text[:300]}"
            ) from exc

        if not isinstance(payload, dict):
            raise MigrationOdApiError("migration OD response JSON was not an object")
        return payload

    raise SourcePeriodUnavailable("migration OD request failed after retry attempts")


def make_page_params(
    period: str,
    *,
    destination_code: str,
    origin_code: str,
    page: int,
    per_page: int,
) -> dict[str, str]:
    if page < 1:
        raise ValueError("page must be at least 1")
    if per_page < 1:
        raise ValueError("per_page must be at least 1")
    validated_period = validate_period(period)
    return {
        "pageNo": str(page),
        "numOfRows": str(per_page),
        "srchFrYm": validated_period,
        "srchToYm": validated_period,
        "mvinAdmmCd": destination_code,
        "mvtAdmmCd": origin_code,
    }


def normalize_result_code(value: Any) -> str:
    return "" if value is None else str(value)


def fetch_migration_od_page(
    period: str,
    *,
    destination_code: str,
    origin_code: str,
    page: int = 1,
    per_page: int = DEFAULT_PER_PAGE,
    timeout: float = 30,
    max_retries: int = 5,
) -> MigrationOdPage:
    params = make_page_params(
        period,
        destination_code=destination_code,
        origin_code=origin_code,
        page=page,
        per_page=per_page,
    )
    payload = fetch_json_payload(
        params,
        timeout=timeout,
        max_retries=max_retries,
    )
    head = parse_response_head(payload)
    result_code = normalize_result_code(head.get("resultCode"))
    result_msg = str(head.get("resultMsg") or "")

    if result_code == "3":
        return MigrationOdPage(
            request_params=params,
            payload=payload,
            rows=(),
            total_count=0,
            result_code=result_code,
            result_msg=result_msg,
        )
    if result_code != "0":
        message = f"migration OD API rejected request: {result_code} {result_msg}"
        if result_code in {"10", "11"}:
            raise MigrationOdApiError(message)
        raise SourcePeriodUnavailable(message)

    rows = parse_response_items(payload)
    total_count = int(head.get("totalCount") or len(rows) or 0)
    return MigrationOdPage(
        request_params=params,
        payload=payload,
        rows=rows,
        total_count=total_count,
        result_code=result_code,
        result_msg=result_msg,
    )


def payload_chunk_for_page(page: MigrationOdPage) -> PayloadChunk:
    envelope = {
        "head": parse_response_head(page.payload),
        "items": [dict(row) for row in page.rows],
    }
    return PayloadChunk(
        request_params=page.request_params,
        response_payload=(envelope,),
    )


def code_matches_scope(row_code: Any, scope_code: str) -> bool:
    code_text = str(row_code or "")
    return len(code_text) == 10 and code_text.startswith(scope_code[:2])


def validate_raw_row(
    row: Mapping[str, Any],
    *,
    period: str,
    destination_code: str,
    origin_code: str,
) -> None:
    if str(row.get("statsYm") or "") != period:
        raise MigrationOdApiError(
            "migration OD row period mismatch: "
            f"expected={period} actual={row.get('statsYm')}"
        )
    if not code_matches_scope(row.get("mvinAdmmCd"), destination_code):
        raise MigrationOdApiError(
            "migration OD destination code outside requested scope: "
            f"scope={destination_code} row={row.get('mvinAdmmCd')}"
        )
    if not code_matches_scope(row.get("mvtAdmmCd"), origin_code):
        raise MigrationOdApiError(
            "migration OD origin code outside requested scope: "
            f"scope={origin_code} row={row.get('mvtAdmmCd')}"
        )


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


def make_empty_download(period: str) -> SourcePeriodDownload:
    validated_period = validate_period(period)
    return SourcePeriodDownload(
        source_name=SOURCE_NAME,
        source_name_kor=SOURCE_NAME_KOR,
        source_org_id=SOURCE_ORG_ID,
        source_table_id=SOURCE_TABLE_ID,
        raw_table=RAW_TABLE,
        period=validated_period,
        payload_chunks=(),
        raw_columns=RAW_COLUMNS,
        raw_rows=(),
    )


def raw_row_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("statsYm") or ""),
        str(row.get("mvinAdmmCd") or ""),
        str(row.get("mvtAdmmCd") or ""),
    )


def validate_scope_page_rows(
    rows: tuple[dict[str, Any], ...],
    *,
    period: str,
    destination_code: str,
    origin_code: str,
    seen_keys: set[tuple[str, str, str]],
) -> None:
    for row in rows:
        validate_raw_row(
            row,
            period=period,
            destination_code=destination_code,
            origin_code=origin_code,
        )
        row_key = raw_row_key(row)
        if row_key in seen_keys:
            raise MigrationOdApiError(
                "migration OD duplicate row key across pages/scopes: "
                f"{row_key}"
            )
        seen_keys.add(row_key)


def insert_payload_page(
    connection: Connection,
    *,
    period: str,
    chunk_index: int,
    page: MigrationOdPage,
) -> None:
    chunk = payload_chunk_for_page(page)
    connection.execute(
        text(
            """
            INSERT INTO raw_json.payloads (
                source_name,
                source_name_kor,
                source_org_id,
                source_table_id,
                raw_table,
                period,
                chunk_index,
                request_params,
                response_payload,
                row_count
            )
            VALUES (
                :source_name,
                :source_name_kor,
                :source_org_id,
                :source_table_id,
                :raw_table,
                :period,
                :chunk_index,
                CAST(:request_params AS jsonb),
                CAST(:response_payload AS jsonb),
                :row_count
            )
            """
        ),
        {
            "source_name": SOURCE_NAME,
            "source_name_kor": SOURCE_NAME_KOR,
            "source_org_id": SOURCE_ORG_ID,
            "source_table_id": SOURCE_TABLE_ID,
            "raw_table": RAW_TABLE,
            "period": period,
            "chunk_index": chunk_index,
            "request_params": json.dumps(
                dict(chunk.request_params),
                ensure_ascii=False,
            ),
            "response_payload": json.dumps(
                [dict(row) for row in chunk.response_payload],
                ensure_ascii=False,
            ),
            "row_count": chunk.row_count,
        },
    )


def insert_raw_page_rows(
    connection: Connection,
    *,
    period: str,
    rows: tuple[dict[str, Any], ...],
    downloaded_at: str,
) -> None:
    if not rows:
        return
    page_download = SourcePeriodDownload(
        source_name=SOURCE_NAME,
        source_name_kor=SOURCE_NAME_KOR,
        source_org_id=SOURCE_ORG_ID,
        source_table_id=SOURCE_TABLE_ID,
        raw_table=RAW_TABLE,
        period=period,
        payload_chunks=(),
        raw_columns=RAW_COLUMNS,
        raw_rows=rows_to_raw_rows(list(rows), downloaded_at=downloaded_at),
    )
    raw_writer.insert_raw_rows(connection, page_download)


def mark_migration_od_period_success(
    connection: Connection,
    *,
    period: str,
    row_count: int,
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO metadata.download_status (
                source_name,
                source_name_kor,
                source_table_id,
                period,
                status,
                row_count,
                error_message
            )
            VALUES (
                :source_name,
                :source_name_kor,
                :source_table_id,
                :period,
                :status,
                :row_count,
                NULL
            )
            ON CONFLICT (source_name, period)
            DO UPDATE SET
                source_name_kor = EXCLUDED.source_name_kor,
                source_table_id = EXCLUDED.source_table_id,
                status = EXCLUDED.status,
                row_count = EXCLUDED.row_count,
                downloaded_at = CURRENT_TIMESTAMP,
                error_message = NULL
            """
        ),
        {
            "source_name": SOURCE_NAME,
            "source_name_kor": SOURCE_NAME_KOR,
            "source_table_id": SOURCE_TABLE_ID,
            "period": period,
            "status": raw_writer.DOWNLOAD_STATUS_OK,
            "row_count": row_count,
        },
    )


def stream_scope_pages_to_raw(
    connection: Connection,
    period: str,
    *,
    destination: SidoCode,
    origin: SidoCode,
    chunk_index: int,
    downloaded_at: str,
    per_page: int = DEFAULT_PER_PAGE,
    timeout: float = 30,
    max_retries: int = 5,
    request_sleep_seconds: float = DEFAULT_REQUEST_SLEEP_SECONDS,
) -> tuple[int, int, bool]:
    LOGGER.info(
        "migration OD streaming scope start period=%s destination=%s origin=%s",
        period,
        destination.region_sido,
        origin.region_sido,
    )
    first_page = fetch_migration_od_page(
        period,
        destination_code=destination.api_code,
        origin_code=origin.api_code,
        page=1,
        per_page=per_page,
        timeout=timeout,
        max_retries=max_retries,
    )
    chunk_index += 1
    insert_payload_page(
        connection,
        period=period,
        chunk_index=chunk_index,
        page=first_page,
    )
    if first_page.nodata:
        LOGGER.info(
            "migration OD streaming scope nodata period=%s destination=%s origin=%s",
            period,
            destination.region_sido,
            origin.region_sido,
        )
        return chunk_index, 0, True

    total_pages = (
        math.ceil(first_page.total_count / per_page)
        if first_page.total_count
        else 1
    )
    LOGGER.info(
        "migration OD streaming scope pagination period=%s destination=%s "
        "origin=%s total_count=%d total_pages=%d per_page=%d",
        period,
        destination.region_sido,
        origin.region_sido,
        first_page.total_count,
        total_pages,
        per_page,
    )

    seen_keys: set[tuple[str, str, str]] = set()
    validate_scope_page_rows(
        first_page.rows,
        period=period,
        destination_code=destination.api_code,
        origin_code=origin.api_code,
        seen_keys=seen_keys,
    )
    inserted_row_count = len(first_page.rows)
    insert_raw_page_rows(
        connection,
        period=period,
        rows=first_page.rows,
        downloaded_at=downloaded_at,
    )

    if request_sleep_seconds > 0 and total_pages > 1:
        time.sleep(request_sleep_seconds)

    for page_number in range(2, total_pages + 1):
        LOGGER.info(
            "migration OD streaming page start period=%s destination=%s "
            "origin=%s page=%d/%d",
            period,
            destination.region_sido,
            origin.region_sido,
            page_number,
            total_pages,
        )
        page = fetch_migration_od_page(
            period,
            destination_code=destination.api_code,
            origin_code=origin.api_code,
            page=page_number,
            per_page=per_page,
            timeout=timeout,
            max_retries=max_retries,
        )
        if page.nodata:
            raise MigrationOdApiError(
                "migration OD returned NODATA after a successful first page: "
                f"period={period} destination={destination.api_code} "
                f"origin={origin.api_code} page={page_number}"
            )
        chunk_index += 1
        insert_payload_page(
            connection,
            period=period,
            chunk_index=chunk_index,
            page=page,
        )
        validate_scope_page_rows(
            page.rows,
            period=period,
            destination_code=destination.api_code,
            origin_code=origin.api_code,
            seen_keys=seen_keys,
        )
        inserted_row_count += len(page.rows)
        insert_raw_page_rows(
            connection,
            period=period,
            rows=page.rows,
            downloaded_at=downloaded_at,
        )
        LOGGER.info(
            "migration OD streaming page complete period=%s destination=%s "
            "origin=%s page=%d/%d rows=%d",
            period,
            destination.region_sido,
            origin.region_sido,
            page_number,
            total_pages,
            len(page.rows),
        )
        if request_sleep_seconds > 0 and page_number < total_pages:
            time.sleep(request_sleep_seconds)

    if inserted_row_count != first_page.total_count:
        raise MigrationOdApiError(
            "migration OD row count mismatch: "
            f"period={period} destination={destination.api_code} "
            f"origin={origin.api_code} expected={first_page.total_count} "
            f"actual={inserted_row_count}"
        )

    LOGGER.info(
        "migration OD streaming scope complete period=%s destination=%s "
        "origin=%s pages=%d rows=%d",
        period,
        destination.region_sido,
        origin.region_sido,
        total_pages,
        inserted_row_count,
    )
    return chunk_index, inserted_row_count, False


def write_migration_od_source_period(
    period: str,
    *,
    engine: Engine | None = None,
    force: bool = False,
    per_page: int = DEFAULT_PER_PAGE,
    page_workers: int | None = None,
    scope_workers: int | None = None,
    request_sleep_seconds: float = DEFAULT_REQUEST_SLEEP_SECONDS,
    timeout: float = 30,
    max_retries: int = 5,
    sido_codes_path: Path = SIDO_CODES_PATH,
) -> raw_writer.RawWriteResult:
    validated_period = validate_period(period)
    db_engine = engine or get_engine()
    sido_codes = load_sido_codes(sido_codes_path)
    expected_scope_count = len(sido_codes) * len(sido_codes)
    downloaded_at = datetime.now(UTC).isoformat()
    if page_workers not in (None, 1) or scope_workers not in (None, 1):
        LOGGER.warning(
            "migration OD streaming write ignores worker concurrency options "
            "for memory safety page_workers=%s scope_workers=%s",
            page_workers,
            scope_workers,
        )

    LOGGER.info(
        "migration OD streaming write start period=%s scopes=%d per_page=%d "
        "force=%s",
        validated_period,
        expected_scope_count,
        per_page,
        force,
    )
    empty_download = make_empty_download(validated_period)
    try:
        with db_engine.begin() as connection:
            raw_writer.create_writer_tables(connection)
            raw_writer.acquire_source_period_name_lock(
                connection,
                SOURCE_NAME,
                validated_period,
            )
            LOGGER.info(
                "migration OD streaming write lock acquired period=%s",
                validated_period,
            )

            existing_row_count = raw_writer.successful_row_count(
                connection,
                empty_download,
            )
            if existing_row_count is not None and not force:
                LOGGER.info(
                    "migration OD streaming write skipped existing period=%s rows=%d",
                    validated_period,
                    existing_row_count,
                )
                return raw_writer.RawWriteResult(
                    source_name=SOURCE_NAME,
                    period=validated_period,
                    status="skipped",
                    row_count=existing_row_count,
                )

            raw_writer.ensure_raw_table(connection, RAW_TABLE, RAW_COLUMNS)
            if force:
                raw_writer.delete_existing_source_period(connection, empty_download)

            chunk_index = 0
            raw_row_count = 0
            completed_scope_count = 0
            nodata_scope_count = 0
            for destination in sido_codes:
                for origin in sido_codes:
                    chunk_index, scope_rows, nodata = stream_scope_pages_to_raw(
                        connection,
                        validated_period,
                        destination=destination,
                        origin=origin,
                        chunk_index=chunk_index,
                        downloaded_at=downloaded_at,
                        per_page=per_page,
                        timeout=timeout,
                        max_retries=max_retries,
                        request_sleep_seconds=request_sleep_seconds,
                    )
                    completed_scope_count += 1
                    raw_row_count += scope_rows
                    if nodata:
                        nodata_scope_count += 1

            if completed_scope_count != expected_scope_count:
                raise MigrationOdApiError(
                    "migration OD did not complete every scope: "
                    f"completed={completed_scope_count}"
                )
            if nodata_scope_count == completed_scope_count:
                raise SourcePeriodUnavailable(
                    "migration OD source returned NODATA for every scope "
                    f"in {validated_period}"
                )

            mark_migration_od_period_success(
                connection,
                period=validated_period,
                row_count=raw_row_count,
            )
    except Exception:
        LOGGER.exception(
            "migration OD streaming write failed period=%s transaction=rollback",
            validated_period,
        )
        raise

    LOGGER.info(
        "migration OD streaming write committed period=%s rows=%d chunks=%d",
        validated_period,
        raw_row_count,
        chunk_index,
    )
    return raw_writer.RawWriteResult(
        source_name=SOURCE_NAME,
        period=validated_period,
        status="written",
        row_count=raw_row_count,
    )


def fetch_scope_pages(
    period: str,
    *,
    destination: SidoCode,
    origin: SidoCode,
    per_page: int = DEFAULT_PER_PAGE,
    page_workers: int = DEFAULT_PAGE_WORKERS,
    timeout: float = 30,
    max_retries: int = 5,
    request_sleep_seconds: float = DEFAULT_REQUEST_SLEEP_SECONDS,
) -> tuple[list[PayloadChunk], list[dict[str, Any]], bool]:
    if page_workers < 1:
        raise ValueError("page_workers must be at least 1")
    LOGGER.info(
        "migration OD scope fetch start period=%s destination=%s origin=%s",
        period,
        destination.region_sido,
        origin.region_sido,
    )
    first_page = fetch_migration_od_page(
        period,
        destination_code=destination.api_code,
        origin_code=origin.api_code,
        page=1,
        per_page=per_page,
        timeout=timeout,
        max_retries=max_retries,
    )
    chunks = [payload_chunk_for_page(first_page)]
    if first_page.nodata:
        LOGGER.info(
            "migration OD scope nodata period=%s destination=%s origin=%s",
            period,
            destination.region_sido,
            origin.region_sido,
        )
        return chunks, [], True

    total_pages = (
        math.ceil(first_page.total_count / per_page)
        if first_page.total_count
        else 1
    )
    LOGGER.info(
        "migration OD scope pagination period=%s destination=%s origin=%s "
        "total_count=%d total_pages=%d per_page=%d",
        period,
        destination.region_sido,
        origin.region_sido,
        first_page.total_count,
        total_pages,
        per_page,
    )
    rows = list(first_page.rows)
    if request_sleep_seconds > 0 and total_pages > 1:
        time.sleep(request_sleep_seconds)

    page_numbers = range(2, total_pages + 1)
    effective_page_workers = min(page_workers, total_pages - 1)

    def fetch_remaining_page(page_number: int) -> tuple[int, MigrationOdPage]:
        LOGGER.info(
            "migration OD page fetch start period=%s destination=%s origin=%s "
            "page=%d/%d",
            period,
            destination.region_sido,
            origin.region_sido,
            page_number,
            total_pages,
        )
        page = fetch_migration_od_page(
            period,
            destination_code=destination.api_code,
            origin_code=origin.api_code,
            page=page_number,
            per_page=per_page,
            timeout=timeout,
            max_retries=max_retries,
        )
        return page_number, page

    if effective_page_workers <= 1:
        remaining_pages = [
            fetch_remaining_page(page_number)
            for page_number in page_numbers
        ]
    else:
        with ThreadPoolExecutor(max_workers=effective_page_workers) as executor:
            futures = [
                executor.submit(fetch_remaining_page, page_number)
                for page_number in page_numbers
            ]
            remaining_pages = [future.result() for future in as_completed(futures)]

    for page_number, page in sorted(remaining_pages, key=lambda item: item[0]):
        if page.nodata:
            raise MigrationOdApiError(
                "migration OD returned NODATA after a successful first page: "
                f"period={period} destination={destination.api_code} "
                f"origin={origin.api_code} page={page_number}"
            )
        chunks.append(payload_chunk_for_page(page))
        rows.extend(page.rows)
        LOGGER.info(
            "migration OD page fetch complete period=%s destination=%s origin=%s "
            "page=%d/%d rows=%d",
            period,
            destination.region_sido,
            origin.region_sido,
            page_number,
            total_pages,
            len(page.rows),
        )
        if request_sleep_seconds > 0 and page_number < total_pages:
            time.sleep(request_sleep_seconds)

    if len(rows) != first_page.total_count:
        raise MigrationOdApiError(
            "migration OD row count mismatch: "
            f"period={period} destination={destination.api_code} "
            f"origin={origin.api_code} expected={first_page.total_count} "
            f"actual={len(rows)}"
        )

    seen_keys: set[tuple[str, str, str]] = set()
    for row in rows:
        validate_raw_row(
            row,
            period=period,
            destination_code=destination.api_code,
            origin_code=origin.api_code,
        )
        row_key = (
            str(row.get("statsYm") or ""),
            str(row.get("mvinAdmmCd") or ""),
            str(row.get("mvtAdmmCd") or ""),
        )
        if row_key in seen_keys:
            raise MigrationOdApiError(
                "migration OD duplicate row key across pages/scopes: "
                f"{row_key}"
            )
        seen_keys.add(row_key)

    LOGGER.info(
        "migration OD scope fetch complete period=%s destination=%s origin=%s "
        "pages=%d rows=%d",
        period,
        destination.region_sido,
        origin.region_sido,
        total_pages,
        len(rows),
    )
    return chunks, rows, False


def download_migration_od(
    period: str,
    *,
    per_page: int = DEFAULT_PER_PAGE,
    page_workers: int = DEFAULT_PAGE_WORKERS,
    scope_workers: int = DEFAULT_SCOPE_WORKERS,
    request_sleep_seconds: float = DEFAULT_REQUEST_SLEEP_SECONDS,
    timeout: float = 30,
    max_retries: int = 5,
    sido_codes_path: Path = SIDO_CODES_PATH,
) -> SourcePeriodDownload:
    validated_period = validate_period(period)
    if scope_workers < 1:
        raise ValueError("scope_workers must be at least 1")
    sido_codes = load_sido_codes(sido_codes_path)
    all_chunks: list[PayloadChunk] = []
    all_rows: list[dict[str, Any]] = []
    nodata_scope_count = 0
    completed_scope_count = 0
    scopes = [
        (scope_index, destination, origin)
        for scope_index, (destination, origin) in enumerate(
            (destination, origin)
            for destination in sido_codes
            for origin in sido_codes
        )
    ]

    LOGGER.info(
        "migration OD fetch month start period=%s scopes=%d per_page=%d "
        "page_workers=%d scope_workers=%d",
        validated_period,
        len(scopes),
        per_page,
        page_workers,
        scope_workers,
    )

    def fetch_scope(
        scope_index: int,
        destination: SidoCode,
        origin: SidoCode,
    ) -> tuple[int, list[PayloadChunk], list[dict[str, Any]], bool]:
        chunks, rows, nodata = fetch_scope_pages(
            validated_period,
            destination=destination,
            origin=origin,
            per_page=per_page,
            page_workers=page_workers,
            timeout=timeout,
            max_retries=max_retries,
            request_sleep_seconds=request_sleep_seconds,
        )
        return scope_index, chunks, rows, nodata

    effective_scope_workers = min(scope_workers, len(scopes))
    if effective_scope_workers <= 1:
        scope_results = [
            fetch_scope(scope_index, destination, origin)
            for scope_index, destination, origin in scopes
        ]
    else:
        with ThreadPoolExecutor(max_workers=effective_scope_workers) as executor:
            futures = [
                executor.submit(fetch_scope, scope_index, destination, origin)
                for scope_index, destination, origin in scopes
            ]
            scope_results = [future.result() for future in as_completed(futures)]

    for _scope_index, chunks, rows, nodata in sorted(
        scope_results,
        key=lambda item: item[0],
    ):
        completed_scope_count += 1
        if nodata:
            nodata_scope_count += 1
        all_chunks.extend(chunks)
        all_rows.extend(rows)

    if completed_scope_count != len(scopes):
        raise MigrationOdApiError(
            "migration OD did not complete every scope: "
            f"completed={completed_scope_count}"
        )
    if nodata_scope_count == completed_scope_count:
        raise SourcePeriodUnavailable(
            f"migration OD source returned NODATA for every scope in {validated_period}"
        )

    raw_rows = rows_to_raw_rows(all_rows)
    LOGGER.info(
        "migration OD fetch month complete period=%s scopes=%d nodata_scopes=%d "
        "payload_chunks=%d raw_rows=%d",
        validated_period,
        completed_scope_count,
        nodata_scope_count,
        len(all_chunks),
        len(raw_rows),
    )
    return SourcePeriodDownload(
        source_name=SOURCE_NAME,
        source_name_kor=SOURCE_NAME_KOR,
        source_org_id=SOURCE_ORG_ID,
        source_table_id=SOURCE_TABLE_ID,
        raw_table=RAW_TABLE,
        period=validated_period,
        payload_chunks=tuple(all_chunks),
        raw_columns=RAW_COLUMNS,
        raw_rows=raw_rows,
    )
