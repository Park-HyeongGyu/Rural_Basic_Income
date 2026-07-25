from __future__ import annotations

from io import BytesIO
from urllib.error import HTTPError

import pytest

from rural_basic_income.worker.download import SourcePeriodUnavailable
from rural_basic_income.worker.sources import electricity


def test_parse_concatenated_json_documents() -> None:
    response_text = (
        '{"totData":[{"year":"2026","month":"02","metro":"전체"}]}'
        '{"data":[{"year":"2026","month":"02","metro":"전북특별자치도"}]}'
    )

    documents = electricity.parse_concatenated_json_documents(response_text)

    assert len(documents) == 2
    assert documents[0]["totData"][0]["metro"] == "전체"
    assert documents[1]["data"][0]["metro"] == "전북특별자치도"


def test_fetch_kepco_documents_accepts_404_with_usable_data(monkeypatch) -> None:
    response_body = (
        '{"errCd":"404","errMsg":"NotFound"}'
        '{"data":[{"year":"2026","month":"01","metro":"강원특별자치도"}]}'
    ).encode()

    def fake_urlopen(request, timeout):
        raise HTTPError(
            url=request.full_url,
            code=404,
            msg="Not Found",
            hdrs={},
            fp=BytesIO(response_body),
        )

    monkeypatch.setattr(electricity, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        electricity,
        "build_kepco_url",
        lambda base_url, params: "https://example.test/kepco",
    )

    documents = electricity.fetch_kepco_documents(
        electricity.POWER_USAGE_CONTRACT_TYPE_URL,
        {"year": "2026", "month": "01"},
    )

    assert len(documents) == 2
    assert documents[0]["errCd"] == "404"
    assert documents[1]["data"][0]["metro"] == "강원특별자치도"


def test_fetch_kepco_documents_marks_404_without_rows_unavailable(monkeypatch) -> None:
    response_body = '{"errCd":"404","errMsg":"NotFound"}'.encode()

    def fake_urlopen(request, timeout):
        raise HTTPError(
            url=request.full_url,
            code=404,
            msg="Not Found",
            hdrs={},
            fp=BytesIO(response_body),
        )

    monkeypatch.setattr(electricity, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        electricity,
        "build_kepco_url",
        lambda base_url, params: "https://example.test/kepco",
    )

    with pytest.raises(SourcePeriodUnavailable):
        electricity.fetch_kepco_documents(
            electricity.POWER_USAGE_CONTRACT_TYPE_URL,
            {"year": "2027", "month": "06"},
        )


def test_fetch_kepco_documents_retries_empty_401(monkeypatch) -> None:
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return '{"data":[{"year":"2026","month":"08","metro":"전체"}]}'.encode()

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(
                url=request.full_url,
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=BytesIO(b"{}"),
            )
        return FakeResponse()

    monkeypatch.setattr(electricity, "urlopen", fake_urlopen)
    monkeypatch.setattr(electricity.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(electricity.random, "uniform", lambda start, end: 0)
    monkeypatch.setattr(
        electricity,
        "build_kepco_url",
        lambda base_url, params: "https://example.test/kepco",
    )

    documents = electricity.fetch_kepco_documents(
        electricity.POWER_USAGE_CONTRACT_TYPE_URL,
        {"year": "2026", "month": "08"},
    )

    assert calls == 2
    assert documents[0]["data"][0]["month"] == "08"


def test_download_electricity_returns_source_period_download(
    monkeypatch,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_fetch_kepco_documents(
        base_url: str,
        params: dict[str, str],
        *,
        timeout: float = 30,
        max_retries: int = 5,
        base_retry_sleep_seconds: float = 1,
        max_retry_sleep_seconds: float = 60,
    ):
        calls.append((base_url, dict(params)))
        return (
            {
                "totData": [
                    {
                        "year": "2026",
                        "month": "02",
                        "metro": "전체",
                        "city": "전체",
                        "cntr": "주택용",
                        "custCnt": 100,
                        "powerUsage": 200,
                        "bill": 300,
                        "unitCost": 150.5,
                        "cntrPwr": 400,
                    }
                ]
            },
            {
                "data": [
                    {
                        "year": "2026",
                        "month": "02",
                        "metro": "전북특별자치도",
                        "city": "순창군",
                        "cntr": "주택용",
                        "custCnt": 10,
                        "powerUsage": 20,
                        "bill": 30,
                        "unitCost": 1.5,
                        "cntrPwr": 40,
                    },
                    {
                        "year": "2026",
                        "month": "02",
                        "metro": "전북특별자치도",
                        "city": "순창군",
                        "cntr": "농사용",
                        "custCnt": 11,
                        "powerUsage": 21,
                        "bill": 31,
                        "unitCost": 1.6,
                        "cntrPwr": 41,
                    },
                ]
            },
        )

    monkeypatch.setattr(electricity, "fetch_kepco_documents", fake_fetch_kepco_documents)

    result = electricity.download_electricity("202602")

    assert result.source_name == "electricity"
    assert result.source_name_kor == "계약종별 전력사용량"
    assert result.source_org_id == "KEPCO"
    assert result.source_table_id == "powerUsage/contractType.do"
    assert result.raw_table == "electricity"
    assert result.period == "202602"
    assert result.payload_row_count == 2
    assert result.raw_row_count == 2
    assert result.raw_columns == electricity.RAW_COLUMNS
    assert result.payload_chunks[0].request_params == {
        "year": "2026",
        "month": "02",
    }
    assert result.raw_rows[0]["metro"] == "전북특별자치도"
    assert result.raw_rows[0]["city"] == "순창군"
    assert result.raw_rows[0]["cntr"] == "주택용"
    assert result.raw_rows[0]["powerUsage"] == "20"
    assert result.raw_rows[1]["cntr"] == "농사용"
    assert calls == [
        (
            electricity.POWER_USAGE_CONTRACT_TYPE_URL,
            {"year": "2026", "month": "02"},
        )
    ]


def test_download_electricity_can_filter_contract_code(monkeypatch) -> None:
    calls: list[dict[str, str]] = []

    def fake_fetch_kepco_documents(
        base_url: str,
        params: dict[str, str],
        *,
        timeout: float = 30,
        max_retries: int = 5,
        base_retry_sleep_seconds: float = 1,
        max_retry_sleep_seconds: float = 60,
    ):
        calls.append(dict(params))
        return ({"data": []},)

    monkeypatch.setattr(electricity, "fetch_kepco_documents", fake_fetch_kepco_documents)

    result = electricity.download_electricity("202602", contract_code="100")

    assert result.raw_row_count == 0
    assert result.payload_chunks[0].request_params == {
        "year": "2026",
        "month": "02",
        "cntrCd": "100",
    }
    assert calls == [{"year": "2026", "month": "02", "cntrCd": "100"}]


def test_rows_to_raw_rows_preserves_zero_values() -> None:
    raw_rows = electricity.rows_to_raw_rows(
        [
            {
                "year": "2026",
                "month": "02",
                "metro": "전북특별자치도",
                "city": "순창군",
                "cntr": "주택용",
                "custCnt": 0,
                "powerUsage": 0,
                "bill": 0,
                "unitCost": 0,
                "cntrPwr": 0,
            }
        ],
        downloaded_at="2026-07-24T00:00:00+00:00",
    )

    assert raw_rows[0]["custCnt"] == "0"
    assert raw_rows[0]["powerUsage"] == "0"
    assert raw_rows[0]["bill"] == "0"
    assert raw_rows[0]["unitCost"] == "0"
    assert raw_rows[0]["cntrPwr"] == "0"
