from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TextIO

from sqlalchemy.engine import Engine

from rural_basic_income.db.connection import get_engine
from rural_basic_income.worker import clean_orchestrator, raw_orchestrator

RawRangeRunner = Callable[..., tuple[raw_orchestrator.RawRefreshResult, ...]]
CleanRunner = Callable[..., tuple[clean_orchestrator.CleanDatasetResult, ...]]
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerUpdateResult:
    raw_results: tuple[raw_orchestrator.RawRefreshResult, ...]
    clean_results: tuple[clean_orchestrator.CleanDatasetResult, ...]


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
            f"{result.sql_file.name} statements={result.statement_count}",
            file=output,
        )


def run_update(
    *,
    start_period: str,
    end_period: str,
    sources: Sequence[str] | None = None,
    datasets: Sequence[str] | None = None,
    force: bool = False,
    engine: Engine | None = None,
    raw_runner: RawRangeRunner = raw_orchestrator.refresh_raw_range,
    clean_runner: CleanRunner = clean_orchestrator.run_clean_datasets,
    output: TextIO = sys.stdout,
) -> WorkerUpdateResult:
    db_engine = engine or get_engine()

    LOGGER.info(
        "worker update start start_period=%s end_period=%s sources=%s "
        "datasets=%s force=%s",
        start_period,
        end_period,
        tuple(sources) if sources is not None else raw_orchestrator.DEFAULT_RAW_SOURCES,
        tuple(datasets)
        if datasets is not None
        else clean_orchestrator.DEFAULT_CLEAN_DATASETS,
        force,
    )
    raw_results = raw_runner(
        start_period,
        end_period,
        sources=sources,
        engine=db_engine,
        force=force,
    )
    print_raw_results(raw_results, output=output)

    clean_results = clean_runner(
        datasets,
        engine=db_engine,
    )
    print_clean_results(clean_results, output=output)
    LOGGER.info(
        "worker update complete raw_results=%d clean_results=%d",
        len(raw_results),
        len(clean_results),
    )

    return WorkerUpdateResult(
        raw_results=tuple(raw_results),
        clean_results=tuple(clean_results),
    )


def run_update_command(args: argparse.Namespace) -> int:
    sources = split_option_values(args.sources)
    datasets = split_option_values(args.datasets)
    run_update(
        start_period=args.start_period,
        end_period=args.end_period,
        sources=sources,
        datasets=datasets,
        force=args.force,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rbi-worker",
        description="Run Rural Basic Income worker jobs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    update_parser = subparsers.add_parser(
        "update",
        help="download raw data and rebuild clean data for a period range",
    )
    update_parser.add_argument(
        "--start-period",
        required=True,
        help="first monthly period to refresh, formatted as YYYYMM",
    )
    update_parser.add_argument(
        "--end-period",
        required=True,
        help="last monthly period to refresh, formatted as YYYYMM",
    )
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
    update_parser.add_argument(
        "--force",
        action="store_true",
        help="redownload and replace raw source-period data even if already successful",
    )
    update_parser.add_argument(
        "--log-level",
        default="INFO",
        help="worker log level for stdout/stderr logs. Default: INFO",
    )
    update_parser.set_defaults(func=run_update_command)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        configure_logging(args.log_level)
        return args.func(args)
    except (
        ValueError,
        raw_orchestrator.RawOrchestratorError,
        clean_orchestrator.CleanOrchestratorError,
    ) as exc:
        parser.exit(2, f"rbi-worker: error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
