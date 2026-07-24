from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from rural_basic_income.worker.sources.electricity import download_electricity


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_ELECTRICITY_RAW_EXPORT_TEST") != "1",
    reason="Set RUN_ELECTRICITY_RAW_EXPORT_TEST=1 to download KEPCO raw CSV.",
)


def test_export_electricity_202601_raw_csv() -> None:
    result = download_electricity("202601", timeout=60, max_retries=2)

    assert result.period == "202601"
    assert result.source_name == "electricity"
    assert result.raw_rows
    assert all(row["city"] != "전체" for row in result.raw_rows)

    output_path = Path("data/temp/raw_electricity_202601.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=result.raw_columns)
        writer.writeheader()
        writer.writerows(result.raw_rows)

    contract_types = sorted({row["cntr"] for row in result.raw_rows})
    region_count = len({(row["metro"], row["city"]) for row in result.raw_rows})

    print(f"exported={output_path}")
    print(f"raw_rows={result.raw_row_count}")
    print(f"regions={region_count}")
    print(f"contract_types={contract_types}")
