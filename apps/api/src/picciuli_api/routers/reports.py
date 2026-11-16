"""Report endpoints."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from picciuli.limits import MAX_HISTORY_POINTS
from picciuli_api.deps import BookDep
from picciuli_api.schemas.base import QueryDate
from picciuli_api.schemas.reports import HistoryPointOut

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/history")
def history(
    book: BookDep,
    by: Literal["month", "period"] = "month",
    count: Annotated[int, Query(ge=1, le=MAX_HISTORY_POINTS)] = 12,
    offset: Annotated[int, Query(ge=0, le=1200)] = 0,
    today: QueryDate = None,
) -> list[HistoryPointOut]:
    """Income, expenses, category flows and balances, oldest first.

    `by=month` returns `count` calendar months ending `offset` months before
    the current one; `by=period` the latest `count` periods started by today,
    skipping the `offset` most recent. `today` defaults to the server date.
    """
    service = book.history.months if by == "month" else book.history.periods
    points = service(count, offset=offset, today=today)
    return [HistoryPointOut.model_validate(p) for p in points]
