from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rural_basic_income.pipeline.kosis_raw import (
    HOUSEHOLD_SPEC,
    base_params,
    dedupe_preserve_order,
    validate_period,
)
from rural_basic_income.worker.download import SourcePeriodDownload
from rural_basic_income.worker.sources._kosis import (
    KosisPayloadChunks,
    fetch_rows,
    make_source_period_download,
)

# Source: KOSIS 행정구역(시군구)별 주민등록세대수.
SPEC = HOUSEHOLD_SPEC


def extract_region_codes(rows: list[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        dedupe_preserve_order(
            str(row["C1"])
            for row in rows
            if row.get("C1")
        )
    )


def fetch_household_payload(
    period: str,
    *,
    request_sleep_seconds: float = 1,
    timeout: float = 30,
    max_retries: int = 5,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    validated_period = validate_period(period)
    params = {
        **base_params(SPEC, validated_period),
        "objL1": "ALL",
    }
    rows = fetch_rows(
        params,
        request_sleep_seconds=request_sleep_seconds,
        timeout=timeout,
        max_retries=max_retries,
    )
    return params, rows


def download_household(
    period: str,
    *,
    request_sleep_seconds: float = 1,
    timeout: float = 30,
    max_retries: int = 5,
) -> SourcePeriodDownload:
    validated_period = validate_period(period)
    chunks: KosisPayloadChunks = [
        fetch_household_payload(
            validated_period,
            request_sleep_seconds=request_sleep_seconds,
            timeout=timeout,
            max_retries=max_retries,
        )
    ]
    return make_source_period_download(SPEC, validated_period, chunks)
