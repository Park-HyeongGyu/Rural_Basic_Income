from __future__ import annotations

from scripts import generate_migration_od_clean_sql

from rural_basic_income.worker.sources import migration_od_schema


def test_migration_od_schema_contract_matches_public_api_columns() -> None:
    assert len(migration_od_schema.BASIC_RAW_COLUMNS) == 12
    assert len(migration_od_schema.AGE_RAW_COLUMNS) == 222
    assert len(migration_od_schema.RAW_COLUMNS) == 235
    assert [bucket.label for bucket in migration_od_schema.AGE_BUCKETS[:3]] == [
        "0-4",
        "5-9",
        "10-14",
    ]
    assert migration_od_schema.AGE_BUCKETS[-1].label == "80-"
    assert migration_od_schema.age_raw_column("male", 24) == "male24AgeNmprCnt"
    assert migration_od_schema.age_raw_column("female", 24) == "feml24AgeNmprCnt"
    assert (
        migration_od_schema.bucket_sql_column(
            "male",
            migration_od_schema.AGE_BUCKETS[-1],
        )
        == "male_80_plus"
    )


def test_migration_od_clean_sql_is_generated_from_contract() -> None:
    checked_in_sql = generate_migration_od_clean_sql.SQL_PATH.read_text(
        encoding="utf-8"
    )

    assert checked_in_sql == generate_migration_od_clean_sql.generate_sql()


def test_generated_migration_od_clean_sql_keeps_fast_path_and_guard() -> None:
    sql = generate_migration_od_clean_sql.generate_sql()

    assert "to_jsonb" not in sql
    assert "jsonb_each_text" not in sql
    assert "ON CONFLICT" not in sql
    assert "ORDER BY" not in sql
    assert "migration_od_statsym_idx" in sql
    assert "no_unmapped_migration_od_region" in sql
    assert "p.destination_sigungu_raw = '영종구'" in sql
    assert "p.origin_sigungu_raw = '영종구'" in sql
    assert 'raw_mo."male0AgeNmprCnt"' in sql
    assert 'raw_mo."feml110AgeNmprCnt"' in sql
    assert '"male_0_4"' in sql
    assert '"male_80_plus"' in sql
