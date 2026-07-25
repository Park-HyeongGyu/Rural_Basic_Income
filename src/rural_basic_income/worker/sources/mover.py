from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from rural_basic_income.worker.download import SourcePeriodDownload
from rural_basic_income.worker.periods import validate_period
from rural_basic_income.worker.sources._kosis import (
    MOVER_SPEC,
    KosisDownloadError,
    KosisPayloadChunks,
    base_params,
    dedupe_preserve_order,
    fetch_rows,
    make_chunks,
    make_source_period_download,
)

# Source: KOSIS 시군구/성/연령(5세)별 이동자수.
SPEC = MOVER_SPEC
LOGGER = logging.getLogger(__name__)


def extract_region_codes(rows: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        dedupe_preserve_order(
            str(row["C1"])
            for row in rows
            if row.get("C1")
        )
    )


def get_region_codes(
    period: str,
    *,
    request_sleep_seconds: float,
    timeout: float,
    max_retries: int,
) -> tuple[str, ...]:
    validated_period = validate_period(period)
    params = {
        **base_params(SPEC, validated_period),
        "objL1": "ALL",
        "objL2": "0",
        "objL3": "000",
    }
    rows = fetch_rows(
        params,
        request_sleep_seconds=request_sleep_seconds,
        timeout=timeout,
        max_retries=max_retries,
    )
    region_codes = extract_region_codes(rows)
    if not region_codes:
        raise KosisDownloadError(
            f"KOSIS mover source returned no region codes for {period}"
        )
    return region_codes


def fetch_mover_payloads(
    period: str,
    *,
    region_codes: Iterable[str] | None = None,
    chunk_size: int = 70,
    request_sleep_seconds: float = 1,
    timeout: float = 30,
    max_retries: int = 5,
) -> KosisPayloadChunks:
    validated_period = validate_period(period)
    resolved_region_codes = tuple(region_codes) if region_codes is not None else None
    if resolved_region_codes is None:
        resolved_region_codes = get_region_codes(
            validated_period,
            request_sleep_seconds=request_sleep_seconds,
            timeout=timeout,
            max_retries=max_retries,
        )

    region_chunks = make_chunks(list(resolved_region_codes), chunk_size)
    LOGGER.info(
        "KOSIS mover chunks prepared period=%s region_codes=%d chunk_size=%d "
        "chunks=%d",
        validated_period,
        len(resolved_region_codes),
        chunk_size,
        len(region_chunks),
    )

    chunks: KosisPayloadChunks = []
    for chunk_index, chunk in enumerate(region_chunks, start=1):
        params = {
            **base_params(SPEC, validated_period),
            "objL1": "+".join(chunk),
            "objL2": "ALL",
            "objL3": "ALL",
        }
        LOGGER.info(
            "KOSIS mover chunk fetch start period=%s chunk=%d/%d region_codes=%d",
            validated_period,
            chunk_index,
            len(region_chunks),
            len(chunk),
        )
        rows = fetch_rows(
            params,
            request_sleep_seconds=request_sleep_seconds,
            timeout=timeout,
            max_retries=max_retries,
        )
        LOGGER.info(
            "KOSIS mover chunk fetch complete period=%s chunk=%d/%d rows=%d",
            validated_period,
            chunk_index,
            len(region_chunks),
            len(rows),
        )
        chunks.append(
            (
                params,
                rows,
            )
        )
    return chunks


def download_mover(
    period: str,
    *,
    region_codes: Iterable[str] | None = None,
    chunk_size: int = 70,
    request_sleep_seconds: float = 1,
    timeout: float = 30,
    max_retries: int = 5,
) -> SourcePeriodDownload:
    validated_period = validate_period(period)
    chunks = fetch_mover_payloads(
        validated_period,
        region_codes=region_codes,
        chunk_size=chunk_size,
        request_sleep_seconds=request_sleep_seconds,
        timeout=timeout,
        max_retries=max_retries,
    )
    return make_source_period_download(SPEC, validated_period, chunks)
