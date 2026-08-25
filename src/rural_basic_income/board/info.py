from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import bleach
import markdown
from sqlalchemy import text
from sqlalchemy.engine import Connection


LIST_INFO_POSTS_SQL = text(
    """
    SELECT
        id,
        title,
        created_at
    FROM board.info
    ORDER BY created_at DESC, id DESC
    """
)

GET_INFO_POST_SQL = text(
    """
    SELECT
        id,
        title,
        body_markdown,
        body_html,
        created_at
    FROM board.info
    WHERE id = :info_id
    """
)

INSERT_INFO_POST_SQL = text(
    """
    INSERT INTO board.info (
        title,
        body_markdown,
        body_html
    )
    VALUES (
        :title,
        :body_markdown,
        :body_html
    )
    RETURNING
        id,
        title,
        body_markdown,
        body_html,
        created_at
    """
)

ALLOWED_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "td": ["align"],
    "th": ["align"],
}
ALLOWED_PROTOCOLS = {"http", "https", "mailto"}


class InfoPostError(ValueError):
    """Raised when an info post payload cannot be stored."""


def ensure_info_schema(connection: Connection) -> None:
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS board"))
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS board.info (
                id bigserial PRIMARY KEY,
                title text NOT NULL,
                body_markdown text NOT NULL,
                body_html text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    )
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS info_created_at_idx
            ON board.info (created_at DESC, id DESC)
            """
        )
    )


def render_markdown(body_markdown: str) -> str:
    rendered = markdown.markdown(
        body_markdown,
        extensions=["fenced_code", "tables", "nl2br"],
        output_format="html5",
    )
    cleaned = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    return bleach.linkify(cleaned)


def normalize_info_payload(payload: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(payload, Mapping):
        raise InfoPostError("info post payload must be an object")

    title = str(payload.get("title") or "").strip()
    if not title:
        raise InfoPostError("title must not be empty")

    body_markdown = str(payload.get("body_markdown") or "").strip()
    if not body_markdown:
        raise InfoPostError("body_markdown must not be empty")

    return {
        "title": title[:200],
        "body_markdown": body_markdown,
        "body_html": render_markdown(body_markdown),
    }


def serialize_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def parse_info_id(value: int | str) -> int:
    try:
        info_id = int(value)
    except (TypeError, ValueError) as exc:
        raise InfoPostError("invalid info post id") from exc
    if info_id < 1:
        raise InfoPostError("invalid info post id")
    return info_id


def info_post_row_to_dict(
    row: Mapping[str, Any],
    *,
    include_body: bool,
) -> dict[str, Any]:
    response = {
        "id": int(row["id"]),
        "title": row["title"],
        "created_at": serialize_datetime(row.get("created_at")),
    }
    if include_body:
        response["body_markdown"] = row["body_markdown"]
        response["body_html"] = row["body_html"]
    return response


def list_info_posts(connection: Connection) -> tuple[dict[str, Any], ...]:
    ensure_info_schema(connection)
    rows = connection.execute(LIST_INFO_POSTS_SQL).mappings()
    return tuple(
        info_post_row_to_dict(row, include_body=False)
        for row in rows
    )


def get_info_post(
    connection: Connection,
    info_id: int | str,
) -> dict[str, Any] | None:
    ensure_info_schema(connection)
    row = (
        connection.execute(GET_INFO_POST_SQL, {"info_id": parse_info_id(info_id)})
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    return info_post_row_to_dict(row, include_body=True)


def create_info_post(
    connection: Connection,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    ensure_info_schema(connection)
    normalized = normalize_info_payload(payload)
    row = (
        connection.execute(INSERT_INFO_POST_SQL, normalized)
        .mappings()
        .one()
    )
    return info_post_row_to_dict(row, include_body=True)
