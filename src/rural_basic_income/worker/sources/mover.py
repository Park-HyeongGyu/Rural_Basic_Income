from __future__ import annotations

from collections.abc import Iterable

from rural_basic_income.pipeline.kosis_raw import (
    MOVER_SPEC,
    base_params,
    make_chunks,
    validate_period,
)
from rural_basic_income.worker.download import SourcePeriodDownload
from rural_basic_income.worker.sources.household import (
    extract_region_codes,
    fetch_household_payload,
)
from rural_basic_income.worker.sources._kosis import (
    KosisDownloadError,
    KosisPayloadChunks,
    fetch_rows,
    make_source_period_download,
)

# Source: KOSIS 시군구/성/연령(5세)별 이동자수.
SPEC = MOVER_SPEC


def get_region_codes(
    period: str,
    *,
    request_sleep_seconds: float,
    timeout: float,
    max_retries: int,
) -> tuple[str, ...]:
    _params, rows = fetch_household_payload(
        period,
        request_sleep_seconds=request_sleep_seconds,
        timeout=timeout,
        max_retries=max_retries,
    )
    region_codes = extract_region_codes(rows)
    if not region_codes:
        raise KosisDownloadError(
            f"KOSIS household source returned no region codes for {period}"
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

    chunks: KosisPayloadChunks = []
    for chunk in make_chunks(list(resolved_region_codes), chunk_size):
        params = {
            **base_params(SPEC, validated_period),
            "objL1": "+".join(chunk),
            "objL2": "ALL",
            "objL3": "ALL",
        }
        chunks.append(
            (
                params,
                fetch_rows(
                    params,
                    request_sleep_seconds=request_sleep_seconds,
                    timeout=timeout,
                    max_retries=max_retries,
                ),
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
