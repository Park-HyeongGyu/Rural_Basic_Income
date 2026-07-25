from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from rural_basic_income.worker.download import PeriodDownload, SourcePeriodUnavailable
from rural_basic_income.worker.sources import _kosis, household, mover, population


def test_download_sources_return_in_memory_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Mapping[str, str]] = []

    def fake_fetch_statistics_parameter_data(
        params: Mapping[str, str],
        *,
        timeout: float = 30,
        max_retries: int = 5,
    ) -> list[dict[str, Any]]:
        calls.append(dict(params))
        period = params["startPrdDe"]
        table_id = params["tblId"]

        if table_id == "DT_1B040B3":
            return [
                {
                    "PRD_DE": period,
                    "C1_OBJ_NM": "행정구역",
                    "C1": "11110",
                    "C1_NM": "서울 종로구",
                    "ITM_NM": "세대수",
                    "UNIT_NM": "가구",
                    "DT": "10",
                },
                {
                    "PRD_DE": period,
                    "C1_OBJ_NM": "행정구역",
                    "C1": "11140",
                    "C1_NM": "서울 중구",
                    "ITM_NM": "세대수",
                    "UNIT_NM": "가구",
                    "DT": "20",
                },
            ]

        if table_id == "DT_1B04006":
            requested_codes = set(params["objL1"].split("+"))
            rows = []
            for code, name, value in (
                ("11110", "서울 종로구", "100"),
                ("11140", "서울 중구", "200"),
            ):
                if code not in requested_codes:
                    continue
                rows.append(
                    {
                        "PRD_DE": period,
                        "C1_OBJ_NM": "행정구역",
                        "C1": code,
                        "C1_NM": name,
                        "C2_OBJ_NM": "연령별",
                        "C2": "000",
                        "C2_NM": "계",
                        "ITM_NM": "총인구",
                        "UNIT_NM": "명",
                        "DT": value,
                    }
                )
            return rows

        if table_id == "DT_1B26001":
            return [
                {
                    "PRD_DE": period,
                    "C1_OBJ_NM": "행정구역",
                    "C1": "11110",
                    "C1_NM": "서울 종로구",
                    "C2_OBJ_NM": "성별",
                    "C2": "0",
                    "C2_NM": "계",
                    "C3_OBJ_NM": "연령별",
                    "C3": "000",
                    "C3_NM": "계",
                    "ITM_NM": "총전입",
                    "UNIT_NM": "명",
                    "DT": "5",
                }
            ]

        raise AssertionError(f"unexpected table id: {table_id}")

    monkeypatch.setattr(
        _kosis,
        "fetch_statistics_parameter_data",
        fake_fetch_statistics_parameter_data,
    )

    household_result = household.download_household(
        "202604",
        request_sleep_seconds=0,
    )
    region_codes = household.extract_region_codes(
        list(household_result.payload_chunks[0].response_payload)
    )
    population_result = population.download_population(
        "202604",
        region_codes=region_codes,
        chunk_size=1,
        request_sleep_seconds=0,
    )
    mover_result = mover.download_mover(
        "202604",
        region_codes=region_codes,
        chunk_size=2,
        request_sleep_seconds=0,
    )
    result = PeriodDownload(
        period="202604",
        sources=(household_result, population_result, mover_result),
    )

    assert result.period == "202604"
    assert result.source_names == ("household", "population", "mover")

    household_source = result.get_source("household")
    population_source = result.get_source("population")
    mover_source = result.get_source("mover")

    assert household_source.payload_row_count == 2
    assert household_source.raw_row_count == 2
    assert household_source.raw_columns == (
        "시점",
        "C행정구역",
        "행정구역",
        "세대수 (가구)",
        "downloaded_at",
    )

    assert population_source.payload_row_count == 2
    assert population_source.raw_row_count == 2
    assert len(population_source.payload_chunks) == 2

    assert mover_source.payload_row_count == 1
    assert mover_source.raw_row_count == 1
    assert len(mover_source.payload_chunks) == 1

    assert [call["tblId"] for call in calls] == [
        "DT_1B040B3",
        "DT_1B04006",
        "DT_1B04006",
        "DT_1B26001",
    ]


def test_population_download_uses_population_table_region_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Mapping[str, str]] = []

    def fake_fetch_statistics_parameter_data(
        params: Mapping[str, str],
        *,
        timeout: float = 30,
        max_retries: int = 5,
    ) -> list[dict[str, Any]]:
        calls.append(dict(params))
        period = params["startPrdDe"]
        assert params["tblId"] == "DT_1B04006"

        if params["objL1"] == "ALL":
            assert params["objL2"] == "000"
            return [
                {
                    "PRD_DE": period,
                    "C1_OBJ_NM": "행정구역",
                    "C1": "11110",
                    "C1_NM": "서울 종로구",
                    "C2_OBJ_NM": "연령별",
                    "C2": "000",
                    "C2_NM": "계",
                    "ITM_NM": "총인구",
                    "UNIT_NM": "명",
                    "DT": "100",
                },
                {
                    "PRD_DE": period,
                    "C1_OBJ_NM": "행정구역",
                    "C1": "11140",
                    "C1_NM": "서울 중구",
                    "C2_OBJ_NM": "연령별",
                    "C2": "000",
                    "C2_NM": "계",
                    "ITM_NM": "총인구",
                    "UNIT_NM": "명",
                    "DT": "200",
                }
            ]

        assert params["objL2"] == "ALL"
        return [
            {
                "PRD_DE": period,
                "C1_OBJ_NM": "행정구역",
                "C1": params["objL1"],
                "C1_NM": f"지역 {params['objL1']}",
                "C2_OBJ_NM": "연령별",
                "C2": "000",
                "C2_NM": "계",
                "ITM_NM": "총인구",
                "UNIT_NM": "명",
                "DT": "100",
            }
        ]

    monkeypatch.setattr(
        _kosis,
        "fetch_statistics_parameter_data",
        fake_fetch_statistics_parameter_data,
    )

    result = population.download_population(
        "202604",
        chunk_size=1,
        request_sleep_seconds=0,
    )

    assert result.source_name == "population"
    assert [call["tblId"] for call in calls] == [
        "DT_1B04006",
        "DT_1B04006",
        "DT_1B04006",
    ]
    assert calls[0]["objL1"] == "ALL"
    assert calls[1]["objL1"] == "11110"
    assert calls[2]["objL1"] == "11140"


def test_mover_download_uses_mover_table_region_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Mapping[str, str]] = []

    def fake_fetch_statistics_parameter_data(
        params: Mapping[str, str],
        *,
        timeout: float = 30,
        max_retries: int = 5,
    ) -> list[dict[str, Any]]:
        calls.append(dict(params))
        period = params["startPrdDe"]
        assert params["tblId"] == "DT_1B26001"

        if params["objL1"] == "ALL":
            assert params["objL2"] == "0"
            assert params["objL3"] == "000"
            return [
                {
                    "PRD_DE": period,
                    "C1_OBJ_NM": "행정구역",
                    "C1": "11110",
                    "C1_NM": "서울 종로구",
                    "C2_OBJ_NM": "성별",
                    "C2": "0",
                    "C2_NM": "계",
                    "C3_OBJ_NM": "연령별",
                    "C3": "000",
                    "C3_NM": "계",
                    "ITM_NM": "총전입",
                    "UNIT_NM": "명",
                    "DT": "5",
                },
                {
                    "PRD_DE": period,
                    "C1_OBJ_NM": "행정구역",
                    "C1": "11140",
                    "C1_NM": "서울 중구",
                    "C2_OBJ_NM": "성별",
                    "C2": "0",
                    "C2_NM": "계",
                    "C3_OBJ_NM": "연령별",
                    "C3": "000",
                    "C3_NM": "계",
                    "ITM_NM": "총전입",
                    "UNIT_NM": "명",
                    "DT": "6",
                },
            ]

        assert params["objL2"] == "ALL"
        assert params["objL3"] == "ALL"
        return [
            {
                "PRD_DE": period,
                "C1_OBJ_NM": "행정구역",
                "C1": params["objL1"],
                "C1_NM": f"지역 {params['objL1']}",
                "C2_OBJ_NM": "성별",
                "C2": "0",
                "C2_NM": "계",
                "C3_OBJ_NM": "연령별",
                "C3": "000",
                "C3_NM": "계",
                "ITM_NM": "총전입",
                "UNIT_NM": "명",
                "DT": "5",
            }
        ]

    monkeypatch.setattr(
        _kosis,
        "fetch_statistics_parameter_data",
        fake_fetch_statistics_parameter_data,
    )

    result = mover.download_mover(
        "202604",
        chunk_size=1,
        request_sleep_seconds=0,
    )

    assert result.source_name == "mover"
    assert [call["tblId"] for call in calls] == [
        "DT_1B26001",
        "DT_1B26001",
        "DT_1B26001",
    ]
    assert calls[0]["objL1"] == "ALL"
    assert calls[1]["objL1"] == "11110"
    assert calls[2]["objL1"] == "11140"


def test_mover_download_accepts_preloaded_region_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Mapping[str, str]] = []

    def fake_fetch_statistics_parameter_data(
        params: Mapping[str, str],
        *,
        timeout: float = 30,
        max_retries: int = 5,
    ) -> list[dict[str, Any]]:
        calls.append(dict(params))
        period = params["startPrdDe"]
        return [
            {
                "PRD_DE": period,
                "C1_OBJ_NM": "행정구역",
                "C1": "11110",
                "C1_NM": "서울 종로구",
                "C2_OBJ_NM": "성별",
                "C2": "0",
                "C2_NM": "계",
                "C3_OBJ_NM": "연령별",
                "C3": "000",
                "C3_NM": "계",
                "ITM_NM": "총전입",
                "UNIT_NM": "명",
                "DT": "5",
            }
        ]

    monkeypatch.setattr(
        _kosis,
        "fetch_statistics_parameter_data",
        fake_fetch_statistics_parameter_data,
    )

    result = mover.download_mover(
        "202604",
        region_codes=("11110", "11140"),
        chunk_size=70,
        request_sleep_seconds=0,
    )

    assert result.source_name == "mover"
    assert len(result.payload_chunks) == 1
    assert [call["tblId"] for call in calls] == ["DT_1B26001"]
    assert calls[0]["objL1"] == "11110+11140"


def test_kosis_error_30_is_source_period_unavailable() -> None:
    assert (
        _kosis.kosis_unavailable_message(
            {"err": "30", "errMsg": "데이터가 존재하지 않습니다."}
        )
        == "KOSIS data unavailable: 30 데이터가 존재하지 않습니다."
    )


def test_kosis_error_payload_is_source_period_unavailable() -> None:
    assert (
        _kosis.kosis_unavailable_message(
            {"err": "99", "errMsg": "API limit exceeded"}
        )
        == "KOSIS data unavailable: 99 API limit exceeded"
    )


def test_kosis_dict_response_with_no_data_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return '{"err":"30","errMsg":"데이터가 존재하지 않습니다."}'.encode(
                "utf-8"
            )

    monkeypatch.setattr(
        _kosis,
        "urlopen",
        lambda request, timeout=30: FakeResponse(),
    )
    monkeypatch.setattr(
        _kosis,
        "build_statistics_parameter_url",
        lambda params, api_key=None: "https://example.test/kosis",
    )

    with pytest.raises(SourcePeriodUnavailable):
        _kosis.fetch_statistics_parameter_data(
            {"tblId": "DT_1B26001", "startPrdDe": "202606"},
            max_retries=0,
        )


def test_kosis_unexpected_dict_response_raises_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return b'{"unexpected":"shape"}'

    monkeypatch.setattr(
        _kosis,
        "urlopen",
        lambda request, timeout=30: FakeResponse(),
    )
    monkeypatch.setattr(
        _kosis,
        "build_statistics_parameter_url",
        lambda params, api_key=None: "https://example.test/kosis",
    )

    with pytest.raises(SourcePeriodUnavailable):
        _kosis.fetch_statistics_parameter_data(
            {"tblId": "DT_1B26001", "startPrdDe": "202606"},
            max_retries=0,
        )
