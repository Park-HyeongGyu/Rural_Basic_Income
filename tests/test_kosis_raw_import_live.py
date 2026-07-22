import os
from pathlib import Path

import pytest

from rural_basic_income.config import get_settings
from rural_basic_income.db.connection import assert_database_ready
from rural_basic_income.pipeline.kosis_raw import (
    export_raw_test_tables,
    load_raw_tables,
)


@pytest.mark.skipif(
    os.environ.get("RUN_KOSIS_RAW_IMPORT_TEST") != "1",
    reason="set RUN_KOSIS_RAW_IMPORT_TEST=1 to download and import KOSIS raw rows",
)
def test_import_202601_kosis_raw_tables_and_export_csv() -> None:
    settings = get_settings()
    if not settings.kosis_api_key:
        pytest.skip("KOSIS_API_KEY is not set")

    assert_database_ready()

    row_counts = load_raw_tables("202601")
    assert row_counts["household"] > 0
    assert row_counts["population"] > 0
    assert row_counts["mover"] > 0

    exported_paths = export_raw_test_tables(Path("data/temp"))
    for path in exported_paths:
        assert path.exists()
        assert path.stat().st_size > 0
