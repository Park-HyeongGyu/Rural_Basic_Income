from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from rural_basic_income.worker.sources.local_currency import download_local_currency


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LOCAL_CURRENCY_RAW_EXPORT_TEST") != "1",
    reason="Set RUN_LOCAL_CURRENCY_RAW_EXPORT_TEST=1 to download local currency raw CSV.",
)


def test_export_local_currency_202401_raw_csv() -> None:
    result = download_local_currency(
        "202401",
        per_page=10_000,
        request_sleep_seconds=0,
        timeout=60,
        max_retries=2,
    )

    assert result.period == "202401"
    assert result.source_name == "local_currency"
    assert result.raw_rows

    output_path = Path("data/temp/raw_local_currency_202401.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=result.raw_columns)
        writer.writeheader()
        writer.writerows(result.raw_rows)

    usage_region_count = len({row["usage_rgn_cd"] for row in result.raw_rows})
    age_groups = sorted({row["par_ag"] for row in result.raw_rows})
    genders = sorted({row["par_gend"] for row in result.raw_rows})

    print(f"exported={output_path}")
    print(f"payload_pages={len(result.payload_chunks)}")
    print(f"raw_rows={result.raw_row_count}")
    print(f"usage_regions={usage_region_count}")
    print(f"age_groups={age_groups}")
    print(f"genders={genders}")
