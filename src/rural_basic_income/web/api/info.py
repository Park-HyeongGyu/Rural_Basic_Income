from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from rural_basic_income.board.info import (
    InfoPostError,
    create_info_post,
    get_info_post,
    list_info_posts,
)
from rural_basic_income.db.connection import get_engine


router = APIRouter(prefix="/api/info", tags=["info"])


@router.get("")
def list_info_items() -> dict[str, Any]:
    try:
        with get_engine().connect() as connection:
            posts = list_info_posts(connection)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    return {"posts": list(posts)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_info_item(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        with get_engine().begin() as connection:
            post = create_info_post(connection, payload)
    except InfoPostError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc)},
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    return {"post": post}


@router.get("/{info_id}")
def get_info_item(info_id: int) -> dict[str, Any]:
    try:
        with get_engine().connect() as connection:
            post = get_info_post(connection, info_id)
    except InfoPostError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc)},
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        ) from exc

    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="info post not found",
        )
    return {"post": post}
