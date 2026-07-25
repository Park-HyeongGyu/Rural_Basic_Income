from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

from rural_basic_income.db.connection import get_engine
from rural_basic_income.worker.download import (
    SourcePeriodDownload,
    SourcePeriodUnavailable,
)
from rural_basic_income.worker.periods import iter_month_periods, validate_period
from rural_basic_income.worker import raw_writer
from rural_basic_income.worker.sources import (
    electricity,
    household,
    local_currency,
    mover,
    population,
)

LOGGER = logging.getLogger(__name__)

RawRefreshStatus = Literal[
    "skipped_existing",
    "skipped_unavailable",
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

    @property
    def unavailable(self) -> bool:
        return self.status == "skipped_unavailable"


@dataclass(frozen=True)
class RawSourceMetadata:
    source_name: str
    source_name_kor: str
    source_table_id: str


SOURCE_METADATA: dict[str, RawSourceMetadata] = {
    "household": RawSourceMetadata(
        source_name=household.SPEC.source_name,
        source_name_kor=household.SPEC.source_name_kor,
        source_table_id=household.SPEC.source_table_id,
    ),
    "population": RawSourceMetadata(
        source_name=population.SPEC.source_name,
        source_name_kor=population.SPEC.source_name_kor,
        source_table_id=population.SPEC.source_table_id,
    ),
    "mover": RawSourceMetadata(
        source_name=mover.SPEC.source_name,
        source_name_kor=mover.SPEC.source_name_kor,
        source_table_id=mover.SPEC.source_table_id,
    ),
    "electricity": RawSourceMetadata(
        source_name=electricity.SOURCE_NAME,
        source_name_kor=electricity.SOURCE_NAME_KOR,
        source_table_id=electricity.SOURCE_TABLE_ID,
    ),
    "local_currency": RawSourceMetadata(
        source_name=local_currency.SOURCE_NAME,
        source_name_kor=local_currency.SOURCE_NAME_KOR,
        source_table_id=local_currency.SOURCE_TABLE_ID,
    ),
}


def source_metadata_for(source_name: str) -> RawSourceMetadata:
    return SOURCE_METADATA.get(
        source_name,
        RawSourceMetadata(
            source_name=source_name,
            source_name_kor=source_name,
            source_table_id="",
        ),
    )


def source_period_unavailable_message(exc: BaseException) -> str | None:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, SourcePeriodUnavailable):
            return str(current)
        current = current.__cause__ or current.__context__
    return None


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
    LOGGER.info(
        "raw download start source=%s period=%s options=%s",
        source_name,
        validated_period,
        sorted(options),
    )
    try:
        download = downloader(validated_period, **options)
    except Exception as exc:
        unavailable_message = source_period_unavailable_message(exc)
        if unavailable_message:
            LOGGER.warning(
                "raw download unavailable source=%s period=%s message=%s",
                source_name,
                validated_period,
                unavailable_message,
            )
        else:
            LOGGER.exception(
                "raw download failed source=%s period=%s",
                source_name,
                validated_period,
            )
        raise

    LOGGER.info(
        "raw download complete source=%s period=%s raw_table=%s "
        "payload_chunks=%d payload_rows=%d raw_rows=%d",
        download.source_name,
        download.period,
        download.raw_table,
        len(download.payload_chunks),
        download.payload_row_count,
        download.raw_row_count,
    )
    return download


def refresh_source_period(
    source_name: str,
    period: str,
    *,
    engine: Engine | None = None,
    force: bool = False,
    source_options: Mapping[str, Any] | None = None,
    downloaders: Mapping[str, DownloadFunction] | None = None,
    writer: RawWriterFunction = raw_writer.write_source_period_download,
    allow_unavailable: bool = True,
) -> RawRefreshResult:
    result, _download = _refresh_source_period(
        source_name,
        period,
        engine=engine,
        force=force,
        source_options=source_options,
        downloaders=downloaders,
        writer=writer,
        allow_unavailable=allow_unavailable,
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
    allow_unavailable: bool,
) -> tuple[RawRefreshResult, SourcePeriodDownload | None]:
    validated_period = validate_period(period)
    db_engine = engine or get_engine()

    LOGGER.info(
        "raw refresh source-period start source=%s period=%s force=%s",
        source_name,
        validated_period,
        force,
    )
    if not force:
        existing_row_count = source_period_success_row_count(
            source_name,
            validated_period,
            engine=db_engine,
        )
        if existing_row_count is not None:
            LOGGER.info(
                "raw refresh skipped existing source=%s period=%s rows=%d",
                source_name,
                validated_period,
                existing_row_count,
            )
            return (
                RawRefreshResult(
                    source_name=source_name,
                    period=validated_period,
                    status="skipped_existing",
                    row_count=existing_row_count,
                ),
                None,
            )

    try:
        download = download_source_period(
            source_name,
            validated_period,
            source_options=source_options,
            downloaders=downloaders,
        )
    except Exception as exc:
        unavailable_message = source_period_unavailable_message(exc)
        if allow_unavailable and unavailable_message:
            return mark_unavailable_source_period(
                source_name=source_name,
                period=validated_period,
                message=unavailable_message,
                engine=db_engine,
            )
        raise

    if allow_unavailable and download.raw_row_count == 0:
        return mark_unavailable_source_period(
            source_name=source_name,
            period=validated_period,
            message=(
                f"{download.source_name} source returned no rows "
                f"for period {validated_period}"
            ),
            engine=db_engine,
        )

    write_result = writer(download, engine=db_engine, force=force)
    status: RawRefreshStatus
    if write_result.status == "written":
        status = "downloaded_written"
    else:
        status = "downloaded_skipped"

    LOGGER.info(
        "raw refresh source-period complete source=%s period=%s status=%s rows=%d",
        download.source_name,
        download.period,
        status,
        write_result.row_count,
    )
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


def mark_unavailable_source_period(
    *,
    source_name: str,
    period: str,
    message: str,
    engine: Engine,
) -> tuple[RawRefreshResult, None]:
    metadata = source_metadata_for(source_name)
    raw_writer.mark_source_period_unavailable(
        source_name=metadata.source_name,
        source_name_kor=metadata.source_name_kor,
        source_table_id=metadata.source_table_id,
        period=period,
        error_message=message,
        engine=engine,
    )
    LOGGER.warning(
        "raw refresh skipped unavailable source=%s period=%s message=%s",
        source_name,
        period,
        message,
    )
    return (
        RawRefreshResult(
            source_name=source_name,
            period=period,
            status="skipped_unavailable",
            row_count=0,
        ),
        None,
    )


def refresh_raw_period(
    period: str,
    *,
    sources: Sequence[str] | None = None,
    engine: Engine | None = None,
    force: bool = False,
    source_options: Mapping[str, Mapping[str, Any]] | None = None,
    downloaders: Mapping[str, DownloadFunction] | None = None,
    writer: RawWriterFunction = raw_writer.write_source_period_download,
    allow_unavailable: bool = True,
) -> tuple[RawRefreshResult, ...]:
    validated_period = validate_period(period)
    db_engine = engine or get_engine()
    resolved_sources = tuple(sources or DEFAULT_RAW_SOURCES)
    results: list[RawRefreshResult] = []

    LOGGER.info(
        "raw refresh period start period=%s sources=%s force=%s",
        validated_period,
        resolved_sources,
        force,
    )
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
            allow_unavailable=allow_unavailable,
        )
        results.append(result)

    LOGGER.info(
        "raw refresh period complete period=%s results=%d",
        validated_period,
        len(results),
    )
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
    continue_on_unavailable: bool = True,
) -> tuple[RawRefreshResult, ...]:
    db_engine = engine or get_engine()
    results: list[RawRefreshResult] = []
    validated_end_period = validate_period(end_period)
    LOGGER.info(
        "raw refresh range start start_period=%s end_period=%s sources=%s "
        "force=%s",
        start_period,
        end_period,
        tuple(sources or DEFAULT_RAW_SOURCES),
        force,
    )
    for period in iter_month_periods(start_period, validated_end_period):
        results.extend(
            refresh_raw_period(
                period,
                sources=sources,
                engine=db_engine,
                force=force,
                source_options=source_options,
                downloaders=downloaders,
                writer=writer,
                allow_unavailable=continue_on_unavailable,
            )
        )
    LOGGER.info(
        "raw refresh range complete start_period=%s end_period=%s results=%d",
        start_period,
        end_period,
        len(results),
    )
    return tuple(results)
