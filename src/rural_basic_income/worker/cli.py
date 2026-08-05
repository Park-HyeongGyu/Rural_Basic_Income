from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from sqlalchemy import text
from sqlalchemy.engine import Engine

from rural_basic_income.db.connection import dispose_engine, get_engine
from rural_basic_income.worker import clean_orchestrator
from rural_basic_income.worker import export as csv_export
from rural_basic_income.worker import raw_orchestrator
from rural_basic_income.worker.importers import living_population

RawRangeRunner = Callable[..., tuple[raw_orchestrator.RawRefreshResult, ...]]
RawLatestRunner = Callable[..., tuple[raw_orchestrator.RawRefreshResult, ...]]
CleanRunner = Callable[..., tuple[clean_orchestrator.CleanDatasetResult, ...]]
ExportRunner = Callable[..., csv_export.ExportRunResult]
LivingPopulationImporter = Callable[..., living_population.LivingPopulationImportResult]
LOGGER = logging.getLogger(__name__)
UPDATE_LOCK_KEY = "rural_basic_income.update"


class WorkerCliError(RuntimeError):
    """Raised when a worker CLI request is invalid or cannot start."""


@dataclass(frozen=True)
class WorkerUpdateResult:
    raw_results: tuple[raw_orchestrator.RawRefreshResult, ...]
    clean_results: tuple[clean_orchestrator.CleanDatasetResult, ...]
    export_result: csv_export.ExportRunResult | None = None


@dataclass(frozen=True)
class WorkerStatusResult:
    source_statuses: tuple[tuple[str, str | None], ...]
    living_population_status: living_population.LivingPopulationImportStatus


@dataclass(frozen=True)
class WorkerImportResult:
    import_result: living_population.LivingPopulationImportResult
    export_result: csv_export.ExportRunResult | None = None


def split_option_values(values: Sequence[str] | None) -> tuple[str, ...] | None:
    if not values:
        return None

    parsed_values = []
    for value in values:
        for item in value.split(","):
            stripped_item = item.strip()
            if stripped_item:
                parsed_values.append(stripped_item)

    if not parsed_values:
        return None
    return tuple(parsed_values)


def format_available(values: Sequence[str]) -> str:
    return ", ".join(values)


def configure_logging(level_name: str = "INFO") -> None:
    log_level = getattr(logging, level_name.upper(), None)
    if not isinstance(log_level, int):
        raise ValueError(f"unknown log level: {level_name}")

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


def print_raw_results(
    results: Sequence[raw_orchestrator.RawRefreshResult],
    *,
    output: TextIO,
) -> None:
    print("raw:", file=output)
    for result in results:
        print(
            f"  {result.period} {result.source_name}: "
            f"{result.status} rows={result.row_count}",
            file=output,
        )


def print_clean_results(
    results: Sequence[clean_orchestrator.CleanDatasetResult],
    *,
    output: TextIO,
) -> None:
    print("clean:", file=output)
    for result in results:
        print(
            f"  {result.dataset_name}: "
            f"{result.sql_file.name} statements={result.statement_count} "
            f"affected_rows={result.affected_row_count} "
            f"revision={result.revision if result.revision is not None else 'unknown'} "
            f"revision_changed={result.revision_changed}",
            file=output,
        )


def print_export_results(
    result: csv_export.ExportRunResult | None,
    *,
    output: TextIO,
) -> None:
    print("export:", file=output)
    if result is None:
        print("  skipped: no data changes and export files exist", file=output)
        return

    for format_name, format_result in (
        ("csv", result.csv),
        ("dta", result.dta),
    ):
        print(f"  {format_name}: {format_result.export_dir}", file=output)
        for table in format_result.tables:
            print(
                f"    {table.schema_name}.{table.table_name}: "
                f"{table.file_path.name} rows={table.row_count}",
                file=output,
            )


def print_living_population_import_result(
    result: living_population.LivingPopulationImportResult,
    *,
    output: TextIO,
) -> None:
    print("import:", file=output)
    print(
        f"  {result.source_name}: {result.raw_status} "
        f"periods={result.periods[0]}-{result.periods[-1]} "
        f"raw_rows={result.raw_row_count} sha256={result.sha256[:12]}",
        file=output,
    )
    if result.clean_results:
        print_clean_results(result.clean_results, output=output)


def print_living_population_status(
    status: living_population.LivingPopulationImportStatus,
    *,
    output: TextIO,
) -> None:
    print("manual_imports:", file=output)
    if not status.exists:
        print("  living_population: last_import=none", file=output)
        return
    print(
        "  living_population: "
        f"status={status.status} "
        f"periods={status.min_period}-{status.max_period} "
        f"period_count={status.period_count} "
        f"raw_rows={status.raw_row_count} "
        f"file={status.original_filename}",
        file=output,
    )


def raw_results_have_writes(
    results: Sequence[raw_orchestrator.RawRefreshResult],
) -> bool:
    return any(result.status == "downloaded_written" for result in results)


def clean_results_have_changes(
    results: Sequence[clean_orchestrator.CleanDatasetResult],
) -> bool:
    return any(
        result.affected_row_count > 0 or result.revision_changed
        for result in results
    )


def export_dir_has_files(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(
        child.is_file() and not child.name.startswith(".")
        for child in path.iterdir()
    )


def export_outputs_missing(
    *,
    export_csv_dir: str | None = None,
    export_dta_dir: str | None = None,
) -> bool:
    csv_dir = csv_export.resolve_export_csv_dir(export_csv_dir)
    dta_dir = csv_export.resolve_export_dta_dir(export_dta_dir)
    return not export_dir_has_files(csv_dir) or not export_dir_has_files(dta_dir)


def should_run_export(
    *,
    raw_results: Sequence[raw_orchestrator.RawRefreshResult] = (),
    clean_results: Sequence[clean_orchestrator.CleanDatasetResult] = (),
    export_csv_dir: str | None = None,
    export_dta_dir: str | None = None,
) -> bool:
    return (
        raw_results_have_writes(raw_results)
        or clean_results_have_changes(clean_results)
        or export_outputs_missing(
            export_csv_dir=export_csv_dir,
            export_dta_dir=export_dta_dir,
        )
    )


def scalar_bool(result) -> bool:
    if hasattr(result, "scalar_one"):
        return bool(result.scalar_one())
    if hasattr(result, "scalar_one_or_none"):
        return bool(result.scalar_one_or_none())
    return bool(result)


def run_with_update_lock(
    engine: Engine,
    callback: Callable[[], WorkerUpdateResult],
) -> WorkerUpdateResult:
    with engine.connect() as connection:
        locked = scalar_bool(
            connection.execute(
                text("SELECT pg_try_advisory_lock(hashtext(:lock_key))"),
                {"lock_key": UPDATE_LOCK_KEY},
            )
        )
        if not locked:
            raise WorkerCliError("another rbi update is already running")

        LOGGER.info("update lock acquired")
        try:
            return callback()
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:lock_key))"),
                {"lock_key": UPDATE_LOCK_KEY},
            )
            LOGGER.info("update lock released")


def run_update(
    *,
    start_period: str,
    end_period: str,
    sources: Sequence[str] | None = None,
    datasets: Sequence[str] | None = None,
    force_raw: bool = False,
    engine: Engine | None = None,
    raw_runner: RawRangeRunner = raw_orchestrator.refresh_raw_range,
    clean_runner: CleanRunner = clean_orchestrator.run_clean_datasets,
    export_requested: bool = False,
    export_csv_dir: str | None = None,
    export_dta_dir: str | None = None,
    export_runner: ExportRunner = csv_export.export_all,
    output: TextIO = sys.stdout,
    lock_update: bool = True,
) -> WorkerUpdateResult:
    db_engine = engine or get_engine()

    def locked_update() -> WorkerUpdateResult:
        LOGGER.info(
            "worker update start start_period=%s end_period=%s sources=%s "
            "datasets=%s force_raw=%s",
            start_period,
            end_period,
            tuple(sources)
            if sources is not None
            else raw_orchestrator.DEFAULT_RAW_SOURCES,
            tuple(datasets)
            if datasets is not None
            else clean_orchestrator.DEFAULT_CLEAN_DATASETS,
            force_raw,
        )
        raw_results = raw_runner(
            start_period,
            end_period,
            sources=sources,
            engine=db_engine,
            force=force_raw,
        )
        print_raw_results(raw_results, output=output)

        clean_results = clean_runner(
            datasets,
            engine=db_engine,
        )
        print_clean_results(clean_results, output=output)
        export_result = None
        if export_requested:
            if should_run_export(
                raw_results=raw_results,
                clean_results=clean_results,
                export_csv_dir=export_csv_dir,
                export_dta_dir=export_dta_dir,
            ):
                export_result = export_runner(
                    export_csv_dir=export_csv_dir,
                    export_dta_dir=export_dta_dir,
                    engine=db_engine,
                )
            print_export_results(export_result, output=output)
        LOGGER.info(
            "worker update complete raw_results=%d clean_results=%d "
            "exported=%s",
            len(raw_results),
            len(clean_results),
            export_result is not None,
        )

        return WorkerUpdateResult(
            raw_results=tuple(raw_results),
            clean_results=tuple(clean_results),
            export_result=export_result,
        )

    if not lock_update:
        return locked_update()
    return run_with_update_lock(db_engine, locked_update)


def run_update_latest(
    *,
    sources: Sequence[str] | None = None,
    datasets: Sequence[str] | None = None,
    fallback_start_period: str | None = None,
    end_period: str | None = None,
    force_raw: bool = False,
    engine: Engine | None = None,
    raw_latest_runner: RawLatestRunner = raw_orchestrator.refresh_raw_latest,
    clean_runner: CleanRunner = clean_orchestrator.run_clean_datasets,
    export_requested: bool = False,
    export_csv_dir: str | None = None,
    export_dta_dir: str | None = None,
    export_runner: ExportRunner = csv_export.export_all,
    output: TextIO = sys.stdout,
    lock_update: bool = True,
) -> WorkerUpdateResult:
    db_engine = engine or get_engine()

    def locked_update() -> WorkerUpdateResult:
        LOGGER.info(
            "worker update latest start sources=%s datasets=%s "
            "fallback_start_period=%s end_period=%s force_raw=%s",
            tuple(sources)
            if sources is not None
            else raw_orchestrator.DEFAULT_RAW_SOURCES,
            tuple(datasets)
            if datasets is not None
            else clean_orchestrator.DEFAULT_CLEAN_DATASETS,
            fallback_start_period or raw_orchestrator.default_latest_start_period(),
            end_period,
            force_raw,
        )
        raw_results = raw_latest_runner(
            sources=sources,
            engine=db_engine,
            force=force_raw,
            fallback_start_period=(
                fallback_start_period
                or raw_orchestrator.default_latest_start_period()
            ),
            end_period=end_period,
        )
        print_raw_results(raw_results, output=output)

        clean_results = clean_runner(
            datasets,
            engine=db_engine,
        )
        print_clean_results(clean_results, output=output)
        export_result = None
        if export_requested:
            if should_run_export(
                raw_results=raw_results,
                clean_results=clean_results,
                export_csv_dir=export_csv_dir,
                export_dta_dir=export_dta_dir,
            ):
                export_result = export_runner(
                    export_csv_dir=export_csv_dir,
                    export_dta_dir=export_dta_dir,
                    engine=db_engine,
                )
            print_export_results(export_result, output=output)
        LOGGER.info(
            "worker update latest complete raw_results=%d clean_results=%d "
            "exported=%s",
            len(raw_results),
            len(clean_results),
            export_result is not None,
        )
        return WorkerUpdateResult(
            raw_results=tuple(raw_results),
            clean_results=tuple(clean_results),
            export_result=export_result,
        )

    if not lock_update:
        return locked_update()
    return run_with_update_lock(db_engine, locked_update)


def run_clean(
    *,
    datasets: Sequence[str] | None = None,
    rebuild: bool = False,
    start_period: str | None = None,
    end_period: str | None = None,
    engine: Engine | None = None,
    clean_runner: CleanRunner = clean_orchestrator.run_clean_datasets,
    export_requested: bool = False,
    export_csv_dir: str | None = None,
    export_dta_dir: str | None = None,
    export_runner: ExportRunner = csv_export.export_all,
    output: TextIO = sys.stdout,
) -> tuple[clean_orchestrator.CleanDatasetResult, ...]:
    db_engine = engine or get_engine()
    clean_results = clean_runner(
        datasets,
        engine=db_engine,
        rebuild=rebuild,
        start_period=start_period,
        end_period=end_period,
    )
    print_clean_results(clean_results, output=output)
    if export_requested:
        export_result = None
        if rebuild or should_run_export(
            clean_results=clean_results,
            export_csv_dir=export_csv_dir,
            export_dta_dir=export_dta_dir,
        ):
            export_result = export_runner(
                export_csv_dir=export_csv_dir,
                export_dta_dir=export_dta_dir,
                engine=db_engine,
            )
        print_export_results(export_result, output=output)
    return tuple(clean_results)


def run_export(
    *,
    export_csv_dir: str | None = None,
    export_dta_dir: str | None = None,
    engine: Engine | None = None,
    export_runner: ExportRunner = csv_export.export_all,
    output: TextIO = sys.stdout,
) -> csv_export.ExportRunResult:
    db_engine = engine or get_engine()
    export_result = export_runner(
        export_csv_dir=export_csv_dir,
        export_dta_dir=export_dta_dir,
        engine=db_engine,
    )
    print_export_results(export_result, output=output)
    return export_result


def run_import_living_population(
    *,
    file_path: str,
    force_raw: bool = False,
    engine: Engine | None = None,
    importer: LivingPopulationImporter = living_population.import_living_population_file,
    export_requested: bool = False,
    export_csv_dir: str | None = None,
    export_dta_dir: str | None = None,
    export_runner: ExportRunner = csv_export.export_all,
    output: TextIO = sys.stdout,
    lock_update: bool = True,
) -> WorkerImportResult:
    db_engine = engine or get_engine()

    def locked_import() -> WorkerImportResult:
        LOGGER.info(
            "worker import living_population start file=%s force_raw=%s",
            file_path,
            force_raw,
        )
        import_result = importer(
            file_path,
            engine=db_engine,
            force_raw=force_raw,
        )
        print_living_population_import_result(import_result, output=output)

        export_result = None
        if export_requested:
            if (
                import_result.raw_changed
                or import_result.clean_changed
                or export_outputs_missing(
                    export_csv_dir=export_csv_dir,
                    export_dta_dir=export_dta_dir,
                )
            ):
                export_result = export_runner(
                    export_csv_dir=export_csv_dir,
                    export_dta_dir=export_dta_dir,
                    engine=db_engine,
                )
            print_export_results(export_result, output=output)

        LOGGER.info(
            "worker import living_population complete raw_status=%s exported=%s",
            import_result.raw_status,
            export_result is not None,
        )
        return WorkerImportResult(
            import_result=import_result,
            export_result=export_result,
        )

    if not lock_update:
        return locked_import()
    return run_with_update_lock(db_engine, locked_import)


def run_status(
    *,
    sources: Sequence[str] | None = None,
    engine: Engine | None = None,
    output: TextIO = sys.stdout,
) -> WorkerStatusResult:
    db_engine = engine or get_engine()
    resolved_sources = tuple(sources or raw_orchestrator.DEFAULT_RAW_SOURCES)
    with db_engine.connect() as connection:
        statuses = tuple(
            (
                source_name,
                raw_orchestrator.source_last_success_period(
                    source_name,
                    engine=db_engine,
                ),
            )
            for source_name in resolved_sources
        )
        living_status = living_population.fetch_latest_import_status(connection)
    print("status:", file=output)
    for source_name, last_success in statuses:
        print(
            f"  {source_name}: last_success={last_success or 'none'}",
            file=output,
        )
    print_living_population_status(living_status, output=output)
    return WorkerStatusResult(
        source_statuses=statuses,
        living_population_status=living_status,
    )


def run_update_command(args: argparse.Namespace) -> int:
    sources = split_option_values(args.sources)
    datasets = split_option_values(args.datasets)
    if args.latest:
        run_update_latest(
            sources=sources,
            datasets=datasets,
            fallback_start_period=args.start_period,
            end_period=args.end_period,
            force_raw=args.force_raw,
            export_requested=args.export,
            export_csv_dir=args.export_csv_dir,
            export_dta_dir=args.export_dta_dir,
        )
    else:
        if not args.start_period or not args.end_period:
            raise WorkerCliError(
                "update requires --start-period and --end-period unless --latest is set"
            )
        run_update(
            start_period=args.start_period,
            end_period=args.end_period,
            sources=sources,
            datasets=datasets,
            force_raw=args.force_raw,
            export_requested=args.export,
            export_csv_dir=args.export_csv_dir,
            export_dta_dir=args.export_dta_dir,
        )
    return 0


def run_clean_command(args: argparse.Namespace) -> int:
    datasets = split_option_values(args.datasets)
    run_clean(
        datasets=datasets,
        rebuild=args.rebuild,
        start_period=args.start_period,
        end_period=args.end_period,
        export_requested=args.export,
        export_csv_dir=args.export_csv_dir,
        export_dta_dir=args.export_dta_dir,
    )
    return 0


def run_status_command(args: argparse.Namespace) -> int:
    sources = split_option_values(args.sources)
    run_status(sources=sources)
    return 0


def run_export_command(args: argparse.Namespace) -> int:
    run_export(
        export_csv_dir=args.export_csv_dir,
        export_dta_dir=args.export_dta_dir,
    )
    return 0


def run_import_command(args: argparse.Namespace) -> int:
    if args.import_type == "living-population":
        run_import_living_population(
            file_path=args.file,
            force_raw=args.force_raw,
            export_requested=args.export,
            export_csv_dir=args.export_csv_dir,
            export_dta_dir=args.export_dta_dir,
        )
        return 0
    raise WorkerCliError(f"unknown import type: {args.import_type}")


def add_common_source_dataset_options(update_parser: argparse.ArgumentParser) -> None:
    update_parser.add_argument(
        "--sources",
        action="append",
        metavar="SOURCE[,SOURCE...]",
        help=(
            "raw sources to refresh; may be comma-separated or repeated. "
            f"Default: {format_available(raw_orchestrator.DEFAULT_RAW_SOURCES)}"
        ),
    )
    update_parser.add_argument(
        "--datasets",
        action="append",
        metavar="DATASET[,DATASET...]",
        help=(
            "clean datasets to run; may be comma-separated or repeated. "
            f"Default: {format_available(clean_orchestrator.DEFAULT_CLEAN_DATASETS)}"
        ),
    )


def build_parser(prog: str = "rbi") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Run Rural Basic Income worker jobs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    update_parser = subparsers.add_parser(
        "update",
        help="download raw data and run clean SQL",
    )
    update_parser.add_argument(
        "--latest",
        action="store_true",
        help=(
            "scan every source-period from --start-period or the default "
            "latest start through the current month, skipping only periods "
            "already marked successful. Default start comes from "
            "RBI_LATEST_START_PERIOD"
        ),
    )
    update_parser.add_argument(
        "--start-period",
        help=(
            "first monthly period to refresh, formatted as YYYYMM. With "
            "--latest, this is the first period scanned for every source"
        ),
    )
    update_parser.add_argument(
        "--end-period",
        help=(
            "last monthly period to refresh, formatted as YYYYMM. With "
            "--latest, overrides the current-month probe limit"
        ),
    )
    add_common_source_dataset_options(update_parser)
    update_parser.add_argument(
        "--force-raw",
        action="store_true",
        dest="force_raw",
        help=(
            "redownload and atomically replace raw source-period data even if "
            "already successful; this does not rebuild existing clean rows"
        ),
    )
    update_parser.add_argument(
        "--force",
        action="store_true",
        dest="force_raw",
        help=argparse.SUPPRESS,
    )
    update_parser.add_argument(
        "--export",
        action="store_true",
        help=(
            "export raw and clean CSV and DTA files after the update only "
            "when raw data was written"
        ),
    )
    update_parser.add_argument(
        "--export-csv-dir",
        help="directory for flat raw_*.csv and clean_*.csv files",
    )
    update_parser.add_argument(
        "--export-dta-dir",
        help="directory for flat raw_*.dta and clean_*.dta files",
    )
    update_parser.add_argument(
        "--log-level",
        default="INFO",
        help="worker log level for stdout/stderr logs. Default: INFO",
    )
    update_parser.set_defaults(func=run_update_command)

    clean_parser = subparsers.add_parser(
        "clean",
        help="run clean SQL files without downloading raw data",
    )
    clean_parser.add_argument(
        "--datasets",
        action="append",
        metavar="DATASET[,DATASET...]",
        help=(
            "clean datasets to run; may be comma-separated or repeated. "
            f"Default: {format_available(clean_orchestrator.DEFAULT_CLEAN_DATASETS)}"
        ),
    )
    clean_parser.add_argument(
        "--rebuild",
        action="store_true",
        help=(
            "delete and rebuild existing clean rows for the selected period "
            "range inside each dataset SQL transaction"
        ),
    )
    clean_parser.add_argument(
        "--start-period",
        help="first monthly clean period to rebuild, formatted as YYYYMM",
    )
    clean_parser.add_argument(
        "--end-period",
        help="last monthly clean period to rebuild, formatted as YYYYMM",
    )
    clean_parser.add_argument(
        "--log-level",
        default="INFO",
        help="worker log level for stdout/stderr logs. Default: INFO",
    )
    clean_parser.add_argument(
        "--export",
        action="store_true",
        help="export raw and clean CSV and DTA files after an explicit clean rebuild",
    )
    clean_parser.add_argument(
        "--export-csv-dir",
        help="directory for flat raw_*.csv and clean_*.csv files",
    )
    clean_parser.add_argument(
        "--export-dta-dir",
        help="directory for flat raw_*.dta and clean_*.dta files",
    )
    clean_parser.set_defaults(func=run_clean_command)

    status_parser = subparsers.add_parser(
        "status",
        help="print source download status summary",
    )
    status_parser.add_argument(
        "--sources",
        action="append",
        metavar="SOURCE[,SOURCE...]",
        help=(
            "raw sources to inspect; may be comma-separated or repeated. "
            f"Default: {format_available(raw_orchestrator.DEFAULT_RAW_SOURCES)}"
        ),
    )
    status_parser.add_argument(
        "--log-level",
        default="INFO",
        help="worker log level for stdout/stderr logs. Default: INFO",
    )
    status_parser.set_defaults(func=run_status_command)

    export_parser = subparsers.add_parser(
        "export",
        help="export current raw and clean tables to flat CSV and DTA files",
    )
    export_parser.add_argument(
        "--export-csv-dir",
        help="directory for flat raw_*.csv and clean_*.csv files",
    )
    export_parser.add_argument(
        "--export-dta-dir",
        help="directory for flat raw_*.dta and clean_*.dta files",
    )
    export_parser.add_argument(
        "--log-level",
        default="INFO",
        help="worker log level for stdout/stderr logs. Default: INFO",
    )
    export_parser.set_defaults(func=run_export_command)

    import_parser = subparsers.add_parser(
        "import",
        help="import manually downloaded source files",
    )
    import_subparsers = import_parser.add_subparsers(
        dest="import_type",
        required=True,
    )
    living_parser = import_subparsers.add_parser(
        "living-population",
        help="import a manually downloaded living population CSV",
    )
    living_parser.add_argument(
        "--file",
        required=True,
        help="path to the living population CSV inside the container",
    )
    living_parser.add_argument(
        "--force-raw",
        action="store_true",
        dest="force_raw",
        help="replace raw rows even if the same file hash was already imported",
    )
    living_parser.add_argument(
        "--export",
        action="store_true",
        help="export raw and clean CSV and DTA files after import",
    )
    living_parser.add_argument(
        "--export-csv-dir",
        help="directory for flat raw_*.csv and clean_*.csv files",
    )
    living_parser.add_argument(
        "--export-dta-dir",
        help="directory for flat raw_*.dta and clean_*.dta files",
    )
    living_parser.add_argument(
        "--log-level",
        default="INFO",
        help="worker log level for stdout/stderr logs. Default: INFO",
    )
    living_parser.set_defaults(func=run_import_command)

    return parser


def main(argv: Sequence[str] | None = None, *, prog: str = "rbi") -> int:
    parsed_argv = tuple(sys.argv[1:] if argv is None else argv)
    original_argv0 = sys.argv[0]
    sys.argv[0] = prog
    parser = build_parser(prog=prog)
    args = parser.parse_args(parsed_argv)
    try:
        configure_logging(args.log_level)
        return args.func(args)
    except (
        ValueError,
        WorkerCliError,
        raw_orchestrator.RawOrchestratorError,
        clean_orchestrator.CleanOrchestratorError,
        csv_export.ExportError,
        living_population.LivingPopulationImportError,
    ) as exc:
        parser.exit(2, f"rbi: error: {exc}\n")
    finally:
        dispose_engine()
        sys.argv[0] = original_argv0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
