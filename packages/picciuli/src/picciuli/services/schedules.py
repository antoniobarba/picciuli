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
from picciuli._db.tables import (
    AccountRow,
    ScheduleDebtRow,
    ScheduleRow,
    ScheduleSplitRow,
    TransactionRow,
)
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
    DebtLinkKind,
    ExternalSplit,
    Occurrence,
    Schedule,
    ScheduleDebt,
    ScheduleFrequency,
    ScheduleMode,
    Split,
    Transaction,
    Unset,
)
from picciuli.services import debts
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
    return _splits_of(row.splits)


def _splits_of(rows: Sequence[ScheduleSplitRow]) -> builtins.list[Split]:
    return [
        AccountSplit(s.account_id, s.amount, s.memo)
        if s.account_id is not None
        else ExternalSplit(s.amount, s.category_id, s.memo)
        for s in rows
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


def _is_card(row: ScheduleRow) -> bool:
    return row.debt is not None and DebtLinkKind(row.debt.kind) in debts.CARD_KINDS


def _loan_link(debt: object) -> ScheduleDebtRow | None:
    if debt is None:
        return None
    if not isinstance(debt, ScheduleDebt):
        raise ValidationError("debt must be a ScheduleDebt or None")
    kind = _choice(DebtLinkKind, debt.kind, "debt kind")
    if kind is not DebtLinkKind.LOAN_PAYMENT:
        raise ValidationError(
            "credit card interest and minimum payments are proposed by the debt "
            "terms of the card"
        )
    category = debt.interest_category_id
    link = ScheduleDebtRow(
        account_id=v.identifier(debt.account_id, "debt account id"),
        kind=kind.value,
        interest_category_id=None
        if category is None
        else v.identifier(category, "interest category id"),
    )
    return link


def _due(
    session: Session,
    row: ScheduleRow,
    day: dt.date,
    ledgers: dict[int, debts.Ledger],
) -> Occurrence:
    """An occurrence, with its prediction when the schedule is tied to a debt."""
    if row.debt is None:
        return Occurrence(row.id, day)
    amount, splits = debts.debt_occurrence(
        session, row, _template_splits(row), day, ledgers=ledgers
    )
    return Occurrence(row.id, day, amount, None if splits is None else tuple(splits))


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
        debt: ScheduleDebt | None = None,
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
            debt: A [`LOAN_PAYMENT`][picciuli.model.DebtLinkKind] link to make
                it a loan payment: the template must move money from one
                account into the loan, and each occurrence is split into
                principal and interest. Credit card schedules are created by
                [`DebtService.set_terms`][picciuli.services.DebtService.set_terms].

        Returns:
            The stored schedule.

        Raises:
            ValidationError: If an argument is invalid, the splits do not
                balance or move shares, `start` is after `end`, or a loan
                payment is not a payment into a loan.
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
            template = _template(session, start, splits)
            link = _loan_link(debt)
            if link is not None:
                debts.check_loan_template(session, link, _splits_of(template))
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
                splits=template,
                debt=link,
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
        debt: ScheduleDebt | None | Unset = UNSET,
    ) -> Schedule:
        """Change a schedule; arguments left `UNSET` are not modified.

        Transactions already recorded are never changed. Any change clears
        [`last_error`][picciuli.model.Schedule]. The schedules of credit card
        interest and minimum payments follow the card's debt terms: they can
        only be paused, posted, skipped or deleted.

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
            debt: A loan payment link, or `None` to make it an ordinary
                schedule.

        Raises:
            NotFoundError: If the schedule, an account or a category does not
                exist.
            ValidationError: If an argument is invalid, the next
                occurrence would be after the end day or without occurrences
                left, or a loan payment is not a payment into a loan.
            ConflictError: If the new splits use a closed account, or
                anything but `paused` changes on a credit card schedule.
        """
        with self._uow.session() as session:
            row = get_row(session, ScheduleRow, schedule_id, "schedule")
            if _is_card(row):
                changed = [
                    value
                    for value in (
                        splits,
                        next_date,
                        frequency,
                        every,
                        day_of_month,
                        end,
                        occurrences,
                        mode,
                        description,
                        notes,
                        debt,
                    )
                    if not isinstance(value, Unset)
                ]
                if changed:
                    raise ConflictError(
                        "this recurring transaction follows the debt terms of the "
                        "credit card: change them instead"
                    )
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
            if not isinstance(debt, Unset):
                link = _loan_link(debt)
                row.debt = None
                session.flush()
                row.debt = link
                session.flush()
            if row.debt is not None and not _is_card(row):
                debts.check_loan_template(session, row.debt, _template_splits(row))
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
            account = None if row.debt is None else row.debt.account_id
            session.execute(
                update(TransactionRow)
                .where(TransactionRow.schedule_id == row.id)
                .values(schedule_id=None)
            )
            session.delete(row)
            if account is not None:
                # The proposals of a card follow its schedules.
                cached = session.get(AccountRow, account)
                if cached is not None:
                    session.flush()
                    session.expire(cached, ["debt_links"])

    def occurrences(self, start: dt.date, end: dt.date) -> builtins.list[Occurrence]:
        """List the occurrences of active schedules between two days.

        Paused and finished schedules have none. Occurrences before the next
        one of a schedule are not listed: they are already recorded or
        skipped. Occurrences of schedules tied to a debt carry their predicted
        amount and splits; credit card occurrences predicted at zero are left
        out.

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
        ledgers: dict[int, debts.Ledger] = {}
        with self._uow.session() as session:
            rows = session.scalars(
                select(ScheduleRow).where(
                    ScheduleRow.paused.is_(False),
                    ScheduleRow.next_date.is_not(None),
                    ScheduleRow.next_date <= end,
                )
            ).all()
            for row in rows:
                for day in _upcoming(row, start=start):
                    if day > end:
                        break
                    if day >= start:
                        occurrence = _due(session, row, day, ledgers)
                        if occurrence.amount == 0 and _is_card(row):
                            continue
                        result.append(occurrence)
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
        amount: int | None = None,
        from_account_id: int | None = None,
    ) -> Transaction:
        """Record the next occurrence of a schedule and move to the following one.

        The arguments change only this transaction, not the schedule: use
        them for a bill whose amount varies, or that was paid on another day.

        Schedules tied to a debt compute their splits for the day: a loan
        payment is split into principal and interest, a credit card gets its
        predicted interest charge or minimum payment.

        Args:
            schedule_id: The schedule.
            date: Day of the transaction; defaults to the day of the next
                occurrence.
            splits: Splits of the transaction; default to the template (or to
                the computed ones of a schedule tied to a debt).
            description: Description; defaults to the schedule's.
            notes: Notes; default to the schedule's.
            amount: Schedules tied to a debt only: the total payment or
                charge, instead of the predicted one.
            from_account_id: Loan and minimum payments only: the account
                the money comes from, instead of the usual one.

        Returns:
            The recorded transaction.

        Raises:
            NotFoundError: If the schedule, an account or a category does not
                exist.
            ConflictError: If the schedule has finished, an account is
                closed, or a card occurrence has nothing to charge or pay.
            ValidationError: If an argument is invalid, the splits do not
                balance or move shares, or the paying account of a minimum
                payment is unknown.
        """
        with self._uow.session() as session:
            row = get_row(session, ScheduleRow, schedule_id, "schedule")
            if row.next_date is None:
                raise ConflictError("the recurring transaction has finished")
            day = row.next_date if date is None else v.date(date, "date")
            if row.debt is None and (amount is not None or from_account_id is not None):
                raise ValidationError(
                    "an amount or a paying account only applies to recurring "
                    "transactions tied to a debt"
                )
            if amount is not None:
                amount = v.positive_amount(amount, "amount")
            payer = v.optional_integer(from_account_id, "from account id")
            if payer is not None:
                v.identifier(payer, "from account id")
                if row.debt is not None and (
                    DebtLinkKind(row.debt.kind) is DebtLinkKind.CARD_INTEREST
                ):
                    raise ValidationError("an interest charge has no paying account")
            if splits is not None:
                _template(session, day, splits)
                chosen: object = splits
            elif row.debt is not None:
                # Card amounts belong to their statement or due day, whatever
                # day they are recorded on; loan interest follows the payment day.
                occurrence = (
                    row.next_date
                    if DebtLinkKind(row.debt.kind) in debts.CARD_KINDS
                    else day
                )
                predicted, computed = debts.debt_occurrence(
                    session,
                    row,
                    _template_splits(row),
                    occurrence,
                    amount=amount,
                    payer=payer,
                )
                if computed is None:
                    if predicted is None:
                        raise ValidationError("the amount is unknown: give it")
                    if predicted:
                        raise ValidationError(
                            "choose the account the payment comes from"
                        )
                    raise ConflictError("there is nothing to charge or pay: skip it")
                chosen = computed
            else:
                chosen = _template_splits(row)
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
        occurrences are returned instead, with their predicted amounts when
        they are tied to a debt. Credit card occurrences with nothing to
        charge or pay are skipped on their own and listed in `skipped`.

        At most [`MAX_CATCH_UP`][picciuli.limits.MAX_CATCH_UP] occurrences
        are recorded and listed; call again to continue.

        Args:
            today: The current day of the user.

        Returns:
            What was recorded, what waits for confirmation, what failed and
            what was skipped.

        Raises:
            ValidationError: If `today` is not a date.
        """
        today = v.date(today, "today")
        posted: builtins.list[Transaction] = []
        due: builtins.list[Occurrence] = []
        failed: builtins.list[Schedule] = []
        skipped: builtins.list[Occurrence] = []
        ledgers: dict[int, debts.Ledger] = {}
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
            confirmed = [r for r in rows if r.mode == ScheduleMode.CONFIRM.value]
            for row in rows:
                if row.mode == ScheduleMode.CONFIRM.value:
                    continue
                while (
                    row.next_date is not None
                    and row.next_date <= today
                    and len(posted) < MAX_CATCH_UP
                ):
                    try:
                        with session.begin_nested():
                            splits: object = _template_splits(row)
                            if row.debt is not None:
                                splits = debts.debt_occurrence(
                                    session, row, _template_splits(row), row.next_date
                                )[1]
                            transaction = _record(
                                session,
                                row,
                                row.next_date,
                                splits,
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
            # Predictions only after every automatic transaction is recorded,
            # so that skipping a card occurrence never relies on a stale ledger.
            session.flush()
            for row in confirmed:
                try:
                    self._list_due(session, row, today, due, skipped, ledgers)
                except (ValidationError, ConflictError, NotFoundError) as exc:
                    row.last_error = str(exc)
                    failed.append(to_schedule(row))
            session.flush()
        posted.sort(key=lambda t: (t.date, t.id))
        due.sort(key=lambda o: (o.date, o.schedule_id))
        skipped.sort(key=lambda o: (o.date, o.schedule_id))
        return CatchUp(
            posted=tuple(posted),
            due=tuple(due),
            failed=tuple(failed),
            skipped=tuple(skipped),
        )

    @staticmethod
    def _list_due(
        session: Session,
        row: ScheduleRow,
        today: dt.date,
        due: builtins.list[Occurrence],
        skipped: builtins.list[Occurrence],
        ledgers: dict[int, debts.Ledger],
    ) -> None:
        """List the due occurrences of a confirmed schedule.

        Leading credit card occurrences predicted at zero are skipped first.
        """
        if _is_card(row):
            while (
                row.next_date is not None
                and row.next_date <= today
                and len(skipped) < MAX_CATCH_UP
            ):
                occurrence = _due(session, row, row.next_date, ledgers)
                if occurrence.amount != 0:
                    break
                skipped.append(occurrence)
                _advance(row)
                row.last_error = None
        for day in _upcoming(row):
            if day > today or len(due) >= MAX_CATCH_UP:
                break
            due.append(_due(session, row, day, ledgers))
