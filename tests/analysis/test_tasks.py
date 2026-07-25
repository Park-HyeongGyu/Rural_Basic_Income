from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pandas as pd
import pytest

from rural_basic_income.analysis.cache import (
    claim_running_task,
    make_analysis_cache_key,
    read_cached_result,
    read_running_task_id,
)
from rural_basic_income.analysis.data_loader import LoadedAnalysisPanel
from rural_basic_income.analysis.panel import AnalysisPanel
from rural_basic_income.analysis.regression import (
    CoefficientEstimate,
    EventStudyPoint,
    EventStudyResult,
    TwfeResult,
)
from rural_basic_income.analysis.tasks import run_analysis_job


class MappingOneResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one(self):
        return self.row


class FakeConnection:
    def execute(self, statement, parameters=None):
        sql = str(statement)
        if "metadata.download_status" in sql:
            return MappingOneResult(
                {
                    "success_count": 2,
                    "latest_success_at": "2026-07-25 00:00:00+00",
                }
            )
        raise AssertionError(f"unexpected SQL: {sql}")


class DictRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_count = 0

    def get(self, key: str):
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.set_count += 1

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        return int(existed)

    def eval(self, script: str, numkeys: int, key: str, task_id: str) -> int:
        if self.values.get(key) == task_id:
            return self.delete(key)
        return 0


@dataclass(frozen=True)
class SettingsStub:
    redis_url: str = "redis://127.0.0.1:6379/0"
    analysis_cache_ttl_seconds: int = 60


def make_payload(*, force: bool = False) -> dict:
    return {
        "outcome": {
            "table": "clean.clean_population",
            "variable": "population",
            "filters": {},
        },
        "period": {
            "start": "202501",
            "end": "202503",
            "normalization_base": "202501",
        },
        "treatments": [
            {
                "region_sido": "전북",
                "region_sigungu": "임실군",
                "treatment_period": "202502",
            }
        ],
        "controls": [
            {"region_sido": "전북", "region_sigungu": "고창군"},
        ],
        "force": force,
    }


def make_loaded_panel():
    data = pd.DataFrame(
        [
            {
                "region_id": "전북::임실군",
                "period": "202501",
                "normalized_value": 1.0,
            },
            {
                "region_id": "전북::고창군",
                "period": "202501",
                "normalized_value": 1.0,
            },
        ]
    )
    panel = AnalysisPanel(
        data=data,
        warnings=(),
        missing_region_periods=(),
    )
    return LoadedAnalysisPanel(
        outcome=SimpleNamespace(table_name="clean_population"),
        table_metadata=SimpleNamespace(table_name="clean_population"),
        panel=panel,
    )


def make_twfe_result() -> TwfeResult:
    return TwfeResult(
        coefficient=CoefficientEstimate(
            estimate=0.2,
            standard_error=0.01,
            t_statistic=20.0,
            p_value=0.0,
            ci_lower_95=0.18,
            ci_upper_95=0.22,
        ),
        n_observations=2,
        n_regions=2,
        n_clusters=2,
        n_periods=1,
    )


def make_event_study_result() -> EventStudyResult:
    return EventStudyResult(
        points=(
            EventStudyPoint(
                event_time=-1,
                estimate=0.0,
                standard_error=None,
                t_statistic=None,
                p_value=None,
                ci_lower_95=None,
                ci_upper_95=None,
                is_reference=True,
                treated_region_count=1,
                observation_count=1,
            ),
        ),
        n_observations=2,
        n_regions=2,
        n_clusters=2,
        n_periods=1,
    )


def test_run_analysis_job_writes_success_cache() -> None:
    redis_client = DictRedis()
    payload = make_payload()
    loader_calls = []

    def panel_loader(connection, outcome, spec):
        loader_calls.append((outcome, spec))
        return make_loaded_panel()

    result = run_analysis_job(
        payload,
        connection=FakeConnection(),
        redis_client=redis_client,
        settings=SettingsStub(),
        panel_loader=panel_loader,
        twfe_runner=lambda _panel: make_twfe_result(),
        event_study_runner=lambda _panel: make_event_study_result(),
    )

    assert result["status"] == "success"
    assert result["cached"] is False
    assert result["result"]["twfe"]["coefficient"]["estimate"] == 0.2
    assert redis_client.set_count == 1
    assert loader_calls
    assert read_cached_result(redis_client, result["cache_key"]) == result["result"]


def test_run_analysis_job_clears_running_lock_after_success() -> None:
    redis_client = DictRedis()
    payload = make_payload()
    data_revision = "metadata.download_status:2:2026-07-25 00:00:00+00"
    cache_key = make_analysis_cache_key(payload, data_revision=data_revision)
    claim_running_task(redis_client, cache_key, "task-1", ttl_seconds=60)

    run_analysis_job(
        payload,
        connection=FakeConnection(),
        redis_client=redis_client,
        settings=SettingsStub(),
        panel_loader=lambda _connection, _outcome, _spec: make_loaded_panel(),
        twfe_runner=lambda _panel: make_twfe_result(),
        event_study_runner=lambda _panel: make_event_study_result(),
        running_task_id="task-1",
    )

    assert read_running_task_id(redis_client, cache_key) is None


def test_run_analysis_job_returns_cache_hit_without_loading_panel() -> None:
    redis_client = DictRedis()
    payload = make_payload()
    data_revision = "metadata.download_status:2:2026-07-25 00:00:00+00"
    cache_key = make_analysis_cache_key(payload, data_revision=data_revision)
    redis_client.setex(
        f"rbi:analysis:result:{cache_key}",
        60,
        '{"cached_result": true}',
    )

    def fail_loader(*args, **kwargs):
        raise AssertionError("panel should not load on cache hit")

    result = run_analysis_job(
        payload,
        connection=FakeConnection(),
        redis_client=redis_client,
        settings=SettingsStub(),
        panel_loader=fail_loader,
    )

    assert result["cached"] is True
    assert result["result"] == {"cached_result": True}


def test_force_rerun_ignores_cache_but_preserves_old_cache_on_failure() -> None:
    redis_client = DictRedis()
    payload = make_payload(force=True)
    data_revision = "metadata.download_status:2:2026-07-25 00:00:00+00"
    cache_key = make_analysis_cache_key(payload, data_revision=data_revision)
    redis_client.setex(
        f"rbi:analysis:result:{cache_key}",
        60,
        '{"old_success": true}',
    )
    claim_running_task(redis_client, cache_key, "task-1", ttl_seconds=60)

    def fail_loader(*args, **kwargs):
        raise RuntimeError("analysis failed")

    with pytest.raises(RuntimeError, match="analysis failed"):
        run_analysis_job(
            payload,
            connection=FakeConnection(),
            redis_client=redis_client,
            settings=SettingsStub(),
            panel_loader=fail_loader,
            running_task_id="task-1",
        )

    assert read_cached_result(redis_client, cache_key) == {"old_success": True}
    assert read_running_task_id(redis_client, cache_key) is None
