from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rural_basic_income.config import Settings, get_settings

KOSIS_STATISTICS_PARAMETER_URL = (
    "https://kosis.kr/openapi/Param/statisticsParameterData.do"
)


class KosisApiKeyMissing(RuntimeError):
    """Raised when a KOSIS API request is attempted without an API key."""


class KosisApiError(RuntimeError):
    """Raised when KOSIS returns an unusable response."""


def build_statistics_parameter_url(
    params: Mapping[str, str],
    *,
    api_key: str | None = None,
    settings: Settings | None = None,
    base_url: str = KOSIS_STATISTICS_PARAMETER_URL,
) -> str:
    resolved_api_key = api_key or (settings or get_settings()).kosis_api_key
    if not resolved_api_key:
        raise KosisApiKeyMissing("KOSIS_API_KEY is required")

    query = {
        "method": "getList",
        "apiKey": resolved_api_key,
        "format": "json",
        "jsonVD": "Y",
        **params,
    }
    return f"{base_url}?{urlencode(query)}"


def fetch_statistics_parameter_data(
    params: Mapping[str, str],
    *,
    api_key: str | None = None,
    timeout: float = 30,
) -> list[dict[str, Any]]:
    url = build_statistics_parameter_url(params, api_key=api_key)
    request = Request(
        url,
        headers={"User-Agent": "rural-basic-income/0.1.0"},
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            raw_body = response.read()
    except HTTPError as exc:
        raise KosisApiError(f"KOSIS request failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise KosisApiError("KOSIS request failed") from exc

    try:
        payload = json.loads(raw_body.decode("utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise KosisApiError("KOSIS response was not valid JSON") from exc

    if isinstance(payload, list):
        return payload

    raise KosisApiError("KOSIS response JSON was not a list")

