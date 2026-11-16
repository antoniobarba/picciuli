"""Recurring transaction endpoints."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, status

from picciuli import ValidationError
from picciuli_api.deps import BookDep
from picciuli_api.schemas.base import Date, PathId
from picciuli_api.schemas.periods import PeriodOut
from picciuli_api.schemas.schedules import (
    CatchUpIn,
    CatchUpOut,
    OccurrenceOut,
    ScheduleCreate,
    ScheduleOut,
    SchedulePost,
    ScheduleUpdate,
)
from picciuli_api.schemas.transactions import TransactionOut

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _check_today(today: dt.date) -> None:
    # Time zones span from UTC-12 to UTC+14, so the user's day is at most one
    # day away from the server's: anything else would post future occurrences.
    utc_today = dt.datetime.now(dt.timezone.utc).date()
    if abs((today - utc_today).days) > 1:
        raise ValidationError("today must be the current day")


@router.get("")
def list_schedules(book: BookDep) -> list[ScheduleOut]:
    """List the recurring transactions, the next due first."""
    return [ScheduleOut.model_validate(s) for s in book.schedules.list()]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_schedule(book: BookDep, body: ScheduleCreate) -> ScheduleOut:
    """Create a recurring transaction."""
    schedule = book.schedules.create(
        body.start,
        [split.to_model() for split in body.splits],
        frequency=body.frequency,
        every=body.every,
        day_of_month=body.day_of_month,
        end=body.end,
        occurrences=body.occurrences,
        mode=body.mode,
        description=body.description,
        notes=body.notes,
        debt=body.debt_model(),
    )
    return ScheduleOut.model_validate(schedule)


@router.get("/occurrences")
def list_occurrences(book: BookDep, start: Date, end: Date) -> list[OccurrenceOut]:
    """Occurrences of active schedules between two days (at most 750 days)."""
    found = book.schedules.occurrences(start, end)
    return [OccurrenceOut.model_validate(o) for o in found]


@router.post("/catch-up")
def catch_up(book: BookDep, body: CatchUpIn) -> CatchUpOut:
    """Create the missing monthly periods and record due automatic occurrences.

    Call it when the app starts, with the user's current day. It is
    idempotent: calling it again the same day changes nothing.
    """
    _check_today(body.today)
    with book.atomic():
        periods = book.periods.ensure_monthly(body.today)
        result = book.schedules.catch_up(body.today)
    return CatchUpOut(
        periods=[PeriodOut.model_validate(p) for p in periods],
        posted=[TransactionOut.model_validate(t) for t in result.posted],
        due=[OccurrenceOut.model_validate(o) for o in result.due],
        failed=[ScheduleOut.model_validate(s) for s in result.failed],
        skipped=[OccurrenceOut.model_validate(o) for o in result.skipped],
    )


@router.get("/{schedule_id:int}")
def get_schedule(book: BookDep, schedule_id: PathId) -> ScheduleOut:
    """Get one recurring transaction."""
    return ScheduleOut.model_validate(book.schedules.get(schedule_id))


@router.patch("/{schedule_id:int}")
def update_schedule(
    book: BookDep, schedule_id: PathId, body: ScheduleUpdate
) -> ScheduleOut:
    """Change a recurring transaction. A `splits` list replaces the template."""
    schedule = book.schedules.update(schedule_id, **body.changes())
    return ScheduleOut.model_validate(schedule)


@router.delete("/{schedule_id:int}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(book: BookDep, schedule_id: PathId) -> None:
    """Delete a recurring transaction; the transactions it recorded are kept."""
    book.schedules.delete(schedule_id)


@router.post("/{schedule_id:int}/post", status_code=status.HTTP_201_CREATED)
def post_occurrence(
    book: BookDep, schedule_id: PathId, body: SchedulePost
) -> TransactionOut:
    """Record the next occurrence, possibly with another day or amount.

    Loan payments are split into principal and interest; credit card
    occurrences get their predicted interest charge or minimum payment unless
    `amount` (and, for payments, `from_account_id`) say otherwise.
    """
    transaction = book.schedules.post(schedule_id, **body.changes())
    return TransactionOut.model_validate(transaction)


@router.post("/{schedule_id:int}/skip")
def skip_occurrence(book: BookDep, schedule_id: PathId) -> ScheduleOut:
    """Move to the following occurrence without recording anything."""
    return ScheduleOut.model_validate(book.schedules.skip(schedule_id))
