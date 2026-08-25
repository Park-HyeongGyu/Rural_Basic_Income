from __future__ import annotations

from rural_basic_income.web.api import data


class ScalarResult:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return iter(self.values)


class FakeConnection:
    def execute(self, statement, parameters=None):
        sql = str(statement)
        if "information_schema.tables" in sql:
            return ScalarResult(
                (
                    "clean_inflow",
                    "clean_inflow_web",
                    "clean_population",
                    "clean_living_population",
                )
            )
        raise AssertionError(f"unexpected SQL: {sql}")


def test_fetch_clean_table_names_hides_od_tables() -> None:
    assert data.fetch_clean_table_names(FakeConnection()) == [
        "clean_inflow_web",
        "clean_population",
        "clean_living_population",
    ]
