"""Recurring transactions: templates of splits repeated on a schedule."""

from __future__ import annotations

import builtins
import datetime as dt
import enum
from collections.abc import Iterator, Sequence
from typing import TypeVar

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from picciuli import _calendar
from picciuli import _validation as v
from picciuli._db.queries import get_row, to_schedule, to_transaction
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import ScheduleRow, ScheduleSplitRow, TransactionRow
from picciuli.errors import ConflictError, NotFoundError, ValidationError
from picciuli.limits import (
    MAX_CATCH_UP,
    MAX_ID,
    MAX_PROJECTION_DAYS,
    MAX_SCHEDULE_EVERY,
)
from picciuli.model import (
    UNSET,
    AccountSplit,
    CatchUp,
    ExternalSplit,
    Occurrence,
    Schedule,
    ScheduleFrequency,
    ScheduleMode,
    Split,
    Transaction,
    Unset,
)
from picciuli.services.transactions import _validated_splits

__all__ = ["ScheduleService"]

_E = TypeVar("_E", bound=enum.Enum)

_MONTHLY = (ScheduleFrequency.MONTHLY, ScheduleFrequency.YEARLY)


def _choice(enum_type: type[_E], value: object, label: str) -> _E:
    try:
        return enum_type(value)
    except ValueError:
        allowed = ", ".join(str(item.value) for item in enum_type)
        raise ValidationError(
            f"invalid {label} {value!r}; expected one of: {allowed}"
        ) from None


def _every(value: object) -> int:
    result = v.integer(value, "every")
    if not 1 <= result <= MAX_SCHEDULE_EVERY:
        raise ValidationError(f"every must be between 1 and {MAX_SCHEDULE_EVERY}")
    return result


def _occurrences(value: object) -> int | None:
    if value is None:
        return None
    result = v.integer(value, "occurrences")
    if not 1 <= result <= MAX_ID:
        raise ValidationError("occurrences must be at least 1")
    return result


def _day_of_month(
    frequency: ScheduleFrequency, value: object, anchor: dt.date | None
) -> int | None:
    if frequency not in _MONTHLY:
        if value is not None:
            raise ValidationError(
                "day of month only applies to monthly and yearly schedules"
            )
        return None
    if value is None:
        if anchor is None:
            raise ValidationError("a day of month is needed")
        return anchor.day
    result = v.integer(value, "day of month")
    if not 1 <= result <= 31:
        raise ValidationError("day of month must be between 1 and 31")
    return result


def _template(
    session: Session, day: dt.date, splits: object
) -> builtins.list[ScheduleSplitRow]:
    if isinstance(splits, Sequence) and not isinstance(splits, (str, bytes)):
        for position, split in enumerate(splits, start=1):
            if isinstance(split, AccountSplit) and (
                split.security_id is not None or split.quantity is not None
            ):
                raise ValidationError(
                    f"split {position}: recurring transactions cannot move shares"
                )
    return [
        ScheduleSplitRow(
            position=row.position,
            account_id=row.account_id,
            category_id=row.category_id,
            amount=row.amount,
            memo=row.memo,
        )
        for row in _validated_splits(session, day, splits)
    ]


def _template_splits(row: ScheduleRow) -> builtins.list[Split]:
    return [
        AccountSplit(s.account_id, s.amount, s.memo)
        if s.account_id is not None
        else ExternalSplit(s.amount, s.category_id, s.memo)
        for s in row.splits
    ]


def _upcoming(row: ScheduleRow, *, start: dt.date | None = None) -> Iterator[dt.date]:
    """The occurrences of `row` from its next one (or from about `start`)."""
    first, remaining = row.next_date, row.remaining
    if first is None:
        return iter(())
    frequency = ScheduleFrequency(row.frequency)
    if start is not None:
        moved, skipped = _calendar.skip_before(
            first, frequency, row.every, row.day_of_month, start
        )
        if remaining is not None:
            remaining -= skipped
        first = moved
    return _calendar.occurrences(
        first,
        frequency,
        row.every,
        row.day_of_month,
        end=row.end_date,
        remaining=remaining,
    )


def _advance(row: ScheduleRow) -> None:
    """Move `row` to its following occurrence, or finish it."""
    upcoming = _upcoming(row)
    next(upcoming, None)
    if row.remaining is not None:
        row.remaining -= 1
    row.next_date = next(upcoming, None)


def _record(
    session: Session,
    row: ScheduleRow,
    day: dt.date,
    splits: object,
    description: str | None,
    notes: str | None,
) -> TransactionRow:
    transaction = TransactionRow(
        date=day,
        description=description,
        notes=notes,
        schedule_id=row.id,
        splits=_validated_splits(session, day, splits),
    )
    session.add(transaction)
    session.flush()
    return transaction


def _check_consistent(row: ScheduleRow) -> None:
    if row.next_date is None:
        return
    if row.end_date is not None and row.next_date > row.end_date:
        raise ValidationError("the next occurrence is after the end day")
    if row.remaining == 0:
        raise ValidationError("occurrences must be at least 1")


class ScheduleService:
    """Create recurring transactions and record their occurrences.

    Obtain it as [`Book.schedules`][picciuli.Book.schedules].

    A [`Schedule`][picciuli.model.Schedule] is a template of splits (any
    transaction that does not move shares: an expense, a salary, a transfer
    to savings, a loan payment with interest...) and a rule saying when it
    repeats. Nothing happens on its own: call
    [`catch_up`][picciuli.services.ScheduleService.catch_up] with the current
    day, typically when an application starts, to record the due occurrences
    of automatic schedules and list those waiting for confirmation.
    Transactions recorded from a schedule keep its id in
    [`Transaction.schedule_id`][picciuli.model.Transaction].
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def create(
        self,
        start: dt.date,
        splits: Sequence[Split],
        *,
        frequency: ScheduleFrequency | str = ScheduleFrequency.MONTHLY,
        every: int = 1,
        day_of_month: int | None = None,
        end: dt.date | None = None,
        occurrences: int | None = None,
        mode: ScheduleMode | str = ScheduleMode.AUTO,
        description: str | None = None,
        notes: str | None = None,
    ) -> Schedule:
        """Create a recurring transaction.

        Args:
            start: Day of the first occurrence.
            splits: Template of the splits, as for
                [`TransactionService.create`][picciuli.services.TransactionService.create],
                without shares.
            frequency: Unit of repetition.
            every: Number of units between two occurrences, for example 2
                with `WEEKLY` for every other week.
            day_of_month: For monthly and yearly schedules, the day of the
                month of the following occurrences (31 for the last day of
                every month); defaults to the day of `start`.
            end: Last day an occurrence may fall on, or `None`.
            occurrences: Number of occurrences before the schedule finishes,
                or `None` for no limit.
            mode: Whether due occurrences are recorded on their own or wait
                for confirmation.
            description: Description of the recorded transactions.
            notes: Notes of the recorded transactions.

        Returns:
            The stored schedule.

        Raises:
            ValidationError: If an argument is invalid, the splits do not
                balance or move shares, or `start` is after `end`.
            NotFoundError: If an account or category does not exist.
            ConflictError: If an account is closed.
        """
        start = v.date(start, "start")
        end = v.optional_date(end, "end")
        v.date_range(start, end)
        frequency = _choice(ScheduleFrequency, frequency, "frequency")
        every = _every(every)
        dom = _day_of_month(frequency, day_of_month, start)
        remaining = _occurrences(occurrences)
        mode = _choice(ScheduleMode, mode, "mode")
        description = v.optional_text(description, "description")
        notes = v.optional_text(notes, "notes")
        with self._uow.session() as session:
            row = ScheduleRow(
                description=description,
                notes=notes,
                frequency=frequency.value,
                every=every,
                day_of_month=dom,
                next_date=start,
                end_date=end,
                remaining=remaining,
                mode=mode.value,
                paused=False,
                last_error=None,
                splits=_template(session, start, splits),
            )
            session.add(row)
            session.flush()
            return to_schedule(row)

    def get(self, schedule_id: int) -> Schedule:
        """Return a schedule.

        Raises:
            NotFoundError: If the schedule does not exist.
        """
        with self._uow.session() as session:
            return to_schedule(get_row(session, ScheduleRow, schedule_id, "schedule"))

    def list(self) -> builtins.list[Schedule]:
        """Return every schedule, the next due first and finished ones last."""
        with self._uow.session() as session:
            rows = session.scalars(
                select(ScheduleRow).order_by(
                    ScheduleRow.next_date.is_(None),
                    ScheduleRow.next_date,
                    ScheduleRow.id,
                )
            )
            return [to_schedule(row) for row in rows]

    def update(
        self,
        schedule_id: int,
        *,
        splits: Sequence[Split] | Unset = UNSET,
        next_date: dt.date | Unset = UNSET,
        frequency: ScheduleFrequency | str | Unset = UNSET,
        every: int | Unset = UNSET,
        day_of_month: int | None | Unset = UNSET,
        end: dt.date | None | Unset = UNSET,
        occurrences: int | None | Unset = UNSET,
        mode: ScheduleMode | str | Unset = UNSET,
        paused: bool | Unset = UNSET,
        description: str | None | Unset = UNSET,
        notes: str | None | Unset = UNSET,
    ) -> Schedule:
        """Change a schedule; arguments left `UNSET` are not modified.

        Transactions already recorded are never changed. Any change clears
        [`last_error`][picciuli.model.Schedule].

        Args:
            schedule_id: The schedule.
            splits: New template of the splits.
            next_date: Day of the next occurrence; setting it restarts a
                finished schedule.
            frequency: Unit of repetition. Changing it to monthly or yearly
                without a `day_of_month` uses the day of the next occurrence.
            every: Number of units between two occurrences.
            day_of_month: Day of the month of monthly and yearly occurrences.
            end: Last day an occurrence may fall on, or `None`.
            occurrences: Occurrences left including the next one, or `None`
                for no limit.
            mode: Automatic or confirmed occurrences.
            paused: Whether the schedule is suspended.
            description: Description of the recorded transactions.
            notes: Notes of the recorded transactions.

        Raises:
            NotFoundError: If the schedule, an account or a category does not
                exist.
            ValidationError: If an argument is invalid, or the next
                occurrence would be after the end day or without occurrences
                left.
            ConflictError: If the new splits use a closed account.
        """
        with self._uow.session() as session:
            row = get_row(session, ScheduleRow, schedule_id, "schedule")
            if not isinstance(next_date, Unset):
                row.next_date = v.date(next_date, "next date")
            old_frequency = ScheduleFrequency(row.frequency)
            new_frequency = (
                old_frequency
                if isinstance(frequency, Unset)
                else _choice(ScheduleFrequency, frequency, "frequency")
            )
            if not isinstance(day_of_month, Unset):
                row.day_of_month = _day_of_month(
                    new_frequency, day_of_month, row.next_date
                )
            elif (new_frequency in _MONTHLY) != (old_frequency in _MONTHLY):
                row.day_of_month = _day_of_month(new_frequency, None, row.next_date)
            row.frequency = new_frequency.value
            if not isinstance(every, Unset):
                row.every = _every(every)
            if not isinstance(end, Unset):
                row.end_date = v.optional_date(end, "end")
            if not isinstance(occurrences, Unset):
                row.remaining = _occurrences(occurrences)
            if not isinstance(mode, Unset):
                row.mode = _choice(ScheduleMode, mode, "mode").value
            if not isinstance(paused, Unset):
                if not isinstance(paused, bool):
                    raise ValidationError("paused must be a boolean")
                row.paused = paused
            if not isinstance(description, Unset):
                row.description = v.optional_text(description, "description")
            if not isinstance(notes, Unset):
                row.notes = v.optional_text(notes, "notes")
            if not isinstance(splits, Unset):
                new_rows = _template(session, row.next_date or dt.date.max, splits)
                row.splits.clear()
                session.flush()
                row.splits.extend(new_rows)
            _check_consistent(row)
            row.last_error = None
            session.flush()
            return to_schedule(row)

    def delete(self, schedule_id: int) -> None:
        """Delete a schedule. The transactions it recorded are kept.

        Raises:
            NotFoundError: If the schedule does not exist.
        """
        with self._uow.session() as session:
            row = get_row(session, ScheduleRow, schedule_id, "schedule")
            session.execute(
                update(TransactionRow)
                .where(TransactionRow.schedule_id == row.id)
                .values(schedule_id=None)
            )
            session.delete(row)

    def occurrences(self, start: dt.date, end: dt.date) -> builtins.list[Occurrence]:
        """List the occurrences of active schedules between two days.

        Paused and finished schedules have none. Occurrences before the next
        one of a schedule are not listed: they are already recorded or
        skipped.

        Args:
            start: First day to include.
            end: Last day to include, at most
                [`MAX_PROJECTION_DAYS`][picciuli.limits.MAX_PROJECTION_DAYS]
                after `start`.

        Returns:
            Occurrences ordered by day, then by schedule.

        Raises:
            ValidationError: If the range is invalid or too long.
        """
        start = v.date(start, "start")
        end = v.date(end, "end")
        v.date_range(start, end)
        if (end - start).days > MAX_PROJECTION_DAYS:
            raise ValidationError(
                f"the range cannot be longer than {MAX_PROJECTION_DAYS} days"
            )
        result: builtins.list[Occurrence] = []
        with self._uow.session() as session:
            rows = session.scalars(
                select(ScheduleRow).where(
                    ScheduleRow.paused.is_(False),
                    ScheduleRow.next_date.is_not(None),
                    ScheduleRow.next_date <= end,
                )
            )
            for row in rows:
                for day in _upcoming(row, start=start):
                    if day > end:
                        break
                    if day >= start:
                        result.append(Occurrence(row.id, day))
        result.sort(key=lambda o: (o.date, o.schedule_id))
        return result

    def post(
        self,
        schedule_id: int,
        *,
        date: dt.date | None = None,
        splits: Sequence[Split] | None = None,
        description: str | None | Unset = UNSET,
        notes: str | None | Unset = UNSET,
    ) -> Transaction:
        """Record the next occurrence of a schedule and move to the following one.

        The arguments change only this transaction, not the schedule: use
        them for a bill whose amount varies, or that was paid on another day.

        Args:
            schedule_id: The schedule.
            date: Day of the transaction; defaults to the day of the next
                occurrence.
            splits: Splits of the transaction; default to the template.
            description: Description; defaults to the schedule's.
            notes: Notes; default to the schedule's.

        Returns:
            The recorded transaction.

        Raises:
            NotFoundError: If the schedule, an account or a category does not
                exist.
            ConflictError: If the schedule has finished or an account is
                closed.
            ValidationError: If an argument is invalid or the splits do not
                balance or move shares.
        """
        with self._uow.session() as session:
            row = get_row(session, ScheduleRow, schedule_id, "schedule")
            if row.next_date is None:
                raise ConflictError("the recurring transaction has finished")
            day = row.next_date if date is None else v.date(date, "date")
            if splits is None:
                chosen: object = _template_splits(row)
            else:
                _template(session, day, splits)
                chosen = splits
            transaction = _record(
                session,
                row,
                day,
                chosen,
                row.description
                if isinstance(description, Unset)
                else v.optional_text(description, "description"),
                row.notes
                if isinstance(notes, Unset)
                else v.optional_text(notes, "notes"),
            )
            _advance(row)
            row.last_error = None
            session.flush()
            return to_transaction(transaction)

    def skip(self, schedule_id: int) -> Schedule:
        """Move a schedule to its following occurrence without recording anything.

        Raises:
            NotFoundError: If the schedule does not exist.
            ConflictError: If the schedule has finished.
        """
        with self._uow.session() as session:
            row = get_row(session, ScheduleRow, schedule_id, "schedule")
            if row.next_date is None:
                raise ConflictError("the recurring transaction has finished")
            _advance(row)
            row.last_error = None
            session.flush()
            return to_schedule(row)

    def catch_up(self, today: dt.date) -> CatchUp:
        """Record every due occurrence of automatic schedules.

        Each automatic schedule that is not paused records its occurrences up
        to `today`, each on its own day. When one cannot be recorded (for
        example because an account was closed) the schedule stops there and
        keeps the reason in `last_error`; the other schedules go on.
        Schedules waiting for confirmation are not changed: their due
        occurrences are returned instead.

        At most [`MAX_CATCH_UP`][picciuli.limits.MAX_CATCH_UP] occurrences
        are recorded and listed; call again to continue.

        Args:
            today: The current day of the user.

        Returns:
            What was recorded, what waits for confirmation and what failed.

        Raises:
            ValidationError: If `today` is not a date.
        """
        today = v.date(today, "today")
        posted: builtins.list[Transaction] = []
        due: builtins.list[Occurrence] = []
        failed: builtins.list[Schedule] = []
        with self._uow.session() as session:
            rows = session.scalars(
                select(ScheduleRow)
                .where(
                    ScheduleRow.paused.is_(False),
                    ScheduleRow.next_date.is_not(None),
                    ScheduleRow.next_date <= today,
                )
                .order_by(ScheduleRow.next_date, ScheduleRow.id)
            ).all()
            for row in rows:
                if row.mode == ScheduleMode.CONFIRM.value:
                    for day in _upcoming(row):
                        if day > today or len(due) >= MAX_CATCH_UP:
                            break
                        due.append(Occurrence(row.id, day))
                    continue
                while (
                    row.next_date is not None
                    and row.next_date <= today
                    and len(posted) < MAX_CATCH_UP
                ):
                    try:
                        with session.begin_nested():
                            transaction = _record(
                                session,
                                row,
                                row.next_date,
                                _template_splits(row),
                                row.description,
                                row.notes,
                            )
                    except (ValidationError, ConflictError, NotFoundError) as exc:
                        row.last_error = str(exc)
                        failed.append(to_schedule(row))
                        break
                    posted.append(to_transaction(transaction))
                    _advance(row)
                    row.last_error = None
            session.flush()
        posted.sort(key=lambda t: (t.date, t.id))
        due.sort(key=lambda o: (o.date, o.schedule_id))
        return CatchUp(posted=tuple(posted), due=tuple(due), failed=tuple(failed))
