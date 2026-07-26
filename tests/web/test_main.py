from __future__ import annotations

from pathlib import Path

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "rural_basic_income"
    / "web"
    / "templates"
    / "index.html"
)


def test_index_uses_root_relative_static_asset_urls() -> None:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    assert 'data-map-src="/static/maps/sigungu_2023_4q.json?v=' in template
    assert "{{ url_for('static'" not in template
    assert 'href="/static/styles.css?v=' in template
