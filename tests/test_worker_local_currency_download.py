from __future__ import annotations

from rural_basic_income.worker.sources import local_currency


def test_download_local_currency_returns_source_period_download(monkeypatch) -> None:
    calls: list[dict[str, str]] = []

    def fake_fetch_json_payload(
        base_url: str,
        params: dict[str, str],
        *,
        timeout: float = 30,
        max_retries: int = 5,
        base_retry_sleep_seconds: float = 1,
        max_retry_sleep_seconds: float = 60,
    ) -> dict:
        calls.append(dict(params))
        page = int(params["page"])
        rows = [
            {
                "crtr_ym": "202401",
                "usage_rgn_cd": "11110",
                "emd_cd": "11110000",
                "emd_nm": None,
                "card_use_amt": 0,
                "mbl_use_amt": 10,
                "mbl_user_cnt": 1,
                "par_ag": "02",
                "par_gend": "F",
                "stlm_amt": page * 100,
                "stlm_nocs": page,
            }
        ]
        return {
            "currentCount": 1,
            "data": rows,
            "matchCount": 2,
            "page": page,
            "perPage": 1,
            "totalCount": 999,
        }

    monkeypatch.setattr(
        local_currency,
        "fetch_json_payload",
        fake_fetch_json_payload,
    )

    result = local_currency.download_local_currency(
        "202401",
        per_page=1,
        request_sleep_seconds=0,
    )

    assert result.source_name == "local_currency"
    assert result.source_name_kor == "지역사랑상품권 결제정보"
    assert result.source_org_id == "B190001"
    assert result.source_table_id == "localGiftsPaymentV3/paymentsV3"
    assert result.raw_table == "local_currency"
    assert result.period == "202401"
    assert result.payload_row_count == 2
    assert result.raw_row_count == 2
    assert result.raw_columns == local_currency.RAW_COLUMNS
    assert result.payload_chunks[0].request_params == {
        "page": "1",
        "perPage": "1",
        "cond[crtr_ym::GTE]": "202401",
        "cond[crtr_ym::LTE]": "202401",
    }
    assert result.raw_rows[0]["emd_nm"] == ""
    assert result.raw_rows[0]["card_use_amt"] == "0"
    assert result.raw_rows[1]["stlm_amt"] == "200"
    assert [call["page"] for call in calls] == ["1", "2"]


def test_download_local_currency_can_filter_usage_region_code(monkeypatch) -> None:
    calls: list[dict[str, str]] = []

    def fake_fetch_json_payload(
        base_url: str,
        params: dict[str, str],
        *,
        timeout: float = 30,
        max_retries: int = 5,
        base_retry_sleep_seconds: float = 1,
        max_retry_sleep_seconds: float = 60,
    ) -> dict:
        calls.append(dict(params))
        return {
            "currentCount": 0,
            "data": [],
            "matchCount": 0,
            "page": 1,
            "perPage": 100,
            "totalCount": 999,
        }

    monkeypatch.setattr(
        local_currency,
        "fetch_json_payload",
        fake_fetch_json_payload,
    )

    result = local_currency.download_local_currency(
        "202401",
        per_page=100,
        usage_region_code="11110",
    )

    assert result.raw_row_count == 0
    assert result.payload_chunks[0].request_params == {
        "page": "1",
        "perPage": "100",
        "cond[crtr_ym::GTE]": "202401",
        "cond[crtr_ym::LTE]": "202401",
        "cond[usage_rgn_cd::EQ]": "11110",
    }
    assert calls == [
        {
            "page": "1",
            "perPage": "100",
            "cond[crtr_ym::GTE]": "202401",
            "cond[crtr_ym::LTE]": "202401",
            "cond[usage_rgn_cd::EQ]": "11110",
        }
    ]


def test_validate_payload_rejects_error_payload() -> None:
    try:
        local_currency.validate_payload({"errorCode": "99", "message": "bad request"})
    except local_currency.DataGoKrApiError as exc:
        assert "99" in str(exc)
    else:
        raise AssertionError("expected DataGoKrApiError")
