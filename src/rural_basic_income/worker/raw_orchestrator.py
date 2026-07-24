from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

from rural_basic_income.db.connection import get_engine
from rural_basic_income.worker.download import SourcePeriodDownload
from rural_basic_income.worker.periods import iter_month_periods, validate_period
from rural_basic_income.worker import raw_writer
from rural_basic_income.worker.sources import (
    electricity,
    household,
    local_currency,
    mover,
    population,
)

RawRefreshStatus = Literal[
    "skipped_existing",
    "downloaded_written",
    "downloaded_skipped",
]
DownloadFunction = Callable[..., SourcePeriodDownload]
RawWriterFunction = Callable[..., raw_writer.RawWriteResult]

DEFAULT_RAW_SOURCES = (
    "household",
    "population",
    "mover",
    "electricity",
    "local_currency",
)

SOURCE_DOWNLOADERS: dict[str, DownloadFunction] = {
    "household": household.download_household,
    "population": population.download_population,
    "mover": mover.download_mover,
    "electricity": electricity.download_electricity,
    "local_currency": local_currency.download_local_currency,
}


class RawOrchestratorError(RuntimeError):
    """Raised when a raw refresh request cannot be orchestrated."""


@dataclass(frozen=True)
class RawRefreshResult:
    source_name: str
    period: str
    status: RawRefreshStatus
    row_count: int

    @property
    def downloaded(self) -> bool:
        return self.status in {"downloaded_written", "downloaded_skipped"}


def source_period_success_row_count(
    source_name: str,
    period: str,
    *,
    engine: Engine | None = None,
) -> int | None:
    validate_period(period)
    db_engine = engine or get_engine()
    with db_engine.connect() as connection:
        if not raw_writer.table_exists(
            connection,
            "metadata",
            "download_status",
        ):
            return None

        row_count = connection.execute(
            text(
                """
                SELECT row_count
                FROM metadata.download_status
                WHERE source_name = :source_name
                  AND period = :period
                  AND status = :status
                """
            ),
            {
                "source_name": source_name,
                "period": period,
                "status": raw_writer.DOWNLOAD_STATUS_OK,
            },
        ).scalar_one_or_none()

    if row_count is None:
        return None
    return int(row_count or 0)


def get_downloader(
    source_name: str,
    downloaders: Mapping[str, DownloadFunction] | None = None,
) -> DownloadFunction:
    resolved_downloaders = downloaders or SOURCE_DOWNLOADERS
    try:
        return resolved_downloaders[source_name]
    except KeyError as exc:
        valid_sources = ", ".join(sorted(resolved_downloaders))
        raise RawOrchestratorError(
            f"unknown raw source: {source_name}. valid sources: {valid_sources}"
        ) from exc


def download_source_period(
    source_name: str,
    period: str,
    *,
    source_options: Mapping[str, Any] | None = None,
    downloaders: Mapping[str, DownloadFunction] | None = None,
) -> SourcePeriodDownload:
    validated_period = validate_period(period)
    downloader = get_downloader(source_name, downloaders)
    options = dict(source_options or {})
    return downloader(validated_period, **options)


def refresh_source_period(
    source_name: str,
    period: str,
    *,
    engine: Engine | None = None,
    force: bool = False,
    source_options: Mapping[str, Any] | None = None,
    downloaders: Mapping[str, DownloadFunction] | None = None,
    writer: RawWriterFunction = raw_writer.write_source_period_download,
) -> RawRefreshResult:
    result, _download = _refresh_source_period(
        source_name,
        period,
        engine=engine,
        force=force,
        source_options=source_options,
        downloaders=downloaders,
        writer=writer,
    )
    return result


def _refresh_source_period(
    source_name: str,
    period: str,
    *,
    engine: Engine | None,
    force: bool,
    source_options: Mapping[str, Any] | None,
    downloaders: Mapping[str, DownloadFunction] | None,
    writer: RawWriterFunction,
) -> tuple[RawRefreshResult, SourcePeriodDownload | None]:
    validated_period = validate_period(period)
    db_engine = engine or get_engine()

    if not force:
        existing_row_count = source_period_success_row_count(
            source_name,
            validated_period,
            engine=db_engine,
        )
        if existing_row_count is not None:
            return (
                RawRefreshResult(
                    source_name=source_name,
                    period=validated_period,
                    status="skipped_existing",
                    row_count=existing_row_count,
                ),
                None,
            )

    download = download_source_period(
        source_name,
        validated_period,
        source_options=source_options,
        downloaders=downloaders,
    )
    write_result = writer(download, engine=db_engine, force=force)
    status: RawRefreshStatus
    if write_result.status == "written":
        status = "downloaded_written"
    else:
        status = "downloaded_skipped"

    return (
        RawRefreshResult(
            source_name=download.source_name,
            period=download.period,
            status=status,
            row_count=write_result.row_count,
        ),
        download,
    )


def source_options_for(
    source_options: Mapping[str, Mapping[str, Any]] | None,
    source_name: str,
) -> dict[str, Any]:
    if not source_options:
        return {}
    return dict(source_options.get(source_name, {}))


def refresh_raw_period(
    period: str,
    *,
    sources: Sequence[str] | None = None,
    engine: Engine | None = None,
    force: bool = False,
    source_options: Mapping[str, Mapping[str, Any]] | None = None,
    downloaders: Mapping[str, DownloadFunction] | None = None,
    writer: RawWriterFunction = raw_writer.write_source_period_download,
) -> tuple[RawRefreshResult, ...]:
    validated_period = validate_period(period)
    db_engine = engine or get_engine()
    resolved_sources = tuple(sources or DEFAULT_RAW_SOURCES)
    results: list[RawRefreshResult] = []

    for source_name in resolved_sources:
        options = source_options_for(source_options, source_name)

        result, _download = _refresh_source_period(
            source_name,
            validated_period,
            engine=db_engine,
            force=force,
            source_options=options,
            downloaders=downloaders,
            writer=writer,
        )
        results.append(result)

    return tuple(results)


def refresh_raw_range(
    start_period: str,
    end_period: str,
    *,
    sources: Sequence[str] | None = None,
    engine: Engine | None = None,
    force: bool = False,
    source_options: Mapping[str, Mapping[str, Any]] | None = None,
    downloaders: Mapping[str, DownloadFunction] | None = None,
    writer: RawWriterFunction = raw_writer.write_source_period_download,
) -> tuple[RawRefreshResult, ...]:
    db_engine = engine or get_engine()
    results: list[RawRefreshResult] = []
    for period in iter_month_periods(start_period, end_period):
        results.extend(
            refresh_raw_period(
                period,
                sources=sources,
                engine=db_engine,
                force=force,
                source_options=source_options,
                downloaders=downloaders,
                writer=writer,
            )
        )
    return tuple(results)
