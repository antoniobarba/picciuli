from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from picciuli import (
    Account,
    AccountSplit,
    AccountType,
    Book,
    Category,
    ConflictError,
    DebtCharge,
    DebtLinkKind,
    DebtTerms,
    ExternalSplit,
    LumpSum,
    NotFoundError,
    PayoffStrategy,
    Rollover,
    ScheduleDebt,
    ScheduleMode,
    ValidationError,
    _debt,
)

from .conftest import d

CARD_TERMS = DebtTerms(
    Decimal(20),
    payment=2500,
    payment_percent=Decimal(3),
    due_day=25,
    statement_day=10,
)


@pytest.fixture
def interest(book: Book) -> Category:
    return book.categories.create("Interest")


@pytest.fixture
def mortgage(book: Book) -> Account:
    return book.accounts.create(
        "Mortgage", AccountType.MORTGAGE, opening_balance=-15000000
    )


def _card_with_proposals(
    book: Book, card: Account, checking: Account, interest: Category
) -> Account:
    return book.debts.set_terms(
        card.id,
        replace(
            CARD_TERMS,
            payment_account_id=checking.id,
            interest_category_id=interest.id,
            propose_interest=True,
            propose_minimum=True,
        ),
        today=d(1),
    )


# --- Arithmetic -----------------------------------------------------------------


def test_interest_and_minimum_payments() -> None:
    assert _debt.monthly_interest(15000000, Decimal(3)) == 37500
    assert _debt.monthly_interest(-100, Decimal(3)) == 0
    assert _debt.daily_interest([10000] * 31, Decimal(20)) == 170
    assert _debt.minimum_payment(
        10000, card=True, payment=2500, percent=Decimal(3)
    ) == (2500)
    assert (
        _debt.minimum_payment(200000, card=True, payment=2500, percent=Decimal(3))
        == 6000
    )
    assert _debt.minimum_payment(1000, card=True, payment=2500, percent=None) == 1000
    assert _debt.minimum_payment(5000, card=False, payment=None, percent=None) is None
    assert _debt.on_or_after(d(31), 25) == d(25, 2)
    assert _debt.on_or_after(d(1, 2), 31) == d(28, 2)
    assert _debt.before(d(10), 10) == d(10, 12, 2024)


debts_strategy = st.lists(
    st.builds(
        _debt.PlanDebt,
        id=st.integers(1, 1000),
        owed=st.integers(0, 10**7),
        annual_rate=st.decimals(0, 40, places=2),
        card=st.booleans(),
        payment=st.none() | st.integers(1, 10**6),
        percent=st.none() | st.decimals(1, 10, places=1),
        charges=st.integers(0, 2000),
    ),
    max_size=4,
)


@given(debts=debts_strategy, extra=st.integers(0, 10**5))
def test_paid_off_debts_cost_their_balance_plus_interest(
    debts: list[_debt.PlanDebt], extra: int
) -> None:
    result = _debt.simulate(debts, first_month=d(1), extra=extra, max_months=240)
    for index, debt in enumerate(result.order):
        if result.payoff[index] is not None:
            assert result.paid[index] == (
                debt.owed + result.interest[index] + result.charges[index]
            )
    for _, payment, _, balances in result.months:
        assert payment >= 0
        assert all(balance >= 0 for balance in balances)


# --- Terms ---------------------------------------------------------------------


def test_terms_are_only_for_liabilities(
    book: Book, checking: Account, mortgage: Account
) -> None:
    with pytest.raises(ValidationError, match="not a liability"):
        book.debts.set_terms(checking.id, DebtTerms(Decimal(1)))
    with pytest.raises(ValidationError, match="only credit cards"):
        book.debts.set_terms(mortgage.id, DebtTerms(Decimal(3), statement_day=1))
    with pytest.raises(ValidationError, match="annual rate"):
        book.debts.set_terms(mortgage.id, DebtTerms(Decimal(-1)))
    with pytest.raises(ValidationError, match="cannot pay itself"):
        book.debts.set_terms(
            mortgage.id, DebtTerms(Decimal(3), payment_account_id=mortgage.id)
        )
    terms = DebtTerms(Decimal("3.25"), payment=80000, due_day=5)
    assert book.debts.set_terms(mortgage.id, terms).debt_terms == terms
    assert book.accounts.get(mortgage.id).debt_terms == terms
    assert book.debts.remove_terms(mortgage.id).debt_terms is None


def test_proposals_need_the_days_and_amounts(
    book: Book, card: Account, interest: Category
) -> None:
    with pytest.raises(ValidationError, match="statement day and an interest"):
        book.debts.set_terms(card.id, DebtTerms(Decimal(20), propose_interest=True))
    with pytest.raises(ValidationError, match="minimum payment"):
        book.debts.set_terms(
            card.id,
            DebtTerms(Decimal(20), statement_day=10, due_day=25, propose_minimum=True),
        )
    assert book.schedules.list() == []


def test_proposals_follow_the_terms(
    book: Book, card: Account, checking: Account, interest: Category
) -> None:
    account = _card_with_proposals(book, card, checking, interest)
    assert account.debt_terms is not None
    assert (
        account.debt_terms.propose_interest,
        account.debt_terms.propose_minimum,
    ) == (
        True,
        True,
    )
    charge, payment = sorted(book.schedules.list(), key=lambda s: s.id)
    assert charge.debt is not None and payment.debt is not None
    assert (charge.debt.kind, charge.next_date, charge.mode) == (
        DebtLinkKind.CARD_INTEREST,
        d(10),
        ScheduleMode.CONFIRM,
    )
    assert (payment.debt.kind, payment.next_date) == (
        DebtLinkKind.CARD_MIN_PAYMENT,
        d(25),
    )
    assert charge.splits == payment.splits == ()
    with pytest.raises(ConflictError, match="debt terms"):
        book.schedules.update(charge.id, description="x")
    assert book.schedules.update(charge.id, paused=True).paused

    moved = book.debts.set_terms(
        card.id,
        replace(account.debt_terms, statement_day=12, propose_minimum=False),
        today=d(1),
    )
    assert moved.debt_terms is not None and not moved.debt_terms.propose_minimum
    (only,) = book.schedules.list()
    assert (only.id, only.day_of_month, only.next_date) == (charge.id, 12, d(12))

    book.schedules.delete(only.id)
    terms = book.accounts.get(card.id).debt_terms
    assert terms is not None and not terms.propose_interest


def test_type_changes_drop_what_does_not_apply(
    book: Book, card: Account, checking: Account, interest: Category
) -> None:
    _card_with_proposals(book, card, checking, interest)
    loan = book.accounts.update(card.id, type=AccountType.LOAN)
    assert loan.debt_terms == DebtTerms(
        Decimal(20),
        payment=2500,
        due_day=25,
        payment_account_id=checking.id,
        interest_category_id=interest.id,
    )
    assert book.schedules.list() == []
    assert book.accounts.update(card.id, type=AccountType.CASH).debt_terms is None


def test_closing_deleting_and_category_removal(
    book: Book, card: Account, checking: Account, interest: Category
) -> None:
    _card_with_proposals(book, card, checking, interest)
    other = book.categories.create("Bank")
    book.categories.delete(interest.id, reassign_to=other.id)
    terms = book.accounts.get(card.id).debt_terms
    assert terms is not None and terms.interest_category_id == other.id
    book.accounts.delete(checking.id)
    terms = book.accounts.get(card.id).debt_terms
    assert terms is not None and terms.payment_account_id is None
    book.accounts.close(card.id, on=d(1))
    assert book.schedules.list() == []


# --- Loans -----------------------------------------------------------------------


def test_loan_payments_are_split_into_principal_and_interest(
    book: Book, checking: Account, mortgage: Account, interest: Category
) -> None:
    book.debts.set_terms(
        mortgage.id,
        DebtTerms(Decimal(3), payment=80000, interest_category_id=interest.id),
    )
    split = book.debts.loan_payment_split(mortgage.id, d(5), 80000)
    assert (split.owed, split.interest, split.principal) == (15000000, 37500, 42500)
    recorded = book.debts.record_loan_payment(
        d(5), 80000, loan_account_id=mortgage.id, from_account_id=checking.id
    )
    assert recorded.splits == (
        AccountSplit(checking.id, -80000),
        AccountSplit(mortgage.id, 42500),
        ExternalSplit(-37500, interest.id, "Interest"),
    )
    again = book.debts.loan_payment_split(
        mortgage.id, d(5), 80000, exclude_transaction_id=recorded.id
    )
    assert again.interest == 37500
    with pytest.raises(ValidationError, match="not a loan"):
        book.debts.loan_payment_split(checking.id, d(5), 100)


def test_recurring_loan_payments_compute_interest_when_posted(
    book: Book, checking: Account, mortgage: Account, interest: Category
) -> None:
    book.debts.set_terms(
        mortgage.id, DebtTerms(Decimal(3), interest_category_id=interest.id)
    )
    template = [AccountSplit(checking.id, -80000), AccountSplit(mortgage.id, 80000)]
    with pytest.raises(ValidationError, match="loan payment"):
        book.schedules.create(
            d(5),
            [AccountSplit(checking.id, -80000), ExternalSplit(-80000)],
            debt=ScheduleDebt(DebtLinkKind.LOAN_PAYMENT, mortgage.id),
        )
    with pytest.raises(ValidationError, match="credit card"):
        book.schedules.create(
            d(5), template, debt=ScheduleDebt(DebtLinkKind.CARD_INTEREST, mortgage.id)
        )
    schedule = book.schedules.create(
        d(5, 2), template, debt=ScheduleDebt(DebtLinkKind.LOAN_PAYMENT, mortgage.id)
    )
    (first,) = book.schedules.occurrences(d(1, 2), d(28, 2))
    assert first.amount == 80000
    assert first.splits is not None and first.splits[-1] == ExternalSplit(
        -37500, interest.id, "Interest"
    )
    posted = book.schedules.catch_up(d(5, 3)).posted
    assert [t.splits for t in posted] == [
        (
            AccountSplit(checking.id, -80000),
            AccountSplit(mortgage.id, 42500),
            ExternalSplit(-37500, interest.id, "Interest"),
        ),
        (
            AccountSplit(checking.id, -80000),
            AccountSplit(mortgage.id, 42606),
            ExternalSplit(-37394, interest.id, "Interest"),
        ),
    ]
    assert all(t.schedule_id == schedule.id for t in posted)
    unlinked = book.schedules.update(schedule.id, debt=None)
    assert unlinked.debt is None


@pytest.fixture
def insurance(book: Book) -> Category:
    return book.categories.create("Insurance")


def _loan_with_insurance(
    book: Book, interest: Category, insurance: Category
) -> Account:
    # Like a real 10,000 loan at 8.99% with 7.09 of insurance in each 133.71.
    loan = book.accounts.create("Loan", AccountType.LOAN, opening_balance=-952000)
    return book.debts.set_terms(
        loan.id,
        DebtTerms(
            Decimal("8.99"),
            payment=13371,
            interest_category_id=interest.id,
            charges=(DebtCharge(709, insurance.id, "Insurance"),),
        ),
    )


def test_loan_payments_pay_fixed_charges_before_principal(
    book: Book, checking: Account, interest: Category, insurance: Category
) -> None:
    loan = _loan_with_insurance(book, interest, insurance)
    assert loan.debt_terms is not None
    assert loan.debt_terms.charges == (DebtCharge(709, insurance.id, "Insurance"),)
    split = book.debts.loan_payment_split(loan.id, d(16, 11), 13371)
    assert (split.interest, split.charges, split.principal) == (
        7132,
        (DebtCharge(709, insurance.id, "Insurance"),),
        5530,
    )
    recorded = book.debts.record_loan_payment(
        d(16, 11), 13371, loan_account_id=loan.id, from_account_id=checking.id
    )
    assert recorded.splits == (
        AccountSplit(checking.id, -13371),
        AccountSplit(loan.id, 5530),
        ExternalSplit(-7132, interest.id, "Interest"),
        ExternalSplit(-709, insurance.id, "Insurance"),
    )
    # A payment too small for everything pays the interest, then the charges.
    small = book.debts.loan_payment_split(loan.id, d(16, 12), 7400)
    assert (small.interest, small.charges, small.principal) == (
        7091,
        (DebtCharge(309, insurance.id, "Insurance"),),
        0,
    )

    template = [AccountSplit(checking.id, -13371), AccountSplit(loan.id, 13371)]
    book.schedules.create(
        d(16, 12), template, debt=ScheduleDebt(DebtLinkKind.LOAN_PAYMENT, loan.id)
    )
    (posted,) = book.schedules.catch_up(d(16, 12)).posted
    assert posted.splits == (
        AccountSplit(checking.id, -13371),
        AccountSplit(loan.id, 5571),
        ExternalSplit(-7091, interest.id, "Interest"),
        ExternalSplit(-709, insurance.id, "Insurance"),
    )

    book.categories.delete(insurance.id, reassign_to=None)
    terms = book.accounts.get(loan.id).debt_terms
    assert terms is not None and terms.charges == (DebtCharge(709, None, "Insurance"),)
    card = book.accounts.update(loan.id, type=AccountType.CREDIT_CARD)
    assert card.debt_terms is not None and card.debt_terms.charges == ()


def test_fixed_charges_are_validated(
    book: Book, card: Account, mortgage: Account, insurance: Category
) -> None:
    charge = DebtCharge(709, insurance.id)
    with pytest.raises(ValidationError, match="only loans"):
        book.debts.set_terms(card.id, DebtTerms(Decimal(20), charges=(charge,)))
    with pytest.raises(ValidationError, match="less than the payment"):
        book.debts.set_terms(
            mortgage.id,
            DebtTerms(Decimal(3), payment=1000, charges=(charge, DebtCharge(291))),
        )
    with pytest.raises(ValidationError, match="charge 1 amount"):
        book.debts.set_terms(
            mortgage.id, DebtTerms(Decimal(3), charges=(DebtCharge(0),))
        )
    with pytest.raises(ValidationError, match="more than 10"):
        book.debts.set_terms(mortgage.id, DebtTerms(Decimal(3), charges=(charge,) * 11))
    with pytest.raises(NotFoundError):
        book.debts.set_terms(
            mortgage.id, DebtTerms(Decimal(3), charges=(DebtCharge(709, 999),))
        )
    terms = DebtTerms(Decimal(3), charges=(charge, DebtCharge(150, label=" Fee ")))
    saved = book.debts.set_terms(mortgage.id, terms).debt_terms
    assert saved is not None
    assert saved.charges == (charge, DebtCharge(150, None, "Fee"))
    replaced = book.debts.set_terms(mortgage.id, replace(terms, charges=()))
    assert replaced.debt_terms is not None and replaced.debt_terms.charges == ()


# --- Credit cards ------------------------------------------------------------------


def test_card_items_are_skipped_when_nothing_is_due(
    book: Book, card: Account, checking: Account, interest: Category
) -> None:
    _card_with_proposals(book, card, checking, interest)
    book.transactions.record_expense(d(5), 10000, account_id=card.id)
    book.transactions.record_transfer(
        d(20), 10000, from_account_id=checking.id, to_account_id=card.id
    )
    first = book.schedules.catch_up(d(31))
    assert first.due == ()
    assert [o.date for o in first.skipped] == [d(10), d(25)]
    second = book.schedules.catch_up(d(28, 2))
    assert (second.due, [o.date for o in second.skipped]) == ((), [d(10, 2), d(25, 2)])
    assert book.debts.card_interest(card.id, d(10, 2)) == 0


def test_card_interest_and_minimum_wait_for_confirmation(
    book: Book, card: Account, checking: Account, interest: Category, savings: Account
) -> None:
    _card_with_proposals(book, card, checking, interest)
    book.transactions.record_expense(d(5), 10000, account_id=card.id)
    result = book.schedules.catch_up(d(31))
    (minimum,) = result.due
    assert (minimum.date, minimum.amount) == (d(25), 2500)
    assert minimum.splits == (
        AccountSplit(checking.id, -2500),
        AccountSplit(card.id, 2500),
    )
    paid = book.schedules.post(minimum.schedule_id, from_account_id=savings.id)
    assert (paid.date, paid.splits) == (
        d(25),
        (AccountSplit(savings.id, -2500), AccountSplit(card.id, 2500)),
    )
    # Statement of February: 14 days owing 100.00 and 17 days owing 75.00.
    (charge,) = book.schedules.catch_up(d(10, 2)).due
    assert (charge.date, charge.amount) == (d(10, 2), 147)
    assert book.debts.card_interest(card.id, d(10, 2)) == 147
    posted = book.schedules.post(charge.schedule_id, amount=150)
    assert posted.splits == (
        AccountSplit(card.id, -150),
        ExternalSplit(-150, interest.id, "Interest"),
    )
    # A partial payment reduces the minimum still due.
    book.transactions.record_transfer(
        d(15, 2), 1000, from_account_id=checking.id, to_account_id=card.id
    )
    assert book.debts.card_minimum(card.id, d(25, 2)) == 2500 - 1000


def test_catch_up_predicts_after_recording_automatic_charges(
    book: Book, card: Account, checking: Account, interest: Category
) -> None:
    book.debts.set_terms(
        card.id,
        replace(
            CARD_TERMS,
            statement_day=1,
            payment_percent=None,
            payment_account_id=checking.id,
            interest_category_id=interest.id,
            propose_interest=True,
            propose_minimum=True,
        ),
        today=d(20, 10, 2026),
    )
    book.schedules.create(
        d(28, 10, 2026), [AccountSplit(card.id, -5000), ExternalSplit(-5000)]
    )
    result = book.schedules.catch_up(d(1, 12, 2026))
    assert [t.date for t in result.posted] == [d(28, 10, 2026), d(28, 11, 2026)]
    assert [o.date for o in result.skipped] == [d(25, 10, 2026), d(1, 11, 2026)]
    assert (result.due[0].date, result.due[0].amount) == (d(25, 11, 2026), 2500)


def test_card_occurrences_keep_their_amount_when_recorded_later(
    book: Book, interest: Category
) -> None:
    card = book.accounts.create(
        "Visa", AccountType.CREDIT_CARD, opening_balance=-100000
    )
    book.debts.set_terms(
        card.id,
        DebtTerms(
            Decimal(20),
            statement_day=1,
            interest_category_id=interest.id,
            propose_interest=True,
        ),
        today=d(20, 10, 2026),
    )
    (charge,) = book.schedules.occurrences(d(1, 11, 2026), d(1, 11, 2026))
    assert charge.amount == 1699
    posted = book.schedules.post(charge.schedule_id, date=d(3, 11, 2026))
    assert (posted.date, posted.net_amount) == (d(3, 11, 2026), -1699)


def test_minimum_payment_without_a_paying_account(
    book: Book, card: Account, interest: Category
) -> None:
    book.debts.set_terms(
        card.id,
        DebtTerms(
            Decimal(20),
            payment=2500,
            due_day=25,
            statement_day=10,
            propose_minimum=True,
        ),
        today=d(1),
    )
    book.transactions.record_expense(d(5), 10000, account_id=card.id)
    (minimum,) = book.schedules.catch_up(d(25)).due
    assert (minimum.amount, minimum.splits) == (2500, None)
    with pytest.raises(ValidationError, match="choose the account"):
        book.schedules.post(minimum.schedule_id)


# --- Status and plans ------------------------------------------------------------


def test_debt_list_forecasts_the_payoff(
    book: Book, mortgage: Account, card: Account
) -> None:
    book.debts.set_terms(mortgage.id, DebtTerms(Decimal(3), payment=80000, due_day=5))
    book.debts.set_terms(card.id, DebtTerms(Decimal(20)))
    status, unknown = book.debts.list(today=d(16, 11))
    assert (status.owed, status.minimum_payment, status.next_due) == (
        15000000,
        80000,
        d(5, 12),
    )
    assert status.payoff is not None and status.payoff.year > 2040
    assert status.interest_to_payoff is not None and status.interest_to_payoff > 0
    assert (unknown.owed, unknown.payoff, unknown.interest_to_payoff) == (0, None, 0)


def test_forecasts_pay_fixed_charges_without_reducing_the_debt(
    book: Book, interest: Category, insurance: Category
) -> None:
    loan = _loan_with_insurance(book, interest, insurance)
    (status,) = book.debts.list(today=d(16, 11))
    assert status.minimum_payment == 13371
    assert status.payoff is not None and status.charges_to_payoff is not None
    assert status.charges_to_payoff % 709 == 0 and status.charges_to_payoff > 0
    plan = book.debts.plan(today=d(16, 11))
    (payoff,) = plan.debts
    assert payoff.charges == plan.total_charges == status.charges_to_payoff
    assert plan.total_paid == 952000 + plan.total_interest + plan.total_charges
    assert plan.months[0].payment == 13371
    terms = book.accounts.get(loan.id).debt_terms
    assert terms is not None
    book.debts.set_terms(loan.id, replace(terms, charges=()))
    without = book.debts.plan(today=d(16, 11))
    assert without.payoff is not None and plan.payoff is not None
    assert without.payoff < plan.payoff


def test_plans_compare_strategies(book: Book, checking: Account) -> None:
    card = book.accounts.create(
        "Card", AccountType.CREDIT_CARD, opening_balance=-300000
    )
    loan = book.accounts.create("Loan", AccountType.LOAN, opening_balance=-100000)
    book.debts.set_terms(card.id, DebtTerms(Decimal(25), payment=10000))
    book.debts.set_terms(loan.id, DebtTerms(Decimal(5), payment=10000))

    snowball = book.debts.plan(
        strategy=PayoffStrategy.SNOWBALL, extra=5000, today=d(16, 11)
    )
    avalanche = book.debts.plan(
        strategy=PayoffStrategy.AVALANCHE, extra=5000, today=d(16, 11)
    )
    assert [p.account_id for p in snowball.debts] == [loan.id, card.id]
    assert [p.account_id for p in avalanche.debts] == [card.id, loan.id]
    assert avalanche.total_interest < snowball.total_interest
    assert avalanche.months[0].month == d(1, 12)
    assert avalanche.monthly_budget == 25000
    assert avalanche.payoff is not None
    assert avalanche.months[-1].balance == 0

    faster = book.debts.plan(extra=15000, today=d(16, 11))
    assert faster.payoff is not None and faster.payoff < avalanche.payoff
    freed = book.debts.plan(rollover=Rollover.NONE, extra=5000, today=d(16, 11))
    assert freed.payoff is None or freed.payoff > avalanche.payoff
    lump = book.debts.plan(
        lump_sums=[LumpSum(d(1, 1, 2026), 50000)], extra=5000, today=d(16, 11)
    )
    assert lump.total_interest < avalanche.total_interest
    partial = book.debts.plan(rollover=Rollover.PARTIAL, today=d(16, 11))
    assert partial.rollover_percent == Decimal(50)
    with pytest.raises(ValidationError, match="partial"):
        book.debts.plan(rollover_percent=Decimal(10))


# --- Import ------------------------------------------------------------------------


def test_import_copies_terms_and_card_schedules_once(
    book: Book, card: Account, checking: Account, interest: Category, mortgage: Account
) -> None:
    _card_with_proposals(book, card, checking, interest)
    book.debts.set_terms(
        mortgage.id,
        DebtTerms(
            Decimal(3), payment=80000, charges=(DebtCharge(500, interest.id, "Fee"),)
        ),
    )
    book.schedules.create(
        d(5, 2),
        [AccountSplit(checking.id, -80000), AccountSplit(mortgage.id, 80000)],
        debt=ScheduleDebt(DebtLinkKind.LOAN_PAYMENT, mortgage.id, interest.id),
    )
    book.transactions.record_expense(d(5), 10000, account_id=card.id)
    (minimum,) = book.schedules.catch_up(d(31)).due
    book.schedules.post(minimum.schedule_id)

    with Book.in_memory() as copy:
        assert copy.import_from(book).schedules == 3
        assert [a.debt_terms for a in copy.accounts.list()] == [
            a.debt_terms for a in book.accounts.list()
        ]
        assert sorted(
            (s.debt.kind, s.next_date) for s in copy.schedules.list() if s.debt
        ) == sorted((s.debt.kind, s.next_date) for s in book.schedules.list() if s.debt)
        assert copy.import_from(book).schedules == 0
        assert len(copy.schedules.list()) == 3

    with Book.in_memory() as other:
        own = other.accounts.create("Card", AccountType.CREDIT_CARD)
        other.debts.set_terms(own.id, DebtTerms(Decimal(9)))
        # An account of the book with the name of a debt of the file is kept.
        home = other.accounts.create("Mortgage", AccountType.CHECKING)
        summary = other.import_from(book)
        assert summary.schedules == 1
        terms = other.accounts.get(own.id).debt_terms
        assert terms == DebtTerms(Decimal(9))
        assert other.accounts.get(home.id).debt_terms is None
        (plain,) = other.schedules.list()
        assert plain.debt is None
        payment = next(
            t for t in other.transactions.list() if t.description is not None
        )
        assert payment.schedule_id is None
