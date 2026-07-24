from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from rural_basic_income.worker import raw_orchestrator, raw_writer
from rural_basic_income.worker.download import PayloadChunk, SourcePeriodDownload


def make_download(
    source_name: str,
    period: str,
    *,
    raw_table: str | None = None,
    payload_rows: tuple[Mapping[str, Any], ...] = (),
    raw_rows: tuple[Mapping[str, str], ...] | None = None,
) -> SourcePeriodDownload:
    return SourcePeriodDownload(
        source_name=source_name,
        source_name_kor=f"{source_name} 이름",
        source_org_id="ORG",
        source_table_id="TABLE",
        raw_table=raw_table or source_name,
        period=period,
        payload_chunks=(
            PayloadChunk(
                request_params={"period": period},
                response_payload=payload_rows,
            ),
        ),
        raw_columns=("시점", "값", "downloaded_at"),
        raw_rows=raw_rows
        or (
            {
                "시점": period,
                "값": "1",
                "downloaded_at": "2026-07-24T00:00:00+00:00",
            },
        ),
    )


def test_refresh_source_period_skips_existing_without_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_source_period_success_row_count(source_name, period, *, engine=None):
        assert source_name == "local_currency"
        assert period == "202604"
        return 10

    def fail_downloader(period: str):
        raise AssertionError("downloader should not be called")

    def fail_writer(download, *, engine=None, force=False):
        raise AssertionError("writer should not be called")

    monkeypatch.setattr(
        raw_orchestrator,
        "source_period_success_row_count",
        fake_source_period_success_row_count,
    )

    result = raw_orchestrator.refresh_source_period(
        "local_currency",
        "202604",
        engine=object(),
        downloaders={"local_currency": fail_downloader},
        writer=fail_writer,
    )

    assert result == raw_orchestrator.RawRefreshResult(
        source_name="local_currency",
        period="202604",
        status="skipped_existing",
        row_count=10,
    )
    assert not result.downloaded


def test_refresh_source_period_downloads_and_writes_new_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(
        raw_orchestrator,
        "source_period_success_row_count",
        lambda source_name, period, *, engine=None: None,
    )

    def fake_downloader(period: str, *, per_page: int):
        calls.append(("download", period, per_page))
        return make_download("local_currency", period)

    def fake_writer(download, *, engine=None, force=False):
        calls.append(("writer", download.source_name, download.period, force))
        return raw_writer.RawWriteResult(
            source_name=download.source_name,
            period=download.period,
            status="written",
            row_count=download.raw_row_count,
        )

    result = raw_orchestrator.refresh_source_period(
        "local_currency",
        "202604",
        engine=object(),
        source_options={"per_page": 1000},
        downloaders={"local_currency": fake_downloader},
        writer=fake_writer,
    )

    assert result.status == "downloaded_written"
    assert result.downloaded
    assert result.row_count == 1
    assert calls == [
        ("download", "202604", 1000),
        ("writer", "local_currency", "202604", False),
    ]


def test_refresh_source_period_force_downloads_even_if_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(
        raw_orchestrator,
        "source_period_success_row_count",
        lambda source_name, period, *, engine=None: 99,
    )

    def fake_downloader(period: str):
        calls.append(("download", period))
        return make_download("electricity", period)

    def fake_writer(download, *, engine=None, force=False):
        calls.append(("writer", force))
        return raw_writer.RawWriteResult(
            source_name=download.source_name,
            period=download.period,
            status="written",
            row_count=download.raw_row_count,
        )

    result = raw_orchestrator.refresh_source_period(
        "electricity",
        "202604",
        engine=object(),
        force=True,
        downloaders={"electricity": fake_downloader},
        writer=fake_writer,
    )

    assert result.status == "downloaded_written"
    assert calls == [("download", "202604"), ("writer", True)]


def test_refresh_source_period_reports_writer_skip_after_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        raw_orchestrator,
        "source_period_success_row_count",
        lambda source_name, period, *, engine=None: None,
    )

    def fake_downloader(period: str):
        return make_download("electricity", period)

    def fake_writer(download, *, engine=None, force=False):
        return raw_writer.RawWriteResult(
            source_name=download.source_name,
            period=download.period,
            status="skipped",
            row_count=5,
        )

    result = raw_orchestrator.refresh_source_period(
        "electricity",
        "202604",
        engine=object(),
        downloaders={"electricity": fake_downloader},
        writer=fake_writer,
    )

    assert result.status == "downloaded_skipped"
    assert result.row_count == 5


def test_refresh_raw_period_does_not_share_household_region_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(
        raw_orchestrator,
        "source_period_success_row_count",
        lambda source_name, period, *, engine=None: None,
    )

    def download_household(period: str):
        calls.append(("household", period))
        return make_download(
            "household",
            period,
            payload_rows=(
                {"C1": "11110"},
                {"C1": "11140"},
                {"C1": "11110"},
            ),
        )

    def download_population(period: str):
        calls.append(("population", period))
        return make_download("population", period)

    def download_mover(period: str):
        calls.append(("mover", period))
        return make_download("mover", period)

    def fake_writer(download, *, engine=None, force=False):
        return raw_writer.RawWriteResult(
            source_name=download.source_name,
            period=download.period,
            status="written",
            row_count=download.raw_row_count,
        )

    results = raw_orchestrator.refresh_raw_period(
        "202604",
        sources=("household", "population", "mover"),
        engine=object(),
        downloaders={
            "household": download_household,
            "population": download_population,
            "mover": download_mover,
        },
        writer=fake_writer,
    )

    assert [result.source_name for result in results] == [
        "household",
        "population",
        "mover",
    ]
    assert calls == [
        ("household", "202604"),
        ("population", "202604"),
        ("mover", "202604"),
    ]


def test_refresh_raw_range_runs_periods_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        raw_orchestrator,
        "source_period_success_row_count",
        lambda source_name, period, *, engine=None: None,
    )

    calls: list[tuple[str, str]] = []

    def fake_downloader(period: str):
        calls.append(("electricity", period))
        return make_download("electricity", period)

    def fake_writer(download, *, engine=None, force=False):
        return raw_writer.RawWriteResult(
            source_name=download.source_name,
            period=download.period,
            status="written",
            row_count=download.raw_row_count,
        )

    results = raw_orchestrator.refresh_raw_range(
        "202604",
        "202606",
        sources=("electricity",),
        engine=object(),
        downloaders={"electricity": fake_downloader},
        writer=fake_writer,
    )

    assert calls == [
        ("electricity", "202604"),
        ("electricity", "202605"),
        ("electricity", "202606"),
    ]
    assert [result.period for result in results] == [
        "202604",
        "202605",
        "202606",
    ]


def test_unknown_source_raises_clear_error() -> None:
    with pytest.raises(raw_orchestrator.RawOrchestratorError) as exc_info:
        raw_orchestrator.get_downloader("permits", {"electricity": lambda period: None})

    assert "unknown raw source: permits" in str(exc_info.value)
