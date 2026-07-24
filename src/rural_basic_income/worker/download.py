from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PayloadChunk:
    request_params: Mapping[str, str]
    response_payload: tuple[Mapping[str, Any], ...]

    @property
    def row_count(self) -> int:
        return len(self.response_payload)


@dataclass(frozen=True)
class SourcePeriodDownload:
    source_name: str
    source_name_kor: str
    source_org_id: str
    source_table_id: str
    raw_table: str
    period: str
    payload_chunks: tuple[PayloadChunk, ...]
    raw_columns: tuple[str, ...]
    raw_rows: tuple[Mapping[str, str], ...]

    @property
    def payload_row_count(self) -> int:
        return sum(chunk.row_count for chunk in self.payload_chunks)

    @property
    def raw_row_count(self) -> int:
        return len(self.raw_rows)


@dataclass(frozen=True)
class PeriodDownload:
    period: str
    sources: tuple[SourcePeriodDownload, ...]

    @property
    def source_names(self) -> tuple[str, ...]:
        return tuple(source.source_name for source in self.sources)

    def get_source(self, source_name: str) -> SourcePeriodDownload:
        for source in self.sources:
            if source.source_name == source_name:
                return source
        raise KeyError(f"download result does not contain source: {source_name}")
