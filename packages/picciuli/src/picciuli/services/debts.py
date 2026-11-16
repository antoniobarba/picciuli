"""Debts: interest and payment terms, payoff plans, loan and card payments."""

from __future__ import annotations

import bisect
import builtins
import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from picciuli import _calendar, _debt
from picciuli import _validation as v
from picciuli._db.queries import (
    account_balances,
    get_row,
    to_account,
    to_transaction,
)
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import (
    AccountRow,
    CategoryRow,
    DebtChargeRow,
    DebtTermsRow,
    ScheduleDebtRow,
    ScheduleRow,
    SplitRow,
    TransactionRow,
)
from picciuli._decimal import from_scaled, to_decimal, to_scaled
from picciuli.errors import ConflictError, ValidationError
from picciuli.limits import MAX_MEMO_LENGTH
from picciuli.model import (
    UNSET,
    Account,
    AccountClass,
    AccountSplit,
    AccountType,
    DebtCharge,
    DebtLinkKind,
    DebtPayoff,
    DebtPlan,
    DebtStatus,
    DebtTerms,
    ExternalSplit,
    LoanPaymentSplit,
    LumpSum,
    PayoffStrategy,
    PlanMonth,
    Rollover,
    ScheduleFrequency,
    ScheduleMode,
    Split,
    Transaction,
    Unset,
)
from picciuli.services.transactions import _validated_splits

__all__ = ["DebtService"]

MAX_RATE = Decimal(1000)
"""Highest annual interest rate accepted, in percent."""

MAX_LUMP_SUMS = 100
"""Most lump sums in a single plan."""

MAX_CHARGES = 10
"""Most fixed charges in the terms of a loan."""

CARD_KINDS = (DebtLinkKind.CARD_INTEREST, DebtLinkKind.CARD_MIN_PAYMENT)


# --- Validation -----------------------------------------------------------------


def _choice(value: object, enum_type: type[PayoffStrategy] | type[Rollover]) -> object:
    try:
        return enum_type(value)
    except ValueError:
        allowed = ", ".join(str(item.value) for item in enum_type)
        raise ValidationError(
            f"invalid value {value!r}; expected one of: {allowed}"
        ) from None


def _percent(value: object, field: str, upper: Decimal) -> Decimal:
    result = to_decimal(value, field)
    if not 0 <= result <= upper:
        raise ValidationError(f"{field} must be between 0 and {upper}")
    return result


def _day(value: object, field: str) -> int | None:
    if value is None:
        return None
    result = v.integer(value, field)
    if not 1 <= result <= 31:
        raise ValidationError(f"{field} must be between 1 and 31")
    return result


def _flag(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{field} must be a boolean")
    return value


def is_liability(row: AccountRow) -> bool:
    return AccountType(row.type).account_class is AccountClass.LIABILITY


def is_card(row: AccountRow) -> bool:
    return row.type == AccountType.CREDIT_CARD.value


def _validated_charges(
    session: Session, charges: object, *, card: bool, payment: int | None
) -> builtins.list[DebtChargeRow]:
    if isinstance(charges, (str, bytes)) or not isinstance(charges, Sequence):
        raise ValidationError("charges must be a sequence of DebtCharge")
    if charges and card:
        raise ValidationError(
            "only loans, mortgages and other liabilities have fixed charges"
        )
    if len(charges) > MAX_CHARGES:
        raise ValidationError(f"a debt cannot have more than {MAX_CHARGES} charges")
    rows = []
    for position, charge in enumerate(charges, start=1):
        if not isinstance(charge, DebtCharge):
            raise ValidationError(f"charge {position} must be a DebtCharge")
        amount = v.positive_amount(charge.amount, f"charge {position} amount")
        category = None
        if charge.category_id is not None:
            category = v.identifier(
                charge.category_id, f"charge {position} category id"
            )
            get_row(session, CategoryRow, category, "category")
        label = v.optional_text(
            charge.label, f"charge {position} label", MAX_MEMO_LENGTH
        )
        rows.append(
            DebtChargeRow(
                position=position, amount=amount, category_id=category, label=label
            )
        )
    if payment is not None and sum(r.amount for r in rows) >= payment:
        raise ValidationError("the fixed charges must be less than the payment")
    return rows


def validated_terms(
    session: Session, account: AccountRow, terms: object
) -> tuple[dict[str, object], bool, bool]:
    """Columns of the terms row, and whether to propose interest and minimums."""
    if not isinstance(terms, DebtTerms):
        raise ValidationError("terms must be a DebtTerms")
    if not is_liability(account):
        raise ValidationError(
            f"account {account.name!r} is not a liability: only credit cards, "
            "loans, mortgages and other liabilities have debt terms"
        )
    card = is_card(account)
    rate = _percent(terms.annual_rate, "annual rate", MAX_RATE)
    payment = (
        None if terms.payment is None else v.positive_amount(terms.payment, "payment")
    )
    percent = None
    if terms.payment_percent is not None:
        percent = _percent(terms.payment_percent, "payment percent", Decimal(100))
        if percent == 0:
            raise ValidationError("payment percent must be greater than zero")
    due_day = _day(terms.due_day, "due day")
    statement_day = _day(terms.statement_day, "statement day")
    limit = (
        None
        if terms.credit_limit is None
        else v.positive_amount(terms.credit_limit, "credit limit")
    )
    propose_interest = _flag(terms.propose_interest, "propose interest")
    propose_minimum = _flag(terms.propose_minimum, "propose minimum")
    if not card:
        for name, value in (
            ("a payment percent", percent),
            ("a statement day", statement_day),
            ("a credit limit", limit),
        ):
            if value is not None:
                raise ValidationError(f"only credit cards have {name}")
        if propose_interest or propose_minimum:
            raise ValidationError(
                "only credit cards propose interest charges and minimum payments"
            )
    payer = None
    if terms.payment_account_id is not None:
        payer = v.identifier(terms.payment_account_id, "payment account id")
        if payer == account.id:
            raise ValidationError("an account cannot pay itself")
        get_row(session, AccountRow, payer, "account")
    category = None
    if terms.interest_category_id is not None:
        category = v.identifier(terms.interest_category_id, "interest category id")
        get_row(session, CategoryRow, category, "category")
    if (propose_interest or propose_minimum) and account.closed_on is not None:
        raise ConflictError(f"account {account.name!r} is closed")
    if propose_interest and (statement_day is None or category is None):
        raise ValidationError(
            "proposing interest charges needs a statement day and an interest category"
        )
    if propose_minimum and (
        statement_day is None
        or due_day is None
        or (payment is None and percent is None)
    ):
        raise ValidationError(
            "proposing minimum payments needs a statement day, a due day and a "
            "minimum payment (amount or percent)"
        )
    columns: dict[str, object] = {
        "annual_rate": to_scaled(rate),
        "payment": payment,
        "payment_percent": None if percent is None else to_scaled(percent),
        "due_day": due_day,
        "statement_day": statement_day,
        "credit_limit": limit,
        "payment_account_id": payer,
        "interest_category_id": category,
        "charges": _validated_charges(
            session, terms.charges, card=card, payment=payment
        ),
    }
    return columns, propose_interest, propose_minimum


# --- Schedules managed by the terms of a credit card ----------------------------


def delete_schedule(session: Session, row: ScheduleRow) -> None:
    """Delete a schedule, keeping the transactions it recorded."""
    session.execute(
        update(TransactionRow)
        .where(TransactionRow.schedule_id == row.id)
        .values(schedule_id=None)
    )
    session.delete(row)


def _links(session: Session, account_id: int) -> builtins.list[ScheduleDebtRow]:
    return list(
        session.scalars(
            select(ScheduleDebtRow).where(ScheduleDebtRow.account_id == account_id)
        )
    )


def _schedule_of(session: Session, link: ScheduleDebtRow) -> ScheduleRow:
    return get_row(session, ScheduleRow, link.schedule_id, "schedule")


def _refresh(session: Session, account: AccountRow) -> None:
    session.flush()
    session.expire(account, ["debt_links", "debt_terms"])


def sync_card_schedules(
    session: Session,
    account: AccountRow,
    *,
    interest: bool,
    minimum: bool,
    today: dt.date,
) -> None:
    """Create, move or delete the schedules proposing card interest and minimums."""
    terms = account.debt_terms
    links = {
        DebtLinkKind(link.kind): link
        for link in _links(session, account.id)
        if DebtLinkKind(link.kind) in CARD_KINDS
    }
    wanted = {
        DebtLinkKind.CARD_INTEREST: (
            interest,
            None if terms is None else terms.statement_day,
            f"{account.name} interest",
        ),
        DebtLinkKind.CARD_MIN_PAYMENT: (
            minimum,
            None if terms is None else terms.due_day,
            f"{account.name} minimum payment",
        ),
    }
    for kind, (wanted_it, day, description) in wanted.items():
        link = links.get(kind)
        if not wanted_it or day is None:
            if link is not None:
                delete_schedule(session, _schedule_of(session, link))
            continue
        if link is None:
            session.add(
                ScheduleRow(
                    description=description,
                    notes=None,
                    frequency=ScheduleFrequency.MONTHLY.value,
                    every=1,
                    day_of_month=day,
                    next_date=_debt.on_or_after(today, day),
                    end_date=None,
                    remaining=None,
                    mode=ScheduleMode.CONFIRM.value,
                    paused=False,
                    last_error=None,
                    splits=[],
                    debt=ScheduleDebtRow(account_id=account.id, kind=kind.value),
                )
            )
            continue
        schedule = _schedule_of(session, link)
        if schedule.day_of_month != day:
            schedule.day_of_month = day
            schedule.next_date = _debt.on_or_after(today, day)
            schedule.last_error = None
    _refresh(session, account)


def check_card_schedule(
    account: AccountRow, kind: DebtLinkKind, fields: dict[str, object]
) -> None:
    """Refuse an imported credit card schedule that its terms would not create."""
    terms = account.debt_terms
    if not is_card(account) or terms is None:
        raise ValidationError(
            f"account {account.name!r} is not a credit card with debt terms"
        )
    if kind is DebtLinkKind.CARD_INTEREST:
        day = terms.statement_day
        ready = day is not None and terms.interest_category_id is not None
    else:
        day = terms.due_day
        ready = (
            day is not None
            and terms.statement_day is not None
            and (terms.payment is not None or terms.payment_percent is not None)
        )
    if not (
        ready
        and fields["frequency"] == ScheduleFrequency.MONTHLY.value
        and fields["every"] == 1
        and fields["day_of_month"] == day
        and fields["mode"] == ScheduleMode.CONFIRM.value
        and fields["end_date"] is None
        and fields["remaining"] is None
    ):
        raise ValidationError("it does not follow the debt terms of its credit card")


def on_type_change(
    session: Session, account: AccountRow, new_type: AccountType
) -> None:
    """Drop the terms (or the parts of them) that the new type cannot have."""
    liability = new_type.account_class is AccountClass.LIABILITY
    card = new_type is AccountType.CREDIT_CARD
    for link in _links(session, account.id):
        kind = DebtLinkKind(link.kind)
        if kind in CARD_KINDS and not card:
            delete_schedule(session, _schedule_of(session, link))
        elif kind is DebtLinkKind.LOAN_PAYMENT and (card or not liability):
            session.delete(link)
    terms = account.debt_terms
    if terms is not None:
        if not liability:
            account.debt_terms = None
        elif not card:
            terms.payment_percent = None
            terms.statement_day = None
            terms.credit_limit = None
        else:
            terms.charges = []
    _refresh(session, account)


def on_close(session: Session, account: AccountRow) -> None:
    """Stop proposing card interest and minimum payments for a closed account."""
    for link in _links(session, account.id):
        if DebtLinkKind(link.kind) in CARD_KINDS:
            delete_schedule(session, _schedule_of(session, link))
    _refresh(session, account)


def on_delete(session: Session, account: AccountRow) -> None:
    """Remove what refers to an account that is about to be deleted."""
    on_close(session, account)
    session.execute(
        update(DebtTermsRow)
        .where(DebtTermsRow.payment_account_id == account.id)
        .values(payment_account_id=None)
    )


def on_category_delete(session: Session, category_id: int, target: int | None) -> None:
    """Move the interest and charges of debts and loan payments to another category."""
    session.execute(
        update(DebtTermsRow)
        .where(DebtTermsRow.interest_category_id == category_id)
        .values(interest_category_id=target)
    )
    session.execute(
        update(DebtChargeRow)
        .where(DebtChargeRow.category_id == category_id)
        .values(category_id=target)
    )
    session.execute(
        update(ScheduleDebtRow)
        .where(ScheduleDebtRow.interest_category_id == category_id)
        .values(interest_category_id=target)
    )


# --- Reading the ledger of one account -------------------------------------------


class Ledger:
    """Daily balances and credits of one account."""

    def __init__(
        self, session: Session, account: AccountRow, *, exclude: int | None = None
    ) -> None:
        statement = (
            select(TransactionRow.date, SplitRow.amount)
            .join(TransactionRow, SplitRow.transaction_id == TransactionRow.id)
            .where(SplitRow.account_id == account.id)
            .order_by(TransactionRow.date)
        )
        if exclude is not None:
            statement = statement.where(TransactionRow.id != exclude)
        flows: dict[dt.date, int] = {}
        credits: dict[dt.date, int] = {}
        for day, amount in session.execute(statement):
            flows[day] = flows.get(day, 0) + amount
            if amount > 0:
                credits[day] = credits.get(day, 0) + amount
        self._days = sorted(flows)
        self._flows = flows
        running = 0
        self._totals: list[int] = []
        for day in self._days:
            running += flows[day]
            self._totals.append(running)
        self._credit_days = sorted(credits)
        running = 0
        self._credit_totals: list[int] = []
        for day in self._credit_days:
            running += credits[day]
            self._credit_totals.append(running)
        self._opening = account.opening_balance
        self._opening_date = account.opening_date

    def balance(self, day: dt.date) -> int:
        """Balance at the end of `day`."""
        index = bisect.bisect_right(self._days, day)
        flows = self._totals[index - 1] if index else 0
        opened = self._opening_date is None or self._opening_date <= day
        return (self._opening if opened else 0) + flows

    def owed(self, day: dt.date) -> int:
        """Amount owed at the end of `day`."""
        return max(0, -self.balance(day))

    def owed_by_day(self, first: dt.date, last: dt.date) -> builtins.list[int]:
        """Amount owed at the end of every day from `first` to `last`."""
        result = []
        balance = self.balance(first - dt.timedelta(days=1))
        day = first
        while day <= last:
            balance += self._flows.get(day, 0)
            if day == self._opening_date:
                balance += self._opening
            result.append(max(0, -balance))
            day += dt.timedelta(days=1)
        return result

    def credits(self, after: dt.date, until: dt.date) -> int:
        """Money credited to the account after `after`, up to `until` included."""
        high = bisect.bisect_right(self._credit_days, until)
        low = bisect.bisect_right(self._credit_days, after)
        if high <= low:
            return 0
        return self._credit_totals[high - 1] - (
            self._credit_totals[low - 1] if low else 0
        )


def _rate(terms: DebtTermsRow | None) -> Decimal:
    return Decimal(0) if terms is None else from_scaled(terms.annual_rate)


def _card_percent(terms: DebtTermsRow) -> Decimal | None:
    return None if terms.payment_percent is None else from_scaled(terms.payment_percent)


def card_interest(ledger: Ledger, terms: DebtTermsRow, statement: dt.date) -> int:
    """Interest charged on the statement of `statement`, with the grace period."""
    if terms.statement_day is None:
        return 0
    previous = _debt.before(statement, terms.statement_day)
    owed = ledger.owed(previous)
    if owed == 0:
        return 0
    if terms.due_day is not None:
        due = _debt.on_or_after(previous + dt.timedelta(days=1), terms.due_day)
        if ledger.credits(previous, due) >= owed:
            return 0
    return _debt.daily_interest(
        ledger.owed_by_day(previous + dt.timedelta(days=1), statement), _rate(terms)
    )


def card_minimum(ledger: Ledger, terms: DebtTermsRow, due: dt.date) -> int | None:
    """Minimum payment still due on `due` after the payments of the cycle."""
    if terms.statement_day is None:
        return None
    statement = _debt.before(due, terms.statement_day)
    minimum = _debt.minimum_payment(
        ledger.owed(statement),
        card=True,
        payment=terms.payment,
        percent=_card_percent(terms),
    )
    if minimum is None:
        return None
    following = _debt.on_or_after(statement + dt.timedelta(days=1), terms.statement_day)
    return max(0, minimum - ledger.credits(statement, following))


def loan_interest(ledger: Ledger, terms: DebtTermsRow | None, day: dt.date) -> int:
    """Interest of the month on what is owed at the start of `day`."""
    return _debt.monthly_interest(ledger.owed(day - dt.timedelta(days=1)), _rate(terms))


def loan_charges(terms: DebtTermsRow | None) -> tuple[DebtCharge, ...]:
    """The fixed charges of a loan's terms."""
    if terms is None:
        return ()
    return tuple(DebtCharge(c.amount, c.category_id, c.label) for c in terms.charges)


def _divide(
    paid: int, interest: int, charges: Sequence[DebtCharge]
) -> tuple[int, tuple[DebtCharge, ...], int]:
    """Interest, charges and principal of a payment: interest first, then charges."""
    interest = min(interest, paid)
    left = paid - interest
    charged = []
    for charge in charges:
        amount = min(charge.amount, left)
        if amount:
            charged.append(DebtCharge(amount, charge.category_id, charge.label))
            left -= amount
    return interest, tuple(charged), left


def _loan_splits(
    template: Sequence[Split],
    loan_id: int,
    total: int | None,
    interest: int,
    charges: Sequence[DebtCharge],
    category: int | None,
    payer: int | None,
) -> builtins.list[Split]:
    paid = total if total is not None else max(abs(s.amount) for s in template)
    charged_interest, charged, principal = _divide(paid, interest, charges)
    result: builtins.list[Split] = []
    for split in template:
        assert isinstance(split, AccountSplit)
        if split.account_id == loan_id:
            if principal:
                result.append(AccountSplit(loan_id, principal, split.memo))
        else:
            result.append(AccountSplit(payer or split.account_id, -paid, split.memo))
    if charged_interest:
        result.append(ExternalSplit(-charged_interest, category, "Interest"))
    result.extend(ExternalSplit(-c.amount, c.category_id, c.label) for c in charged)
    return result


def check_loan_template(
    session: Session, link: ScheduleDebtRow, splits: Sequence[Split]
) -> None:
    """Refuse a loan payment schedule that is not a plain payment into the loan."""
    loan = get_row(session, AccountRow, link.account_id, "account")
    if not is_liability(loan) or is_card(loan):
        raise ValidationError(
            f"account {loan.name!r} is not a loan: only loans, mortgages and other "
            "liabilities have loan payments"
        )
    if link.interest_category_id is not None:
        get_row(session, CategoryRow, link.interest_category_id, "category")
    accounts = [s for s in splits if isinstance(s, AccountSplit)]
    into = [s for s in accounts if s.account_id == loan.id]
    other = [s for s in accounts if s.account_id != loan.id]
    if not (
        len(splits) == 2
        and len(into) == 1
        and len(other) == 1
        and into[0].amount > 0
        and other[0].amount == -into[0].amount
    ):
        raise ValidationError(
            f"a loan payment must move money from one account into {loan.name!r}, "
            "without categories"
        )


def debt_occurrence(
    session: Session,
    schedule: ScheduleRow,
    template: Sequence[Split],
    day: dt.date,
    *,
    amount: int | None = None,
    payer: int | None = None,
    ledgers: dict[int, Ledger] | None = None,
) -> tuple[int | None, builtins.list[Split] | None]:
    """Predicted amount and splits of an occurrence of a schedule tied to a debt.

    `amount` and `payer` replace the predicted amount and the paying account.
    The splits are `None` when the paying account of a minimum payment is
    unknown, or there is nothing to charge.
    """
    link = schedule.debt
    assert link is not None
    account = get_row(session, AccountRow, link.account_id, "account")
    cache = {} if ledgers is None else ledgers
    ledger = cache.get(account.id)
    if ledger is None:
        ledger = cache[account.id] = Ledger(session, account)
    terms = account.debt_terms
    kind = DebtLinkKind(link.kind)
    if kind is DebtLinkKind.LOAN_PAYMENT:
        total = amount if amount is not None else max(abs(s.amount) for s in template)
        interest = loan_interest(ledger, terms, day)
        category = link.interest_category_id
        if category is None and terms is not None:
            category = terms.interest_category_id
        return total, _loan_splits(
            template,
            account.id,
            amount,
            interest,
            loan_charges(terms),
            category,
            payer,
        )
    if terms is None:
        raise ConflictError(f"account {account.name!r} has no debt terms")
    if kind is DebtLinkKind.CARD_INTEREST:
        charge = amount if amount is not None else card_interest(ledger, terms, day)
        if charge == 0:
            return 0, None
        return charge, [
            AccountSplit(account.id, -charge),
            ExternalSplit(-charge, terms.interest_category_id, "Interest"),
        ]
    due = amount if amount is not None else card_minimum(ledger, terms, day)
    source = payer if payer is not None else terms.payment_account_id
    if not due or source is None:
        return due, None
    return due, [AccountSplit(source, -due), AccountSplit(account.id, due)]


# --- The service ---------------------------------------------------------------


class DebtService:
    """Interest and payment terms of liabilities, payoff plans and loan payments.

    Obtain it as [`Book.debts`][picciuli.Book.debts].

    Credit cards, loans, mortgages and other liabilities can have
    [`DebtTerms`][picciuli.model.DebtTerms]: an interest rate, a minimum or
    fixed payment and the days of the statement and of the payment. With
    them the library splits loan payments into principal, interest and fixed
    charges (such as an insurance premium),
    proposes the interest charge and the minimum payment of credit cards for
    confirmation (as recurring transactions that wait for it), forecasts when
    each debt is paid off, and simulates paying them all off with the
    snowball or avalanche strategy.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def set_terms(
        self, account_id: int, terms: DebtTerms, *, today: dt.date | None = None
    ) -> Account:
        """Set (or replace) the terms of a liability account.

        Turning on `propose_interest` or `propose_minimum` creates a monthly
        recurring transaction waiting for confirmation on the statement or due
        day, starting on or after `today`; turning them off deletes it.

        Args:
            account_id: A credit card, loan, mortgage or other liability.
            terms: The new terms.
            today: The current day, which decides the first proposed
                occurrence; defaults to the actual date.

        Returns:
            The account with its new terms.

        Raises:
            NotFoundError: If the account, the paying account or the
                interest category does not exist.
            ValidationError: If the account is not a liability, a value is
                invalid, a credit card field is given for another account
                type, or a proposal misses the days or amounts it needs.
            ConflictError: If proposals are turned on for a closed account.
        """
        today = v.optional_date(today, "today") or dt.date.today()
        with self._uow.session() as session:
            row = get_row(session, AccountRow, account_id, "account")
            columns, interest, minimum = validated_terms(session, row, terms)
            if row.debt_terms is None:
                row.debt_terms = DebtTermsRow(account_id=row.id, **columns)
            else:
                for name, value in columns.items():
                    setattr(row.debt_terms, name, value)
            session.flush()
            sync_card_schedules(
                session, row, interest=interest, minimum=minimum, today=today
            )
            return to_account(row)

    def remove_terms(self, account_id: int) -> Account:
        """Remove the terms of an account and stop proposing card payments.

        Loan payment schedules stay, without interest.

        Raises:
            NotFoundError: If the account does not exist.
        """
        with self._uow.session() as session:
            row = get_row(session, AccountRow, account_id, "account")
            on_close(session, row)
            row.debt_terms = None
            _refresh(session, row)
            return to_account(row)

    def list(self, *, today: dt.date | None = None) -> builtins.list[DebtStatus]:
        """Return the open liabilities with terms, in display order.

        Args:
            today: The current day; defaults to the actual date. Balances
                include the transactions up to this day, and payoff dates
                are simulated from the following month.
        """
        today = v.optional_date(today, "today") or dt.date.today()
        first = _next_month(today)
        result = []
        with self._uow.session() as session:
            balances = account_balances(session, until=today)
            for row in _debt_rows(session):
                terms = row.debt_terms
                assert terms is not None
                balance = balances[row.id]
                plan_debt = _plan_debt(row, balance)
                minimum = _debt.minimum_payment(
                    plan_debt.owed,
                    card=plan_debt.card,
                    payment=terms.payment,
                    percent=plan_debt.percent,
                    charges=plan_debt.charges,
                )
                payoff = interest = charges = None
                if plan_debt.owed == 0:
                    interest = charges = 0
                elif minimum is not None:
                    outcome = _debt.simulate(
                        [plan_debt], first_month=first, rollover=Rollover.NONE
                    )
                    payoff = outcome.payoff[0]
                    if payoff is not None:
                        interest = outcome.interest[0]
                        charges = outcome.charges[0]
                result.append(
                    DebtStatus(
                        account=to_account(row),
                        balance=balance,
                        minimum_payment=minimum,
                        next_due=None
                        if terms.due_day is None
                        else _debt.on_or_after(today, terms.due_day),
                        payoff=payoff,
                        interest_to_payoff=interest,
                        charges_to_payoff=charges,
                    )
                )
        return result

    def plan(
        self,
        *,
        strategy: PayoffStrategy | str = PayoffStrategy.AVALANCHE,
        extra: int = 0,
        lump_sums: Sequence[LumpSum] = (),
        rollover: Rollover | str = Rollover.FULL,
        rollover_percent: Decimal | None = None,
        today: dt.date | None = None,
    ) -> DebtPlan:
        """Simulate paying off every open liability with terms and a balance owed.

        Args:
            strategy: Which debt gets the money left after the minimum
                payments.
            extra: Extra payment every month (zero or positive).
            lump_sums: One-off extra payments, at most 100.
            rollover: What happens to the payment of a paid-off debt.
            rollover_percent: With `Rollover.PARTIAL`, the percentage of it
                that goes to the next debt (0 to 100); defaults to 50.
            today: The current day; defaults to the actual date. The plan
                starts the following month.

        Raises:
            ValidationError: If an argument is invalid.
        """
        strategy = PayoffStrategy(_choice(strategy, PayoffStrategy))
        rollover = Rollover(_choice(rollover, Rollover))
        extra = v.non_negative_amount(extra, "extra")
        percent = None
        if rollover is Rollover.PARTIAL:
            percent = (
                Decimal(50)
                if rollover_percent is None
                else _percent(rollover_percent, "rollover percent", Decimal(100))
            )
        elif rollover_percent is not None:
            raise ValidationError("a rollover percent needs a partial rollover")
        today = v.optional_date(today, "today") or dt.date.today()
        first = _next_month(today)
        if isinstance(lump_sums, (str, bytes)) or not isinstance(lump_sums, Sequence):
            raise ValidationError("lump sums must be a sequence of LumpSum")
        if len(lump_sums) > MAX_LUMP_SUMS:
            raise ValidationError(
                f"a plan cannot have more than {MAX_LUMP_SUMS} lump sums"
            )
        lumps: dict[int, int] = {}
        for index, lump in enumerate(lump_sums, start=1):
            if not isinstance(lump, LumpSum):
                raise ValidationError(f"lump sum {index} must be a LumpSum")
            day = v.date(lump.date, f"lump sum {index} date")
            value = v.positive_amount(lump.amount, f"lump sum {index} amount")
            number = max(0, _calendar.month_index(day) - _calendar.month_index(first))
            lumps[number] = lumps.get(number, 0) + value
        with self._uow.session() as session:
            balances = account_balances(session, until=today)
            debts = [
                _plan_debt(row, balances[row.id])
                for row in _debt_rows(session)
                if balances[row.id] < 0
            ]
        outcome = _debt.simulate(
            debts,
            first_month=first,
            strategy=strategy,
            extra=extra,
            lump_sums=lumps,
            rollover=rollover,
            rollover_percent=percent,
        )
        payoffs = tuple(
            DebtPayoff(
                account_id=debt.id,
                order=index,
                balance=debt.owed,
                payoff=outcome.payoff[index - 1],
                interest=outcome.interest[index - 1],
                paid=outcome.paid[index - 1],
                charges=outcome.charges[index - 1],
            )
            for index, debt in enumerate(outcome.order, start=1)
        )
        months = tuple(
            PlanMonth(month, payment, interest, sum(balances_), balances_)
            for month, payment, interest, balances_ in outcome.months
        )
        last = [p.payoff for p in payoffs]
        return DebtPlan(
            strategy=strategy,
            rollover=rollover,
            rollover_percent=percent,
            extra=extra,
            monthly_budget=outcome.monthly_budget,
            debts=payoffs,
            months=months,
            payoff=None
            if any(day is None for day in last)
            else max((day for day in last if day is not None), default=first),
            total_interest=sum(outcome.interest),
            total_paid=sum(outcome.paid),
            total_charges=sum(outcome.charges),
        )

    def loan_payment_split(
        self,
        account_id: int,
        date: dt.date,
        amount: int,
        *,
        exclude_transaction_id: int | None = None,
    ) -> LoanPaymentSplit:
        """Divide a payment into a loan into interest, charges and principal.

        The interest is one month at the loan's rate on the amount owed at
        the start of `date`, at most the whole payment. The fixed charges of
        the loan's terms come next, at most what is left; the rest is
        principal. A loan without terms has no interest and no charges.

        Args:
            account_id: A loan, mortgage or other liability (not a credit
                card).
            date: Day of the payment.
            amount: The whole payment (positive).
            exclude_transaction_id: A transaction to leave out of the balance,
                typically the payment being edited.

        Raises:
            NotFoundError: If the account does not exist.
            ValidationError: If the account is not a loan or an argument is
                invalid.
        """
        date = v.date(date, "date")
        amount = v.positive_amount(amount, "amount")
        exclude = v.optional_integer(exclude_transaction_id, "exclude transaction id")
        with self._uow.session() as session:
            row = _loan_row(session, account_id)
            ledger = Ledger(session, row, exclude=exclude)
            owed = ledger.owed(date - dt.timedelta(days=1))
            interest, charges, principal = _divide(
                amount,
                loan_interest(ledger, row.debt_terms, date),
                loan_charges(row.debt_terms),
            )
            return LoanPaymentSplit(
                account_id=row.id,
                date=date,
                amount=amount,
                owed=owed,
                interest=interest,
                principal=principal,
                charges=charges,
            )

    def record_loan_payment(
        self,
        date: dt.date,
        amount: int,
        *,
        loan_account_id: int,
        from_account_id: int,
        interest_category_id: int | None | Unset = UNSET,
        description: str | None = None,
        notes: str | None = None,
    ) -> Transaction:
        """Record a payment into a loan, split into principal, interest and charges.

        The fixed charges of the loan's terms are recorded as expenses in
        their categories, like the interest.

        Args:
            date: Day of the payment.
            amount: The whole payment (positive).
            loan_account_id: The loan.
            from_account_id: The account the money comes from.
            interest_category_id: Category of the interest; defaults to the
                one of the loan's terms.
            description: Description of the transaction.
            notes: Notes of the transaction.

        Raises:
            NotFoundError: If an account or the category does not exist.
            ValidationError: If the loan is not a loan or an argument is
                invalid.
            ConflictError: If an account is closed.
        """
        date = v.date(date, "date")
        amount = v.positive_amount(amount, "amount")
        payer = v.identifier(from_account_id, "from account id")
        with self._uow.session() as session:
            row = _loan_row(session, loan_account_id)
            if payer == row.id:
                raise ValidationError("a loan cannot pay itself")
            category: int | None
            if isinstance(interest_category_id, Unset):
                terms = row.debt_terms
                category = None if terms is None else terms.interest_category_id
            else:
                category = v.optional_integer(
                    interest_category_id, "interest category id"
                )
            interest = loan_interest(Ledger(session, row), row.debt_terms, date)
            splits = _loan_splits(
                [AccountSplit(payer, -amount), AccountSplit(row.id, amount)],
                row.id,
                amount,
                interest,
                loan_charges(row.debt_terms),
                category,
                payer,
            )
            transaction = TransactionRow(
                date=date,
                description=v.optional_text(description, "description"),
                notes=v.optional_text(notes, "notes"),
                splits=_validated_splits(session, date, splits),
            )
            session.add(transaction)
            session.flush()
            return to_transaction(transaction)

    def card_interest(self, account_id: int, statement_date: dt.date) -> int:
        """Predict the interest charged on a credit card statement.

        It is the average daily balance owed during the cycle ending on
        `statement_date` times `annual_rate / 365` per day, or zero when the
        previous statement was paid in full by its due day.

        Raises:
            NotFoundError: If the account does not exist.
            ValidationError: If the account is not a credit card with terms.
        """
        statement_date = v.date(statement_date, "statement date")
        with self._uow.session() as session:
            row, terms = _card_row(session, account_id)
            return card_interest(Ledger(session, row), terms, statement_date)

    def card_minimum(self, account_id: int, due_date: dt.date) -> int | None:
        """Predict the minimum payment still due on a credit card on a due day.

        It is the minimum payment on the balance of the last statement
        before `due_date`, less what was paid into the card since then;
        `None` without a statement day or a minimum payment in the terms.

        Raises:
            NotFoundError: If the account does not exist.
            ValidationError: If the account is not a credit card with terms.
        """
        due_date = v.date(due_date, "due date")
        with self._uow.session() as session:
            row, terms = _card_row(session, account_id)
            return card_minimum(Ledger(session, row), terms, due_date)


def _next_month(today: dt.date) -> dt.date:
    following = _calendar.add_months(today, 1, 1)
    if following is None:
        raise ValidationError("today is out of the supported range of dates")
    return following


def _debt_rows(session: Session) -> builtins.list[AccountRow]:
    rows = session.scalars(
        select(AccountRow)
        .join(DebtTermsRow, DebtTermsRow.account_id == AccountRow.id)
        .where(AccountRow.closed_on.is_(None))
        .order_by(AccountRow.position, AccountRow.id)
    )
    return [row for row in rows if is_liability(row)]


def _plan_debt(row: AccountRow, balance: int) -> _debt.PlanDebt:
    terms = row.debt_terms
    assert terms is not None
    return _debt.PlanDebt(
        id=row.id,
        owed=max(0, -balance),
        annual_rate=_rate(terms),
        card=is_card(row),
        payment=terms.payment,
        percent=_card_percent(terms),
        charges=sum(c.amount for c in terms.charges),
    )


def _loan_row(session: Session, account_id: int) -> AccountRow:
    row = get_row(session, AccountRow, account_id, "account")
    if not is_liability(row) or is_card(row):
        raise ValidationError(
            f"account {row.name!r} is not a loan, a mortgage or another liability"
        )
    return row


def _card_row(session: Session, account_id: int) -> tuple[AccountRow, DebtTermsRow]:
    row = get_row(session, AccountRow, account_id, "account")
    if not is_card(row) or row.debt_terms is None:
        raise ValidationError(f"account {row.name!r} is not a credit card with terms")
    return row, row.debt_terms
