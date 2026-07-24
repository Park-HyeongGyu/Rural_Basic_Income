from __future__ import annotations

from sqlalchemy.engine import Engine

from rural_basic_income.worker.clean_orchestrator import (
    CLEAN_SQL_LOCK_KEY,
    LOCAL_CURRENCY_REGION_CODES_PATH,
    PROJECT_ROOT,
    REGION_MERGE_KEY_PATH,
    CleanDatasetResult,
    CleanDatasetSpec,
    clean_dataset_specs,
    load_clean_dependencies,
    load_local_currency_region_codes,
    load_region_merge_key,
    read_sql_statements,
    run_clean_datasets,
    run_clean_sql,
    run_sql_file,
)

SQL_FILES = tuple(spec.sql_file for spec in clean_dataset_specs())


def main(engine: Engine | None = None) -> None:
    executed_counts = run_clean_sql(engine=engine)
    for name, count in executed_counts.items():
        print(f"{name}: {count}")


__all__ = [
    "CLEAN_SQL_LOCK_KEY",
    "LOCAL_CURRENCY_REGION_CODES_PATH",
    "PROJECT_ROOT",
    "REGION_MERGE_KEY_PATH",
    "SQL_FILES",
    "CleanDatasetResult",
    "CleanDatasetSpec",
    "clean_dataset_specs",
    "load_clean_dependencies",
    "load_local_currency_region_codes",
    "load_region_merge_key",
    "main",
    "read_sql_statements",
    "run_clean_datasets",
    "run_clean_sql",
    "run_sql_file",
]


if __name__ == "__main__":
    main()
