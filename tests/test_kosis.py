from urllib.parse import parse_qs, urlparse

import pytest

from rural_basic_income.config import Settings
import rural_basic_income.pipeline.kosis as kosis
from rural_basic_income.pipeline.kosis import (
    KosisApiKeyMissing,
    build_statistics_parameter_url,
)


def test_settings_accepts_kosis_api_key() -> None:
    settings = Settings(_env_file=None, kosis_api_key="test-key")

    assert settings.kosis_api_key == "test-key"


def test_build_statistics_parameter_url_includes_required_defaults() -> None:
    url = build_statistics_parameter_url(
        {
            "orgId": "101",
            "tblId": "DT_TEST",
            "itmId": "T1",
            "objL1": "ALL",
            "prdSe": "M",
            "startPrdDe": "202401",
            "endPrdDe": "202401",
        },
        api_key="test-key",
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "kosis.kr"
    assert parsed.path == "/openapi/Param/statisticsParameterData.do"
    assert query["method"] == ["getList"]
    assert query["apiKey"] == ["test-key"]
    assert query["format"] == ["json"]
    assert query["jsonVD"] == ["Y"]
    assert query["orgId"] == ["101"]
    assert query["tblId"] == ["DT_TEST"]
    assert query["prdSe"] == ["M"]


def test_build_statistics_parameter_url_requires_api_key() -> None:
    settings = Settings(_env_file=None, kosis_api_key=None)

    with pytest.raises(KosisApiKeyMissing):
        build_statistics_parameter_url({}, settings=settings)


def test_fetch_statistics_parameter_data_decodes_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'[{"PRD_DE": "202401", "DT": "100"}]'

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        assert timeout == 10
        return FakeResponse()

    monkeypatch.setattr(kosis, "urlopen", fake_urlopen)

    payload = kosis.fetch_statistics_parameter_data(
        {
            "orgId": "101",
            "tblId": "DT_TEST",
            "itmId": "T1",
            "objL1": "ALL",
            "prdSe": "M",
        },
        api_key="test-key",
        timeout=10,
    )

    assert payload == [{"PRD_DE": "202401", "DT": "100"}]
