from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from rural_basic_income.config import Settings
from rural_basic_income.worker import raw_orchestrator, raw_writer
from rural_basic_income.worker.download import (
    PayloadChunk,
    SourcePeriodDownload,
    SourcePeriodUnavailable,
)


def test_default_latest_start_period_uses_settings_value() -> None:
    settings = Settings(rbi_latest_start_period="202401")

    assert raw_orchestrator.default_latest_start_period(settings) == "202401"


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
        if raw_rows is not None
        else (
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


def test_force_unavailable_preserves_existing_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        raw_orchestrator,
        "source_period_success_row_count",
        lambda source_name, period, *, engine=None: 99,
    )

    def unavailable_downloader(period: str):
        raise SourcePeriodUnavailable("KOSIS data unavailable: 30 데이터가 존재하지 않습니다.")

    def fail_writer(download, *, engine=None, force=False):
        raise AssertionError("unavailable force refresh should not write raw rows")

    def fail_mark_unavailable(**kwargs):
        raise AssertionError("existing success metadata should be preserved")

    monkeypatch.setattr(
        raw_writer,
        "mark_source_period_unavailable",
        fail_mark_unavailable,
    )

    result = raw_orchestrator.refresh_source_period(
        "mover",
        "202604",
        engine=object(),
        force=True,
        downloaders={"mover": unavailable_downloader},
        writer=fail_writer,
    )

    assert result.status == "skipped_unavailable_existing"
    assert result.row_count == 99
    assert result.unavailable
    assert result.preserved_existing


def test_force_zero_row_download_preserves_existing_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        raw_orchestrator,
        "source_period_success_row_count",
        lambda source_name, period, *, engine=None: 12,
    )

    def empty_downloader(period: str):
        return make_download(
            "local_currency",
            period,
            raw_rows=(),
        )

    def fail_writer(download, *, engine=None, force=False):
        raise AssertionError("zero-row force refresh should not write raw rows")

    def fail_mark_unavailable(**kwargs):
        raise AssertionError("existing success metadata should be preserved")

    monkeypatch.setattr(
        raw_writer,
        "mark_source_period_unavailable",
        fail_mark_unavailable,
    )

    result = raw_orchestrator.refresh_source_period(
        "local_currency",
        "202604",
        engine=object(),
        force=True,
        downloaders={"local_currency": empty_downloader},
        writer=fail_writer,
    )

    assert result.status == "skipped_unavailable_existing"
    assert result.row_count == 12
    assert result.unavailable
    assert result.preserved_existing


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


def test_refresh_raw_latest_scans_requested_range_for_each_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        raw_orchestrator,
        "source_last_success_period",
        lambda source_name, *, engine=None: (_ for _ in ()).throw(
            AssertionError("--latest should not start from last success")
        ),
    )

    def fake_refresh_raw_range(
        start_period,
        end_period,
        *,
        sources=None,
        engine=None,
        force=False,
        source_options=None,
        downloaders=None,
        writer=None,
        continue_on_unavailable=True,
    ):
        calls.append((sources[0], start_period, end_period))
        return (
            raw_orchestrator.RawRefreshResult(
                source_name=sources[0],
                period=start_period,
                status="downloaded_written",
                row_count=1,
            ),
        )

    monkeypatch.setattr(
        raw_orchestrator,
        "refresh_raw_range",
        fake_refresh_raw_range,
    )

    results = raw_orchestrator.refresh_raw_latest(
        sources=("population", "mover"),
        engine=object(),
        fallback_start_period="202501",
        end_period="202605",
    )

    assert calls == [
        ("population", "202501", "202605"),
        ("mover", "202501", "202605"),
    ]
    assert [result.source_name for result in results] == ["population", "mover"]


def test_refresh_raw_latest_force_scans_requested_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, str, bool]] = []

    monkeypatch.setattr(
        raw_orchestrator,
        "source_last_success_period",
        lambda source_name, *, engine=None: (_ for _ in ()).throw(
            AssertionError("--latest force should not start from last success")
        ),
    )

    def fake_refresh_raw_range(
        start_period,
        end_period,
        *,
        sources=None,
        engine=None,
        force=False,
        source_options=None,
        downloaders=None,
        writer=None,
        continue_on_unavailable=True,
    ):
        calls.append((sources[0], start_period, end_period, force))
        return (
            raw_orchestrator.RawRefreshResult(
                source_name=sources[0],
                period=start_period,
                status="downloaded_written",
                row_count=1,
            ),
        )

    monkeypatch.setattr(
        raw_orchestrator,
        "refresh_raw_range",
        fake_refresh_raw_range,
    )

    results = raw_orchestrator.refresh_raw_latest(
        sources=("population",),
        engine=object(),
        force=True,
        fallback_start_period="202401",
        end_period="202606",
    )

    assert calls == [("population", "202401", "202606", True)]
    assert [result.source_name for result in results] == ["population"]


def test_refresh_raw_range_records_unavailable_periods_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        raw_orchestrator,
        "source_period_success_row_count",
        lambda source_name, period, *, engine=None: None,
    )

    metadata_calls: list[dict[str, Any]] = []

    def fake_mark_source_period_unavailable(**kwargs):
        metadata_calls.append(kwargs)

    monkeypatch.setattr(
        raw_writer,
        "mark_source_period_unavailable",
        fake_mark_source_period_unavailable,
    )

    calls: list[tuple[str, str]] = []

    def unavailable_mover(period: str):
        calls.append(("mover", period))
        raise SourcePeriodUnavailable("KOSIS data unavailable: 30 데이터가 존재하지 않습니다.")

    def download_electricity(period: str):
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
        "202605",
        "202606",
        sources=("mover", "electricity"),
        engine=object(),
        downloaders={
            "mover": unavailable_mover,
            "electricity": download_electricity,
        },
        writer=fake_writer,
    )

    assert calls == [
        ("mover", "202605"),
        ("electricity", "202605"),
        ("mover", "202606"),
        ("electricity", "202606"),
    ]
    assert [result.status for result in results] == [
        "skipped_unavailable",
        "downloaded_written",
        "skipped_unavailable",
        "downloaded_written",
    ]
    assert results[0].unavailable
    assert results[2].unavailable
    assert metadata_calls[0]["source_name"] == "mover"
    assert metadata_calls[0]["period"] == "202605"
    assert "데이터가 존재하지 않습니다" in metadata_calls[0]["error_message"]
    assert metadata_calls[1]["period"] == "202606"


def test_refresh_raw_range_can_fail_on_unavailable_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        raw_orchestrator,
        "source_period_success_row_count",
        lambda source_name, period, *, engine=None: None,
    )

    def unavailable_mover(period: str):
        raise SourcePeriodUnavailable("KOSIS data unavailable: 30 데이터가 존재하지 않습니다.")

    with pytest.raises(SourcePeriodUnavailable):
        raw_orchestrator.refresh_raw_range(
            "202605",
            "202606",
            sources=("mover",),
            engine=object(),
            downloaders={"mover": unavailable_mover},
            continue_on_unavailable=False,
        )


def test_refresh_source_period_records_zero_row_download_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        raw_orchestrator,
        "source_period_success_row_count",
        lambda source_name, period, *, engine=None: None,
    )

    metadata_calls: list[dict[str, Any]] = []

    def fake_mark_source_period_unavailable(**kwargs):
        metadata_calls.append(kwargs)

    monkeypatch.setattr(
        raw_writer,
        "mark_source_period_unavailable",
        fake_mark_source_period_unavailable,
    )

    def empty_download(period: str):
        return make_download(
            "local_currency",
            period,
            raw_rows=(),
        )

    def fail_writer(download, *, engine=None, force=False):
        raise AssertionError("zero-row unavailable downloads should not be written")

    result = raw_orchestrator.refresh_source_period(
        "local_currency",
        "202706",
        engine=object(),
        downloaders={"local_currency": empty_download},
        writer=fail_writer,
    )

    assert result.status == "skipped_unavailable"
    assert result.row_count == 0
    assert metadata_calls[0]["source_name"] == "local_currency"
    assert metadata_calls[0]["period"] == "202706"
    assert "returned no rows" in metadata_calls[0]["error_message"]


def test_unknown_source_raises_clear_error() -> None:
    with pytest.raises(raw_orchestrator.RawOrchestratorError) as exc_info:
        raw_orchestrator.get_downloader("permits", {"electricity": lambda period: None})

    assert "unknown raw source: permits" in str(exc_info.value)
