from __future__ import annotations

from textwrap import dedent

import pytest

from rural_basic_income.board.info import (
    InfoPostError,
    normalize_info_payload,
    parse_info_id,
    render_markdown,
)


def test_render_markdown_keeps_basic_markup_and_strips_script() -> None:
    html = render_markdown(
        dedent(
            """
        # 제목

        **굵게** <script>alert("x")</script>

        | a | b |
        | - | - |
        | 1 | 2 |
        """
        )
    )

    assert "<h1>" in html
    assert "<strong>" in html
    assert "<table>" in html
    assert "<script>" not in html


def test_normalize_info_payload_requires_title_and_body() -> None:
    with pytest.raises(InfoPostError):
        normalize_info_payload({"title": "", "body_markdown": "본문"})

    with pytest.raises(InfoPostError):
        normalize_info_payload({"title": "제목", "body_markdown": ""})


def test_normalize_info_payload_truncates_title() -> None:
    normalized = normalize_info_payload(
        {
            "title": "가" * 250,
            "body_markdown": "본문",
        }
    )

    assert len(normalized["title"]) == 200
    assert normalized["body_markdown"] == "본문"
    assert "<p>본문</p>" in normalized["body_html"]


def test_parse_info_id_rejects_invalid_values() -> None:
    assert parse_info_id("7") == 7

    with pytest.raises(InfoPostError):
        parse_info_id("0")

    with pytest.raises(InfoPostError):
        parse_info_id("abc")
