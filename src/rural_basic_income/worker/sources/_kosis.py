from __future__ import annotations

import time
from collections.abc import Iterable, Mapping
from typing import Any

from rural_basic_income.pipeline.kosis import fetch_statistics_parameter_data
from rural_basic_income.pipeline.kosis_raw import (
    KosisRawSpec,
    kosis_rows_to_raw_rows,
)
from rural_basic_income.worker.download import PayloadChunk, SourcePeriodDownload

KosisPayloadChunks = list[tuple[dict[str, str], list[dict[str, Any]]]]


class KosisDownloadError(RuntimeError):
    """Raised when KOSIS data cannot be downloaded into an in-memory batch."""


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
