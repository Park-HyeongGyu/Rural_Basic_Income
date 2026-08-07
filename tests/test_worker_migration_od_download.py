from __future__ import annotations

from http.client import RemoteDisconnected
from pathlib import Path

import pytest

from rural_basic_income.worker.download import SourcePeriodUnavailable
from rural_basic_income.worker.sources import migration_od


def make_payload(
    *,
    page_no: int = 1,
    num_of_rows: int = 2,
    total_count: int = 1,
    result_code: str = "0",
    result_msg: str = "NORMAL_SERVICE",
    rows=None,
):
    return {
        "Response": {
            "head": {
                "pageNo": str(page_no),
                "numOfRows": str(num_of_rows),
                "totalCount": str(total_count),
                "resultCode": result_code,
                "resultMsg": result_msg,
            },
            "items": "" if rows is None else {"item": rows},
        }
    }


def make_row(
    *,
    period: str = "202601",
    destination_code: str = "1111051500",
    origin_code: str = "5211356000",
    total: str = "3",
    male: str = "1",
    female: str = "2",
):
    row = {
        "statsYm": period,
        "mvinAdmmCd": destination_code,
        "mvinCtpvNm": "서울특별시",
        "mvinSggNm": "종로구",
        "mvinDongNm": "청운효자동",
        "mvtAdmmCd": origin_code,
        "mvtCtpvNm": "전북특별자치도",
        "mvtSggNm": "전주시 덕진구",
        "mvtDongNm": "인후3동",
        "totNmprCnt": total,
        "maleNmprCnt": male,
        "femlNmprCnt": female,
    }
    for sex in ("male", "feml"):
        for age in range(111):
            row[f"{sex}{age}AgeNmprCnt"] = "0"
    row["male24AgeNmprCnt"] = male
    row["feml24AgeNmprCnt"] = female
    return row


def test_parse_response_items_accepts_dict_and_list() -> None:
    row = make_row()

    assert migration_od.parse_response_items(make_payload(rows=row)) == (row,)
    assert migration_od.parse_response_items(make_payload(rows=[row, row])) == (
        row,
        row,
    )


def test_fetch_scope_pages_paginates_and_validates_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [
        make_payload(
            page_no=1,
            num_of_rows=1,
            total_count=2,
            rows=[make_row(destination_code="1111051500", origin_code="5211356000")],
        ),
        make_payload(
            page_no=2,
            num_of_rows=1,
            total_count=2,
            rows=[make_row(destination_code="1111053000", origin_code="5211357000")],
        ),
    ]

    def fake_fetch_json_payload(params, **kwargs):
        assert "serviceKey" not in params
        return pages.pop(0)

    monkeypatch.setattr(migration_od, "fetch_json_payload", fake_fetch_json_payload)

    chunks, rows, nodata = migration_od.fetch_scope_pages(
        "202601",
        destination=migration_od.SidoCode("1100000000", "서울", 1),
        origin=migration_od.SidoCode("5200000000", "전북", 13),
        per_page=1,
        request_sleep_seconds=0,
    )

    assert nodata is False
    assert len(chunks) == 2
    assert len(rows) == 2
    assert chunks[0].request_params["mvinAdmmCd"] == "1100000000"
    assert chunks[0].request_params["mvtAdmmCd"] == "5200000000"


def test_fetch_scope_pages_treats_nodata_as_empty_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        migration_od,
        "fetch_json_payload",
        lambda params, **kwargs: make_payload(
            result_code="3",
            result_msg="NODATA_ERROR",
            rows=None,
            total_count=0,
        ),
    )

    chunks, rows, nodata = migration_od.fetch_scope_pages(
        "202601",
        destination=migration_od.SidoCode("1100000000", "서울", 1),
        origin=migration_od.SidoCode("5200000000", "전북", 13),
        request_sleep_seconds=0,
    )

    assert nodata is True
    assert len(chunks) == 1
    assert rows == []


def test_fetch_migration_od_page_treats_invalid_parameter_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        migration_od,
        "fetch_json_payload",
        lambda params, **kwargs: make_payload(
            result_code="10",
            result_msg="INVALID_REQUEST_PARAMETER_ERROR",
            rows=None,
            total_count=0,
        ),
    )

    with pytest.raises(SourcePeriodUnavailable, match="INVALID_REQUEST_PARAMETER"):
        migration_od.fetch_migration_od_page(
            "202608",
            destination_code="1100000000",
            origin_code="1100000000",
        )


def test_fetch_json_payload_retries_remote_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    class ResponseStub:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return b'{"Response":{"head":{"resultCode":"0"},"items":""}}'

    def fake_urlopen(request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RemoteDisconnected("Remote end closed connection without response")
        return ResponseStub()

    monkeypatch.setattr(
        migration_od,
        "build_migration_od_url",
        lambda params: "https://example.test",
    )
    monkeypatch.setattr(migration_od, "urlopen", fake_urlopen)

    payload = migration_od.fetch_json_payload(
        {"pageNo": "1"},
        max_retries=1,
        base_retry_sleep_seconds=0,
    )

    assert attempts == 2
    assert payload["Response"]["head"]["resultCode"] == "0"


def test_fetch_json_payload_exhausts_remote_disconnect_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request, timeout):
        raise RemoteDisconnected("Remote end closed connection without response")

    monkeypatch.setattr(
        migration_od,
        "build_migration_od_url",
        lambda params: "https://example.test",
    )
    monkeypatch.setattr(migration_od, "urlopen", fake_urlopen)

    with pytest.raises(SourcePeriodUnavailable, match="Remote end closed"):
        migration_od.fetch_json_payload(
            {"pageNo": "1"},
            max_retries=1,
            base_retry_sleep_seconds=0,
        )


def test_download_migration_od_marks_all_nodata_month_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code_path = tmp_path / "codes.csv"
    code_path.write_text(
        "api_code,region_sido,request_order\n"
        "1100000000,서울,1\n"
        "5200000000,전북,2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migration_od, "load_sido_codes", lambda path: (
        migration_od.SidoCode("1100000000", "서울", 1),
        migration_od.SidoCode("5200000000", "전북", 2),
    ))
    monkeypatch.setattr(
        migration_od,
        "fetch_scope_pages",
        lambda *args, **kwargs: ([], [], True),
    )

    with pytest.raises(SourcePeriodUnavailable):
        migration_od.download_migration_od(
            "202601",
            sido_codes_path=code_path,
            request_sleep_seconds=0,
        )


def test_rows_to_raw_rows_preserves_all_raw_columns() -> None:
    raw_rows = migration_od.rows_to_raw_rows([make_row()], downloaded_at="now")

    assert len(raw_rows) == 1
    assert tuple(raw_rows[0]) == migration_od.RAW_COLUMNS
    assert raw_rows[0]["statsYm"] == "202601"
    assert raw_rows[0]["male24AgeNmprCnt"] == "1"
    assert raw_rows[0]["downloaded_at"] == "now"
