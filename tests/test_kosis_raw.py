from rural_basic_income.pipeline.kosis_raw import (
    dedupe_preserve_order,
    kosis_rows_to_raw_rows,
    make_chunks,
)


def test_make_chunks() -> None:
    assert make_chunks(["a", "b", "c", "d", "e"], 2) == [
        ["a", "b"],
        ["c", "d"],
        ["e"],
    ]


def test_dedupe_preserve_order() -> None:
    assert dedupe_preserve_order(["11", "26", "11", "00"]) == ["11", "26", "00"]


def test_kosis_rows_to_raw_rows_pivots_items_to_korean_columns() -> None:
    columns, rows = kosis_rows_to_raw_rows(
        [
            {
                "PRD_DE": "202601",
                "C1_OBJ_NM": "행정구역(시군구)별",
                "C1": "00",
                "C1_NM": "전국",
                "ITM_NM": "총인구수",
                "UNIT_NM": "명",
                "DT": "51111158",
            },
            {
                "PRD_DE": "202601",
                "C1_OBJ_NM": "행정구역(시군구)별",
                "C1": "00",
                "C1_NM": "전국",
                "ITM_NM": "남자인구수",
                "UNIT_NM": "명",
                "DT": "25400000",
            },
        ]
    )

    assert columns == [
        "시점",
        "C행정구역(시군구)별",
        "행정구역(시군구)별",
        "총인구수 (명)",
        "남자인구수 (명)",
        "downloaded_at",
    ]
    assert len(rows) == 1
    assert rows[0]["시점"] == "202601"
    assert rows[0]["C행정구역(시군구)별"] == "00"
    assert rows[0]["행정구역(시군구)별"] == "전국"
    assert rows[0]["총인구수 (명)"] == "51111158"
    assert rows[0]["남자인구수 (명)"] == "25400000"

