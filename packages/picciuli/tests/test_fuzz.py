"""Stateful fuzzing of a Book with extreme amounts, quantities and prices.

Whatever the input, the library must only raise `PicciuliError`, and the
balances and net worth must stay readable.
"""

from __future__ import annotations

import contextlib
import datetime as dt
from decimal import Decimal

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import Bundle, RuleBasedStateMachine, invariant, rule

from picciuli import (
    AccountSplit,
    AccountType,
    Book,
    ExternalSplit,
    PicciuliError,
    SecurityKind,
)
from picciuli.limits import MAX_AMOUNT

EXTREME_INTS = [
    0,
    1,
    -1,
    2,
    MAX_AMOUNT,
    MAX_AMOUNT + 1,
    -MAX_AMOUNT,
    -MAX_AMOUNT - 1,
    2**53,
    2**63 - 1,
    2**63,
    -(2**63),
    -(2**63) - 1,
    2**64,
]
amounts = st.one_of(
    st.sampled_from(EXTREME_INTS), st.integers(-(2**65), 2**65), st.integers(-9, 9)
)
decimals = st.one_of(
    st.sampled_from(
        [
            "1",
            "0.5",
            "1E+30",
            "1e308",
            "1e999999999",
            "-1e999999999",
            "1e-999999999",
            "0.123456789",
            "92233720368.54775807",
            "92233720368.54775808",
            "NaN",
            "Infinity",
            "-0",
        ]
    ).map(Decimal),
    st.decimals(allow_nan=True, allow_infinity=True),
    st.integers(-(2**70), 2**70),
)
days = st.dates(dt.date(1, 1, 1), dt.date(9999, 12, 31))
texts = st.one_of(st.none(), st.text(max_size=30), st.just("x" * 3000))


class BookMachine(RuleBasedStateMachine):
    accounts = Bundle("accounts")
    securities = Bundle("securities")

    def __init__(self) -> None:
        super().__init__()
        self.book = Book.in_memory()
        self.created = 0

    def teardown(self) -> None:
        self.book.close()

    def _name(self, prefix: str) -> str:
        self.created += 1
        return f"{prefix} {self.created}"

    @rule(
        target=accounts,
        kind=st.sampled_from([AccountType.CHECKING, AccountType.INVESTMENT]),
        opening=amounts,
        goal=st.one_of(st.none(), amounts),
        notes=texts,
    )
    def create_account(
        self, kind: AccountType, opening: int, goal: int | None, notes: str | None
    ) -> int:
        try:
            return self.book.accounts.create(
                self._name("Account"),
                kind,
                opening_balance=opening,
                goal=goal,
                notes=notes,
            ).id
        except PicciuliError:
            return self.book.accounts.create(self._name("Fallback"), kind).id

    @rule(target=securities)
    def create_security(self) -> int:
        return self.book.securities.create(
            self._name("Security"), currency="EUR", kind=SecurityKind.ETF
        ).id

    @rule(account=accounts, day=days, amount=amounts, income=st.booleans())
    def income_or_expense(
        self, account: int, day: dt.date, amount: int, income: bool
    ) -> None:
        record = (
            self.book.transactions.record_income
            if income
            else self.book.transactions.record_expense
        )
        with contextlib.suppress(PicciuliError):
            record(day, amount, account_id=account)

    @rule(source=accounts, target_account=accounts, day=days, amount=amounts)
    def transfer(
        self, source: int, target_account: int, day: dt.date, amount: int
    ) -> None:
        with contextlib.suppress(PicciuliError):
            self.book.transactions.record_transfer(
                day, amount, from_account_id=source, to_account_id=target_account
            )

    @rule(
        account=accounts,
        day=days,
        parts=st.lists(amounts, min_size=0, max_size=4),
        memo=texts,
    )
    def split_transaction(
        self, account: int, day: dt.date, parts: list[int], memo: str | None
    ) -> None:
        splits = [ExternalSplit(amount=part, memo=memo) for part in parts]
        total = sum(parts)
        with contextlib.suppress(PicciuliError):
            self.book.transactions.create(
                day, [AccountSplit(account_id=account, amount=total), *splits]
            )

    @rule(
        account=accounts,
        security=securities,
        day=days,
        quantity=decimals,
        cost=amounts,
        fee=amounts,
    )
    def buy(
        self,
        account: int,
        security: int,
        day: dt.date,
        quantity: Decimal | int,
        cost: int,
        fee: int,
    ) -> None:
        with contextlib.suppress(PicciuliError):
            self.book.investments.record_buy(
                day,
                account_id=account,
                security_id=security,
                quantity=quantity,
                cost=cost,
                fee=fee,
            )

    @rule(
        account=accounts,
        security=securities,
        day=days,
        quantity=decimals,
        proceeds=amounts,
        tax=amounts,
    )
    def sell(
        self,
        account: int,
        security: int,
        day: dt.date,
        quantity: Decimal | int,
        proceeds: int,
        tax: int,
    ) -> None:
        with contextlib.suppress(PicciuliError):
            self.book.investments.record_sell(
                day,
                account_id=account,
                security_id=security,
                quantity=quantity,
                proceeds=proceeds,
                tax=tax,
            )

    @rule(security=securities, day=days, price=decimals)
    def set_price(self, security: int, day: dt.date, price: Decimal | int) -> None:
        with contextlib.suppress(PicciuliError):
            self.book.securities.set_price(security, day, price)

    @rule(other=amounts)
    def lookup_any_id(self, other: int) -> None:
        with contextlib.suppress(PicciuliError):
            self.book.accounts.balance(other)
        with contextlib.suppress(PicciuliError):
            self.book.transactions.list(account_id=other, limit=abs(other))

    @invariant()
    def totals_are_readable(self) -> None:
        balances = self.book.accounts.balances(include_closed=True)
        worth = self.book.accounts.net_worth()
        assert worth.net_worth == sum(b.balance for b in balances)
        self.book.investments.net_worth()
        self.book.investments.valuations(include_closed=True)


BookMachine.TestCase.settings = settings(
    max_examples=40,
    stateful_step_count=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
TestBookMachine = BookMachine.TestCase
