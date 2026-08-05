from __future__ import annotations

from pathlib import Path
from typing import Any

from rural_basic_income.worker import clean_orchestrator
from rural_basic_income.worker.importers import living_population


def write_sample_living_population(path: Path) -> Path:
    path.write_text(
        "시도명,시군구명,구분,생활인구,2024.01,2024.01,2024.02,2024.02,\n"
        "시도명,시군구명,구분,생활인구,계,20대,계,20대,\n"
        "전북특별자치도,임실군,감소,계,100,20,110,22,\n"
        "전북특별자치도,임실군,감소,주민등록인구,70,10,71,11,\n"
        "전북특별자치도,임실군,감소,체류인구,25,8,34,9,\n"
        "전북특별자치도,임실군,감소,외국인,*,2,*,2,\n",
        encoding="utf-8-sig",
    )
    return path


class ScalarResult:
    def __init__(self, value: Any = None) -> None:
        self.value = value

    def scalar_one(self):
        return self.value

    def one_or_none(self):
        return self.value


class RecordingConnection:
    def __init__(self, *, existing_status: tuple[int, str] | None = None) -> None:
        self.existing_status = existing_status
        self.calls: list[tuple[str, Any]] = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))
        if "SELECT id, status" in sql:
            if self.existing_status is None:
                return ScalarResult(None)
            return ScalarResult(
                type(
                    "Row",
                    (),
                    {"id": self.existing_status[0], "status": self.existing_status[1]},
                )()
            )
        if "RETURNING id" in sql:
            return ScalarResult(1)
        return ScalarResult()


class RecordingTransaction:
    def __init__(self, connection: RecordingConnection) -> None:
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class RecordingEngine:
    def __init__(self, connection: RecordingConnection) -> None:
        self.connection = connection

    def begin(self):
        return RecordingTransaction(self.connection)


def matching_calls(connection: RecordingConnection, needle: str):
    return [
        (sql, parameters)
        for sql, parameters in connection.calls
        if needle in sql
    ]


def test_parse_living_population_csv_expands_two_header_wide_file(
    tmp_path: Path,
) -> None:
    sample = write_sample_living_population(tmp_path / "living.csv")

    parsed = living_population.parse_living_population_csv(sample)

    assert parsed.periods == ("202401", "202402")
    assert parsed.source_row_count == 4
    assert len(parsed.rows) == 16
    assert parsed.rows[0]["period"] == "202401"
    assert parsed.rows[0]["age_raw"] == "계"
    assert parsed.rows[0]["value_raw"] == "100"
    assert any(row["value_raw"] == "*" for row in parsed.rows)


def test_parse_living_population_rejects_duplicate_cells(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.csv"
    path.write_text(
        "시도명,시군구명,구분,생활인구,2024.01,2024.01\n"
        "시도명,시군구명,구분,생활인구,계,계\n"
        "전북특별자치도,임실군,감소,계,1,2\n",
        encoding="utf-8-sig",
    )

    try:
        living_population.parse_living_population_csv(path)
    except living_population.LivingPopulationImportError as exc:
        assert "duplicate living population cell" in str(exc)
    else:
        raise AssertionError("duplicate living population cells should fail")


def test_import_living_population_replaces_raw_and_runs_clean(
    tmp_path: Path,
) -> None:
    sample = write_sample_living_population(tmp_path / "living.csv")
    connection = RecordingConnection()
    engine = RecordingEngine(connection)
    clean_calls: list[tuple[Any, ...]] = []

    def clean_runner(datasets=None, **kwargs):
        clean_calls.append((datasets, kwargs))
        return (
            clean_orchestrator.CleanDatasetResult(
                dataset_name="living_population",
                sql_file=Path("clean_living_population.sql"),
                statement_count=10,
                affected_row_count=5,
                revision=1,
                revision_changed=True,
            ),
        )

    result = living_population.import_living_population_file(
        sample,
        engine=engine,
        clean_runner=clean_runner,
    )

    assert result.raw_status == "raw_committed"
    assert result.raw_changed is True
    assert result.clean_changed is True
    assert matching_calls(connection, "DELETE FROM raw.living_population")
    assert matching_calls(connection, "INSERT INTO raw.living_population")
    assert clean_calls[0][0] == ("living_population",)
    assert clean_calls[0][1]["rebuild"] is True
    assert clean_calls[0][1]["exact_rebuild_periods"] == ("202401", "202402")


def test_import_living_population_skips_same_clean_committed_hash(
    tmp_path: Path,
) -> None:
    sample = write_sample_living_population(tmp_path / "living.csv")
    parsed = living_population.parse_living_population_csv(sample)
    connection = RecordingConnection(existing_status=(7, "clean_committed"))
    engine = RecordingEngine(connection)

    result = living_population.import_living_population_file(
        sample,
        engine=engine,
        clean_runner=lambda *args, **kwargs: (),
    )

    assert result.sha256 == parsed.sha256
    assert result.raw_status == "skipped_existing"
    assert not matching_calls(connection, "INSERT INTO raw.living_population")
