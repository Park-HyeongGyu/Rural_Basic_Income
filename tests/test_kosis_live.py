import os

import pytest

from rural_basic_income.config import get_settings
from rural_basic_income.pipeline.kosis import fetch_statistics_parameter_data


@pytest.mark.skipif(
    os.environ.get("RUN_KOSIS_API_SMOKE_TEST") != "1",
    reason="set RUN_KOSIS_API_SMOKE_TEST=1 to call the live KOSIS API",
)
def test_kosis_statistics_parameter_api_smoke() -> None:
    settings = get_settings()
    if not settings.kosis_api_key:
        pytest.skip("KOSIS_API_KEY is not set")

    required_env = {
        "orgId": "KOSIS_SMOKE_ORG_ID",
        "tblId": "KOSIS_SMOKE_TBL_ID",
        "itmId": "KOSIS_SMOKE_ITM_ID",
        "objL1": "KOSIS_SMOKE_OBJ_L1",
        "prdSe": "KOSIS_SMOKE_PRD_SE",
    }
    params = {}
    missing = []
    for param_name, env_name in required_env.items():
        value = os.environ.get(env_name)
        if value:
            params[param_name] = value
        else:
            missing.append(env_name)

    if missing:
        pytest.skip(f"missing KOSIS smoke-test parameters: {', '.join(missing)}")

    optional_env = {
        "startPrdDe": "KOSIS_SMOKE_START_PRD_DE",
        "endPrdDe": "KOSIS_SMOKE_END_PRD_DE",
        "newEstPrdCnt": "KOSIS_SMOKE_NEW_EST_PRD_CNT",
    }
    for param_name, env_name in optional_env.items():
        value = os.environ.get(env_name)
        if value:
            params[param_name] = value

    payload = fetch_statistics_parameter_data(params, timeout=30)

    assert isinstance(payload, list)

