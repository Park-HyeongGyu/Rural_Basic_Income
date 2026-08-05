from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import pytest

from rural_basic_income.worker import raw_writer
from rural_basic_income.worker.download import PayloadChunk, SourcePeriodDownload


class FakeResult:
    def __init__(
        self,
        *,
        rows: Iterable[tuple[Any, ...]] = (),
        scalar: Any = None,
    ) -> None:
        self._rows = tuple(rows)
        self._scalar = scalar

    def __iter__(self):
        return iter(self._rows)

    def scalar_one_or_none(self):
        return self._scalar


class RecordingConnection:
    def __init__(
        self,
        *,
        successful_row_count: int | None = None,
        raw_table_columns: dict[str, list[str]] | None = None,
    ) -> None:
        self.successful_row_count = successful_row_count
        self.raw_table_columns = raw_table_columns or {}
        self.calls: list[tuple[str, Any]] = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))

        if (
            "FROM metadata.download_status" in sql
            and "SELECT row_count" in sql
        ):
            return FakeResult(scalar=self.successful_row_count)

        if "FROM information_schema.tables" in sql:
            table_name = parameters["table_name"]
            exists = table_name in self.raw_table_columns
            return FakeResult(scalar=1 if exists else None)

        if "FROM information_schema.columns" in sql:
            table_name = parameters["table_name"]
            columns = self.raw_table_columns.get(table_name, [])
            return FakeResult(rows=((column,) for column in columns))

        return FakeResult()


class RecordingTransaction:
    def __init__(self, connection: RecordingConnection) -> None:
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        return False


class RecordingEngine:
    def __init__(self, connection: RecordingConnection) -> None:
        self.connection = connection

    def begin(self):
        return RecordingTransaction(self.connection)


def make_download() -> SourcePeriodDownload:
    raw_columns = ("시점", "행정구역", "값", "downloaded_at")
    return SourcePeriodDownload(
        source_name="unit_source",
        source_name_kor="테스트 원천",
        source_org_id="ORG",
        source_table_id="TABLE",
        raw_table="unit_raw",
        period="202604",
        payload_chunks=(
            PayloadChunk(
                request_params={"period": "202604", "지역": "전북"},
                response_payload=({"원본": "값"}, {"원본": "다음"}),
            ),
        ),
        raw_columns=raw_columns,
        raw_rows=(
            {
                "시점": "202604",
                "행정구역": "전북 순창군",
                "값": "10",
                "downloaded_at": "2026-07-24T00:00:00+00:00",
            },
            {
                "시점": "202604",
                "행정구역": "전북 임실군",
                "값": "20",
                "downloaded_at": "2026-07-24T00:00:00+00:00",
            },
        ),
    )


def matching_calls(
    connection: RecordingConnection,
    needle: str,
) -> list[tuple[str, Any]]:
    return [
        (sql, parameters)
        for sql, parameters in connection.calls
        if needle in sql
    ]


def test_write_source_period_download_inserts_payload_raw_and_metadata() -> None:
    download = make_download()
    connection = RecordingConnection(
        raw_table_columns={"unit_raw": list(download.raw_columns)}
    )
    engine = RecordingEngine(connection)

    result = raw_writer.write_source_period_download(download, engine=engine)

    assert result.status == "written"
    assert result.row_count == 2

    payload_insert = matching_calls(
        connection,
        "INSERT INTO raw_json.payloads",
    )[0]
    payload_rows = payload_insert[1]
    assert len(payload_rows) == 1
    assert payload_rows[0]["source_name"] == "unit_source"
    assert payload_rows[0]["source_name_kor"] == "테스트 원천"
    assert payload_rows[0]["period"] == "202604"
    assert payload_rows[0]["chunk_index"] == 1
    assert payload_rows[0]["row_count"] == 2
    assert json.loads(payload_rows[0]["request_params"]) == {
        "period": "202604",
        "지역": "전북",
    }
    assert json.loads(payload_rows[0]["response_payload"]) == [
        {"원본": "값"},
        {"원본": "다음"},
    ]

    raw_insert = matching_calls(
        connection,
        'INSERT INTO raw."unit_raw"',
    )[0]
    assert raw_insert[1][0]["col_0"] == "202604"
    assert raw_insert[1][0]["col_1"] == "전북 순창군"
    assert raw_insert[1][0]["col_2"] == "10"

    metadata_insert = matching_calls(
        connection,
        "INSERT INTO metadata.download_status",
    )[0]
    assert metadata_insert[1]["source_name"] == "unit_source"
    assert metadata_insert[1]["period"] == "202604"
    assert metadata_insert[1]["status"] == raw_writer.DOWNLOAD_STATUS_OK
    assert metadata_insert[1]["row_count"] == 2


def test_write_source_period_download_skips_existing_success() -> None:
    download = make_download()
    connection = RecordingConnection(
        successful_row_count=2,
        raw_table_columns={"unit_raw": list(download.raw_columns)},
    )
    engine = RecordingEngine(connection)

    result = raw_writer.write_source_period_download(download, engine=engine)

    assert result.status == "skipped"
    assert result.row_count == 2
    assert not matching_calls(connection, "INSERT INTO raw_json.payloads")
    assert not matching_calls(connection, 'INSERT INTO raw."unit_raw"')
    assert not matching_calls(
        connection,
        'CREATE TABLE IF NOT EXISTS raw."unit_raw"',
    )


def test_write_source_period_download_force_replaces_existing_period() -> None:
    download = make_download()
    connection = RecordingConnection(
        successful_row_count=2,
        raw_table_columns={"unit_raw": list(download.raw_columns)},
    )
    engine = RecordingEngine(connection)

    result = raw_writer.write_source_period_download(
        download,
        engine=engine,
        force=True,
    )

    assert result.status == "written"

    assert matching_calls(connection, "DELETE FROM raw_json.payloads")
    raw_delete = matching_calls(connection, 'DELETE FROM raw."unit_raw"')[0]
    assert raw_delete[1] == {"period": "202604"}
    assert matching_calls(connection, "DELETE FROM metadata.download_status")
    assert matching_calls(connection, "INSERT INTO raw_json.payloads")
    assert matching_calls(connection, 'INSERT INTO raw."unit_raw"')
    assert matching_calls(connection, "INSERT INTO metadata.download_status")


def test_period_delete_predicate_supports_current_sources() -> None:
    assert raw_writer.period_delete_predicate(("시점",), "202604") == (
        '"시점" = :period',
        {"period": "202604"},
    )
    assert raw_writer.period_delete_predicate(("crtr_ym",), "202604") == (
        '"crtr_ym" = :period',
        {"period": "202604"},
    )
    assert raw_writer.period_delete_predicate(("statsYm",), "202604") == (
        '"statsYm" = :period',
        {"period": "202604"},
    )
    assert raw_writer.period_delete_predicate(("period",), "202604") == (
        '"period" = :period',
        {"period": "202604"},
    )
    assert raw_writer.period_delete_predicate(("year", "month"), "202604") == (
        '"year" = :year AND "month" = :month',
        {"year": "2026", "month": "04"},
    )

    with pytest.raises(raw_writer.RawWriterError):
        raw_writer.period_delete_predicate(("unknown_period",), "202604")


def test_quote_identifier_escapes_double_quotes() -> None:
    assert raw_writer.quote_identifier('a"b') == '"a""b"'

    with pytest.raises(raw_writer.RawWriterError):
        raw_writer.quote_identifier("")
