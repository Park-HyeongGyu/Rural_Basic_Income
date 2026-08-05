from __future__ import annotations

import csv
import hashlib
import logging
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection, Engine

from rural_basic_income.db.connection import get_engine
from rural_basic_income.worker import clean_orchestrator
from rural_basic_income.worker.periods import validate_period

SOURCE_NAME = "living_population"
SOURCE_NAME_KOR = "생활인구"
RAW_TABLE = "living_population"
RAW_COLUMNS = (
    "period",
    "source_file_name",
    "source_file_hash",
    "source_row_number",
    "region_sido_raw",
    "region_sigungu_raw",
    "region_type_raw",
    "population_type_raw",
    "age_raw",
    "value_raw",
    "imported_at",
)
IDENTIFIER_COLUMNS = ("시도명", "시군구명", "구분", "생활인구")
KNOWN_AGE_VALUES = (
    "계",
    "20세 미만",
    "20대",
    "30대",
    "40대",
    "50대",
    "60대",
    "70세 이상",
)
KNOWN_POPULATION_TYPES = ("계", "주민등록인구", "체류인구", "외국인")
KNOWN_REGION_TYPES = ("감소", "관심")
CleanRunner = Callable[..., tuple[clean_orchestrator.CleanDatasetResult, ...]]
LOGGER = logging.getLogger(__name__)


class LivingPopulationImportError(RuntimeError):
    """Raised when a living population file cannot be imported."""


@dataclass(frozen=True)
class ParsedLivingPopulationFile:
    path: Path
    sha256: str
    file_size_bytes: int
    periods: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    source_row_count: int

    @property
    def min_period(self) -> str:
        return min(self.periods)

    @property
    def max_period(self) -> str:
        return max(self.periods)


@dataclass(frozen=True)
class LivingPopulationImportResult:
    source_name: str
    file_path: Path
    sha256: str
    periods: tuple[str, ...]
    raw_row_count: int
    raw_status: str
    clean_results: tuple[clean_orchestrator.CleanDatasetResult, ...]

    @property
    def raw_changed(self) -> bool:
        return self.raw_status in {"raw_committed", "raw_replaced"}

    @property
    def clean_changed(self) -> bool:
        return any(
            result.affected_row_count > 0 or result.revision_changed
            for result in self.clean_results
        )


@dataclass(frozen=True)
class LivingPopulationImportStatus:
    source_name: str = SOURCE_NAME
    status: str | None = None
    original_filename: str | None = None
    min_period: str | None = None
    max_period: str | None = None
    period_count: int | None = None
    raw_row_count: int | None = None
    imported_at: datetime | None = None
    raw_completed_at: datetime | None = None
    clean_completed_at: datetime | None = None

    @property
    def exists(self) -> bool:
        return self.status is not None


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_period_label(label: str) -> str | None:
    cleaned = label.strip()
    if not cleaned:
        return None
    if "." not in cleaned:
        return None
    year, month = cleaned.split(".", 1)
    period = f"{int(year):04d}{int(month):02d}"
    return validate_period(period)


def forward_fill_periods(header: Sequence[str]) -> list[str | None]:
    periods: list[str | None] = []
    current_period: str | None = None
    for value in header:
        parsed_period = normalize_period_label(value) if value.strip() else None
        if parsed_period is not None:
            current_period = parsed_period
        periods.append(current_period)
    return periods


def parse_living_population_csv(path: str | Path) -> ParsedLivingPopulationFile:
    file_path = Path(path)
    if not file_path.is_file():
        raise LivingPopulationImportError(f"living population file not found: {path}")

    sha256 = calculate_sha256(file_path)
    file_size_bytes = file_path.stat().st_size
    imported_at = datetime.now(UTC).isoformat()

    with file_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.reader(csv_file)
        try:
            period_header = next(reader)
            age_header = next(reader)
        except StopIteration as exc:
            raise LivingPopulationImportError(
                "living population file must contain two header rows"
            ) from exc

        if len(period_header) != len(age_header):
            raise LivingPopulationImportError(
                "living population header rows have different lengths"
            )
        if tuple(age_header[:4]) != IDENTIFIER_COLUMNS:
            raise LivingPopulationImportError(
                "living population identifier columns must be: "
                + ", ".join(IDENTIFIER_COLUMNS)
            )

        periods_by_column = forward_fill_periods(period_header)
        value_columns: list[tuple[int, str, str]] = []
        for index, (period, age) in enumerate(
            zip(periods_by_column, age_header, strict=True)
        ):
            if index < len(IDENTIFIER_COLUMNS):
                continue
            age_value = age.strip()
            if not age_value:
                continue
            if not period:
                raise LivingPopulationImportError(
                    f"invalid living population value header at column {index + 1}"
                )
            if age_value not in KNOWN_AGE_VALUES:
                raise LivingPopulationImportError(
                    f"unknown living population age header: {age_value}"
                )
            value_columns.append((index, period, age_value))

        raw_rows: list[dict[str, str]] = []
        source_row_count = 0
        unique_keys: set[tuple[str, str, str, str, str, str]] = set()
        for source_row_number, source_row in enumerate(reader, start=3):
            if not source_row or all(not item.strip() for item in source_row):
                continue
            if len(source_row) < len(age_header):
                source_row = [*source_row, *([""] * (len(age_header) - len(source_row)))]
            elif len(source_row) > len(age_header):
                if any(item.strip() for item in source_row[len(age_header) :]):
                    raise LivingPopulationImportError(
                        f"unexpected extra values at source row {source_row_number}"
                    )
                source_row = source_row[: len(age_header)]

            region_sido, region_sigungu, region_type, population_type = (
                source_row[0].strip(),
                source_row[1].strip(),
                source_row[2].strip(),
                source_row[3].strip(),
            )
            if not region_sido or not region_sigungu:
                raise LivingPopulationImportError(
                    f"missing region identifier at source row {source_row_number}"
                )
            if region_type not in KNOWN_REGION_TYPES:
                raise LivingPopulationImportError(
                    f"unknown living population region type at row "
                    f"{source_row_number}: {region_type}"
                )
            if population_type not in KNOWN_POPULATION_TYPES:
                raise LivingPopulationImportError(
                    f"unknown living population type at row "
                    f"{source_row_number}: {population_type}"
                )

            source_row_count += 1
            for index, period, age in value_columns:
                value_raw = source_row[index].strip()
                if value_raw not in {"", "*"}:
                    try:
                        float(value_raw.replace(",", ""))
                    except ValueError as exc:
                        raise LivingPopulationImportError(
                            "unexpected living population value token at row "
                            f"{source_row_number}, period={period}, age={age}: "
                            f"{value_raw}"
                        ) from exc

                key = (
                    period,
                    region_sido,
                    region_sigungu,
                    region_type,
                    population_type,
                    age,
                )
                if key in unique_keys:
                    raise LivingPopulationImportError(
                        "duplicate living population cell: "
                        f"{key} at source row {source_row_number}"
                    )
                unique_keys.add(key)
                raw_rows.append(
                    {
                        "period": period,
                        "source_file_name": file_path.name,
                        "source_file_hash": sha256,
                        "source_row_number": str(source_row_number),
                        "region_sido_raw": region_sido,
                        "region_sigungu_raw": region_sigungu,
                        "region_type_raw": region_type,
                        "population_type_raw": population_type,
                        "age_raw": age,
                        "value_raw": value_raw,
                        "imported_at": imported_at,
                    }
                )

    if not raw_rows:
        raise LivingPopulationImportError("living population file has no value cells")

    period_counts = Counter(row["period"] for row in raw_rows)
    periods = tuple(sorted(period_counts))
    return ParsedLivingPopulationFile(
        path=file_path,
        sha256=sha256,
        file_size_bytes=file_size_bytes,
        periods=periods,
        rows=tuple(raw_rows),
        source_row_count=source_row_count,
    )


def ensure_import_tables(connection: Connection) -> None:
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS metadata"))
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS metadata.file_imports (
                id bigserial PRIMARY KEY,
                source_name text NOT NULL,
                sha256 text NOT NULL,
                original_filename text NOT NULL,
                file_size_bytes bigint NOT NULL,
                imported_at timestamptz NOT NULL DEFAULT now(),
                min_period text NOT NULL,
                max_period text NOT NULL,
                period_count integer NOT NULL,
                raw_row_count integer NOT NULL,
                attempt_count integer NOT NULL DEFAULT 1,
                raw_completed_at timestamptz,
                clean_completed_at timestamptz,
                status text NOT NULL,
                error_summary text,
                UNIQUE (source_name, sha256)
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS metadata.file_import_periods (
                file_import_id bigint NOT NULL
                    REFERENCES metadata.file_imports(id) ON DELETE CASCADE,
                period text NOT NULL,
                raw_row_count integer NOT NULL,
                PRIMARY KEY (file_import_id, period)
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS raw.living_population (
                period text NOT NULL,
                source_file_name text NOT NULL,
                source_file_hash text NOT NULL,
                source_row_number integer NOT NULL,
                region_sido_raw text NOT NULL,
                region_sigungu_raw text NOT NULL,
                region_type_raw text NOT NULL,
                population_type_raw text NOT NULL,
                age_raw text NOT NULL,
                value_raw text NOT NULL,
                imported_at timestamptz NOT NULL
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS raw_living_population_key
            ON raw.living_population (
                period,
                region_sido_raw,
                region_sigungu_raw,
                region_type_raw,
                population_type_raw,
                age_raw
            )
            """
        )
    )


def fetch_existing_import_status(
    connection: Connection,
    *,
    sha256: str,
) -> tuple[int, str] | None:
    row = connection.execute(
        text(
            """
            SELECT id, status
            FROM metadata.file_imports
            WHERE source_name = :source_name
              AND sha256 = :sha256
            """
        ),
        {"source_name": SOURCE_NAME, "sha256": sha256},
    ).one_or_none()
    if row is None:
        return None
    return int(row.id), str(row.status)


def file_imports_table_exists(connection: Connection) -> bool:
    return (
        connection.execute(
            text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'metadata'
                  AND table_name = 'file_imports'
                """
            )
        ).scalar_one_or_none()
        is not None
    )


def fetch_latest_import_status(connection: Connection) -> LivingPopulationImportStatus:
    if not file_imports_table_exists(connection):
        return LivingPopulationImportStatus()

    row = connection.execute(
        text(
            """
            SELECT
                status,
                original_filename,
                min_period,
                max_period,
                period_count,
                raw_row_count,
                imported_at,
                raw_completed_at,
                clean_completed_at
            FROM metadata.file_imports
            WHERE source_name = :source_name
            ORDER BY
                clean_completed_at DESC NULLS LAST,
                raw_completed_at DESC NULLS LAST,
                imported_at DESC
            LIMIT 1
            """
        ),
        {"source_name": SOURCE_NAME},
    ).one_or_none()
    if row is None:
        return LivingPopulationImportStatus()

    return LivingPopulationImportStatus(
        status=str(row.status),
        original_filename=str(row.original_filename),
        min_period=str(row.min_period),
        max_period=str(row.max_period),
        period_count=int(row.period_count),
        raw_row_count=int(row.raw_row_count),
        imported_at=row.imported_at,
        raw_completed_at=row.raw_completed_at,
        clean_completed_at=row.clean_completed_at,
    )


def upsert_file_import_started(
    connection: Connection,
    parsed: ParsedLivingPopulationFile,
) -> int:
    file_import_id = connection.execute(
        text(
            """
            INSERT INTO metadata.file_imports (
                source_name,
                sha256,
                original_filename,
                file_size_bytes,
                min_period,
                max_period,
                period_count,
                raw_row_count,
                status,
                error_summary
            )
            VALUES (
                :source_name,
                :sha256,
                :original_filename,
                :file_size_bytes,
                :min_period,
                :max_period,
                :period_count,
                :raw_row_count,
                'started',
                NULL
            )
            ON CONFLICT (source_name, sha256)
            DO UPDATE SET
                attempt_count = metadata.file_imports.attempt_count + 1,
                original_filename = EXCLUDED.original_filename,
                file_size_bytes = EXCLUDED.file_size_bytes,
                min_period = EXCLUDED.min_period,
                max_period = EXCLUDED.max_period,
                period_count = EXCLUDED.period_count,
                raw_row_count = EXCLUDED.raw_row_count,
                imported_at = now(),
                status = 'started',
                error_summary = NULL
            RETURNING id
            """
        ),
        {
            "source_name": SOURCE_NAME,
            "sha256": parsed.sha256,
            "original_filename": parsed.path.name,
            "file_size_bytes": parsed.file_size_bytes,
            "min_period": parsed.min_period,
            "max_period": parsed.max_period,
            "period_count": len(parsed.periods),
            "raw_row_count": len(parsed.rows),
        },
    ).scalar_one()
    return int(file_import_id)


def insert_file_import_periods(
    connection: Connection,
    *,
    file_import_id: int,
    parsed: ParsedLivingPopulationFile,
) -> None:
    period_counts = Counter(row["period"] for row in parsed.rows)
    connection.execute(
        text(
            """
            DELETE FROM metadata.file_import_periods
            WHERE file_import_id = :file_import_id
            """
        ),
        {"file_import_id": file_import_id},
    )
    connection.execute(
        text(
            """
            INSERT INTO metadata.file_import_periods (
                file_import_id,
                period,
                raw_row_count
            )
            VALUES (
                :file_import_id,
                :period,
                :raw_row_count
            )
            """
        ),
        [
            {
                "file_import_id": file_import_id,
                "period": period,
                "raw_row_count": period_counts[period],
            }
            for period in parsed.periods
        ],
    )


def replace_raw_periods(
    connection: Connection,
    parsed: ParsedLivingPopulationFile,
) -> None:
    connection.execute(
        text(
            """
            DELETE FROM raw.living_population
            WHERE period IN :periods
            """
        ).bindparams(bindparam("periods", expanding=True)),
        {"periods": list(parsed.periods)},
    )
    connection.execute(
        text(
            """
            INSERT INTO raw.living_population (
                period,
                source_file_name,
                source_file_hash,
                source_row_number,
                region_sido_raw,
                region_sigungu_raw,
                region_type_raw,
                population_type_raw,
                age_raw,
                value_raw,
                imported_at
            )
            VALUES (
                :period,
                :source_file_name,
                :source_file_hash,
                :source_row_number,
                :region_sido_raw,
                :region_sigungu_raw,
                :region_type_raw,
                :population_type_raw,
                :age_raw,
                :value_raw,
                :imported_at
            )
            """
        ),
        list(parsed.rows),
    )


def mark_raw_committed(
    connection: Connection,
    *,
    file_import_id: int,
) -> None:
    connection.execute(
        text(
            """
            UPDATE metadata.file_imports
            SET status = 'raw_committed',
                raw_completed_at = now(),
                error_summary = NULL
            WHERE id = :file_import_id
            """
        ),
        {"file_import_id": file_import_id},
    )


def mark_clean_committed(
    connection: Connection,
    *,
    sha256: str,
) -> None:
    connection.execute(
        text(
            """
            UPDATE metadata.file_imports
            SET status = 'clean_committed',
                clean_completed_at = now(),
                error_summary = NULL
            WHERE source_name = :source_name
              AND sha256 = :sha256
            """
        ),
        {"source_name": SOURCE_NAME, "sha256": sha256},
    )


def mark_failed(
    connection: Connection,
    *,
    sha256: str,
    error_summary: str,
) -> None:
    connection.execute(
        text(
            """
            UPDATE metadata.file_imports
            SET status = 'failed',
                error_summary = :error_summary
            WHERE source_name = :source_name
              AND sha256 = :sha256
            """
        ),
        {
            "source_name": SOURCE_NAME,
            "sha256": sha256,
            "error_summary": error_summary[:1000],
        },
    )


def import_living_population_file(
    path: str | Path,
    *,
    engine: Engine | None = None,
    force_raw: bool = False,
    clean_runner: CleanRunner = clean_orchestrator.run_clean_datasets,
) -> LivingPopulationImportResult:
    parsed = parse_living_population_csv(path)
    db_engine = engine or get_engine()
    raw_status = "skipped_existing"

    LOGGER.info(
        "living population import parsed file=%s periods=%d raw_rows=%d sha256=%s",
        parsed.path,
        len(parsed.periods),
        len(parsed.rows),
        parsed.sha256[:12],
    )
    try:
        with db_engine.begin() as connection:
            ensure_import_tables(connection)
            existing = fetch_existing_import_status(
                connection,
                sha256=parsed.sha256,
            )
            if existing and existing[1] == "clean_committed" and not force_raw:
                LOGGER.info(
                    "living population import skipped existing clean file=%s sha256=%s",
                    parsed.path,
                    parsed.sha256[:12],
                )
                raw_status = "skipped_existing"
            else:
                file_import_id = upsert_file_import_started(connection, parsed)
                insert_file_import_periods(
                    connection,
                    file_import_id=file_import_id,
                    parsed=parsed,
                )
                replace_raw_periods(connection, parsed)
                mark_raw_committed(connection, file_import_id=file_import_id)
                raw_status = "raw_replaced" if existing else "raw_committed"
    except Exception:
        LOGGER.exception("living population raw import failed file=%s", parsed.path)
        raise

    clean_results: tuple[clean_orchestrator.CleanDatasetResult, ...] = ()
    if raw_status == "skipped_existing":
        return LivingPopulationImportResult(
            source_name=SOURCE_NAME,
            file_path=parsed.path,
            sha256=parsed.sha256,
            periods=parsed.periods,
            raw_row_count=len(parsed.rows),
            raw_status=raw_status,
            clean_results=clean_results,
        )

    try:
        clean_results = clean_runner(
            ("living_population",),
            engine=db_engine,
            rebuild=True,
            exact_rebuild_periods=parsed.periods,
        )
    except Exception as exc:
        with db_engine.begin() as connection:
            ensure_import_tables(connection)
            mark_failed(connection, sha256=parsed.sha256, error_summary=str(exc))
        raise

    with db_engine.begin() as connection:
        ensure_import_tables(connection)
        mark_clean_committed(connection, sha256=parsed.sha256)

    LOGGER.info(
        "living population import complete file=%s periods=%d raw_rows=%d "
        "clean_results=%d",
        parsed.path,
        len(parsed.periods),
        len(parsed.rows),
        len(clean_results),
    )
    return LivingPopulationImportResult(
        source_name=SOURCE_NAME,
        file_path=parsed.path,
        sha256=parsed.sha256,
        periods=parsed.periods,
        raw_row_count=len(parsed.rows),
        raw_status=raw_status,
        clean_results=clean_results,
    )
