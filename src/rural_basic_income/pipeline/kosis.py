from __future__ import annotations

import json
import random
import time
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rural_basic_income.config import Settings, get_settings

KOSIS_STATISTICS_PARAMETER_URL = (
    "https://kosis.kr/openapi/Param/statisticsParameterData.do"
)
RETRYABLE_HTTP_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
RETRYABLE_MESSAGE_MARKERS = (
    "too many",
    "rate limit",
    "ratelimit",
    "quota",
    "exceeded",
    "timeout",
    "timed out",
    "temporarily",
    "try again",
    "잠시",
    "초과",
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


def is_retryable_message(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in RETRYABLE_MESSAGE_MARKERS)


def retry_sleep_seconds(
    attempt_index: int,
    *,
    base_sleep_seconds: float,
    max_sleep_seconds: float,
) -> float:
    exponential_sleep = base_sleep_seconds * (2 ** attempt_index)
    jitter = random.uniform(0, base_sleep_seconds)
    return min(exponential_sleep + jitter, max_sleep_seconds)


def sleep_before_retry(
    attempt_index: int,
    *,
    base_sleep_seconds: float,
    max_sleep_seconds: float,
) -> None:
    time.sleep(
        retry_sleep_seconds(
            attempt_index,
            base_sleep_seconds=base_sleep_seconds,
            max_sleep_seconds=max_sleep_seconds,
        )
    )


def read_http_error_body(exc: HTTPError) -> str:
    try:
        return exc.read().decode("utf-8-sig", errors="replace")
    except Exception:
        return ""


def fetch_statistics_parameter_data(
    params: Mapping[str, str],
    *,
    api_key: str | None = None,
    timeout: float = 30,
    max_retries: int = 5,
    base_retry_sleep_seconds: float = 1,
    max_retry_sleep_seconds: float = 60,
) -> list[dict[str, Any]]:
    url = build_statistics_parameter_url(params, api_key=api_key)
    request = Request(
        url,
        headers={"User-Agent": "rural-basic-income/0.2.0"},
    )

    for attempt_index in range(max_retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                response_text = response.read().decode("utf-8-sig", errors="replace")
        except HTTPError as exc:
            response_text = read_http_error_body(exc)
            should_retry = (
                exc.code in RETRYABLE_HTTP_STATUS_CODES
                or is_retryable_message(response_text)
            )
            if should_retry and attempt_index < max_retries:
                sleep_before_retry(
                    attempt_index,
                    base_sleep_seconds=base_retry_sleep_seconds,
                    max_sleep_seconds=max_retry_sleep_seconds,
                )
                continue
            message = f"KOSIS request failed with HTTP {exc.code}"
            if response_text:
                message = f"{message}: {response_text[:300]}"
            raise KosisApiError(message) from exc
        except (TimeoutError, URLError) as exc:
            if attempt_index < max_retries:
                sleep_before_retry(
                    attempt_index,
                    base_sleep_seconds=base_retry_sleep_seconds,
                    max_sleep_seconds=max_retry_sleep_seconds,
                )
                continue
            raise KosisApiError("KOSIS request failed") from exc

        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            if is_retryable_message(response_text) and attempt_index < max_retries:
                sleep_before_retry(
                    attempt_index,
                    base_sleep_seconds=base_retry_sleep_seconds,
                    max_sleep_seconds=max_retry_sleep_seconds,
                )
                continue
            raise KosisApiError("KOSIS response was not valid JSON") from exc

        if isinstance(payload, list):
            return payload

        payload_text = json.dumps(payload, ensure_ascii=False)
        if is_retryable_message(payload_text) and attempt_index < max_retries:
            sleep_before_retry(
                attempt_index,
                base_sleep_seconds=base_retry_sleep_seconds,
                max_sleep_seconds=max_retry_sleep_seconds,
            )
            continue

        raise KosisApiError("KOSIS response JSON was not a list")

    raise KosisApiError("KOSIS request failed after retry attempts")
