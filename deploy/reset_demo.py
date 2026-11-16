"""Reset only the explicitly provisioned production demo identity and book."""

from __future__ import annotations

import calendar
import datetime as dt
import json
import math
import os
import sqlite3
import tempfile
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote

from picciuli import (
    AccountSplit,
    AccountType,
    Book,
    ExternalSplit,
    GoalPriority,
    SecurityKind,
)
from picciuli_api.auth import User
from picciuli_api.config import Settings
from picciuli_api.login import Zitadel

PAY_DAY = 27
"""Salary day: the demo periods run from one pay day to the next."""


def shift_month(day: dt.date, months: int) -> dt.date:
    """Move a day by whole months, clamping it to the length of the month."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    last = calendar.monthrange(year, month + 1)[1]
    return dt.date(year, month + 1, min(day.day, last))


def _cents(units: float) -> int:
    return round(units * 100)


def populate_demo(book: Book, today: dt.date) -> None:
    """Fill an empty book with four pay cycles of realistic data ending `today`."""
    current = (
        today.replace(day=PAY_DAY)
        if today.day >= PAY_DAY
        else shift_month(today.replace(day=PAY_DAY), -1)
    )
    starts = [shift_month(current, months) for months in (-3, -2, -1, 0)]
    first = starts[0]
    with book.atomic():
        book.settings.update(currency="€")
        accounts = book.accounts
        checking = accounts.create(
            "Checking",
            AccountType.CHECKING,
            opening_balance=_cents(1200),
            opening_date=first,
        )
        savings = accounts.create(
            "Savings",
            AccountType.SAVINGS,
            opening_balance=_cents(800),
            opening_date=first,
        )
        book.goals.create(
            savings.id,
            "Emergency fund",
            _cents(5000),
            saved_amount=_cents(600),
            priority=GoalPriority.HIGH,
        )
        book.goals.create(
            savings.id,
            "Summer holiday",
            _cents(1500),
            saved_amount=_cents(200),
            target_date=shift_month(today, 8),
        )
        card = accounts.create(
            "Credit card", AccountType.CREDIT_CARD, opening_date=first
        )
        cash = accounts.create(
            "Cash", AccountType.CASH, opening_balance=_cents(60), opening_date=first
        )
        mortgage = accounts.create(
            "Mortgage",
            AccountType.MORTGAGE,
            opening_balance=-_cents(150_000),
            opening_date=first,
        )

        categories = book.categories
        income = categories.create("Income")
        salary = categories.create("Salary", parent_id=income.id)
        home = categories.create("Home")
        utilities = categories.create("Utilities", parent_id=home.id)
        maintenance = categories.create("Maintenance", parent_id=home.id)
        food = categories.create("Food")
        groceries = categories.create("Groceries", parent_id=food.id)
        restaurants = categories.create("Restaurants", parent_id=food.id)
        transport = categories.create("Transport")
        leisure = categories.create("Leisure")
        finance = categories.create("Finance")
        interest = categories.create(
            "Mortgage interest", parent_id=finance.id, symbol="INT"
        )

        record = book.transactions
        for cycle, start in enumerate(starts):
            name = (start + dt.timedelta(days=7)).strftime("%B %Y")
            period = book.periods.create(start, name=name)
            for category, amount in (
                (groceries, 400),
                (restaurants, 120),
                (home, 250),
                (transport, 150),
                (leisure, 200),
            ):
                book.budgets.create(category.id, period.id, _cents(amount))

            def on(offset: int, start: dt.date = start) -> dt.date | None:
                day = start + dt.timedelta(days=offset)
                return day if day <= today else None

            card_spent = 0

            def card_expense(
                offset: int, amount: int, category: int, text: str
            ) -> None:
                nonlocal card_spent
                day = on(offset)
                if day is not None:
                    record.record_expense(
                        day,
                        amount,
                        account_id=card.id,
                        category_id=category,
                        description=text,
                    )
                    card_spent += amount

            if day := on(0):
                record.record_income(
                    day,
                    _cents(2450),
                    account_id=checking.id,
                    category_id=salary.id,
                    description="Salary",
                )
            if day := on(1):
                record.record_transfer(
                    day,
                    _cents(300),
                    from_account_id=checking.id,
                    to_account_id=savings.id,
                    description="Monthly saving",
                )
            if day := on(3):
                principal = _cents(480 + cycle)
                record.create(
                    day,
                    [
                        AccountSplit(checking.id, -_cents(650)),
                        AccountSplit(mortgage.id, principal),
                        ExternalSplit(principal - _cents(650), interest.id),
                    ],
                    description="Mortgage instalment",
                )
            for week, offset in enumerate((2, 9, 16, 23)):
                card_expense(
                    offset,
                    _cents(62 + (cycle * 7 + week * 13) % 30),
                    groceries.id,
                    "Supermarket",
                )
            for offset in (5, 19):
                card_expense(
                    offset,
                    _cents(35 + (cycle * 5 + offset) % 14),
                    restaurants.id,
                    "Dinner out",
                )
            if day := on(7):
                record.record_expense(
                    day,
                    _cents(110 + cycle * 4),
                    account_id=checking.id,
                    category_id=utilities.id,
                    description="Electricity and gas",
                )
            if day := on(10):
                record.record_expense(
                    day, _cents(2), account_id=checking.id, description="Bank fee"
                )
            if day := on(12):
                record.record_expense(
                    day,
                    _cents(45),
                    account_id=checking.id,
                    category_id=transport.id,
                    description="Fuel",
                )
            if day := on(14):
                record.create(
                    day,
                    [
                        AccountSplit(card.id, -_cents(100)),
                        ExternalSplit(-_cents(60), groceries.id),
                        ExternalSplit(-_cents(40), maintenance.id, "light bulbs"),
                    ],
                    description="Hypermarket",
                )
                card_spent += _cents(100)
            if day := on(15):
                record.record_expense(
                    day,
                    _cents(24),
                    account_id=cash.id,
                    category_id=leisure.id,
                    description="Cinema",
                )
            if day := on(17):
                record.record_transfer(
                    day,
                    _cents(50),
                    from_account_id=checking.id,
                    to_account_id=cash.id,
                    description="ATM withdrawal",
                )
            if card_spent and (day := on(25)):
                record.record_transfer(
                    day,
                    card_spent,
                    from_account_id=checking.id,
                    to_account_id=card.id,
                    description="Credit card bill",
                )
        holiday_start = max(today - dt.timedelta(days=12), starts[-1])
        book.periods.create(
            holiday_start, end=holiday_start + dt.timedelta(days=7), name="Holiday"
        )
        _populate_investments(book, checking.id, starts, today)


def _demo_price(base: float, day: int) -> Decimal:
    """A deterministic, gently rising and wobbling price."""
    value = base * (1 + 0.001 * day + 0.03 * math.sin(day / 6))
    return Decimal(f"{value:.2f}")


def _populate_investments(
    book: Book, checking_id: int, starts: list[dt.date], today: dt.date
) -> None:
    """An investment account with monthly ETF purchases and offline prices."""
    first = starts[0]
    book.settings.update(currency_code="EUR")
    broker = book.accounts.create("Broker", AccountType.INVESTMENT, opening_date=first)
    investing = book.categories.create("Investing")
    gains = book.categories.create("Capital gains", parent_id=investing.id)
    fees = book.categories.create("Broker fees", parent_id=investing.id, symbol="FEES")
    etf = book.securities.create(
        "Vanguard FTSE All-World",
        currency="EUR",
        kind=SecurityKind.ETF,
        symbol="VWCE.DE",
        isin="IE00BK5BQT80",
    )
    apple = book.securities.create(
        "Apple", currency="USD", symbol="AAPL", isin="US0378331005"
    )
    day = first
    while day <= today:
        offset = (day - first).days
        book.securities.set_price(etf.id, day, _demo_price(120, offset))
        book.securities.set_price(apple.id, day, _demo_price(220, offset))
        book.securities.set_exchange_rate(
            "USD", day, Decimal(f"{0.92 + 0.01 * math.sin(offset / 9):.4f}")
        )
        day += dt.timedelta(days=1)
    for start in starts:
        purchase = start + dt.timedelta(days=2)
        if purchase > today:
            continue
        price = _demo_price(120, (purchase - first).days)
        book.investments.record_buy(
            purchase,
            account_id=broker.id,
            security_id=etf.id,
            quantity=(Decimal(200) / price).quantize(Decimal("0.0001")),
            cost=_cents(200),
            from_account_id=checking_id,
            fee=_cents(1),
            fee_category_id=fees.id,
            description="Savings plan",
        )
    if first + dt.timedelta(days=4) <= today:
        book.investments.record_buy(
            first + dt.timedelta(days=4),
            account_id=broker.id,
            security_id=apple.id,
            quantity=2,
            cost=_cents(405),
            from_account_id=checking_id,
        )
    sale = starts[-1] + dt.timedelta(days=4)
    if sale <= today:
        book.investments.record_sell(
            sale,
            account_id=broker.id,
            security_id=apple.id,
            quantity=1,
            proceeds=_cents(215),
            to_account_id=checking_id,
            gain_category_id=gains.id,
        )


def create_demo(path: str | os.PathLike[str], today: dt.date) -> None:
    """Create a new demonstration book file.

    Raises:
        FileExistsError: If the file already exists.
    """
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"refusing to overwrite {os.fspath(path)}")
    with Book.open(target) as book:
        populate_demo(book, today)


def reset_book(destination: Path, today: dt.date) -> None:
    """Replace data atomically without unlinking a database cached by the API."""
    with tempfile.TemporaryDirectory(prefix="picciuli-demo-") as directory:
        seed = Path(directory) / "seed.db"
        create_demo(seed, today)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with Book.open(destination):
            pass
        with (
            closing(sqlite3.connect(seed)) as source,
            closing(sqlite3.connect(destination, timeout=30)) as target,
        ):
            if source.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RuntimeError("Demo seed failed its integrity check")
            if source.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Demo seed has invalid references")
            # SQLite's online backup locks and commits the destination atomically;
            # replacing the file itself would strand the API's open connections.
            source.backup(target)


def main() -> None:
    """Read VM-only credentials, validate the pinned identity, and reset it."""
    credentials = json.loads(Path("/run/secrets/demo.json").read_text())
    user_id = credentials["user_id"]
    password = credentials["password"]
    if not isinstance(user_id, str) or not user_id.isdecimal():
        raise ValueError("The demo identity must be pinned to a numeric user ID")
    if not isinstance(password, str) or not password:
        raise ValueError("The demo password must be configured")
    settings = Settings()  # type: ignore[call-arg]
    zitadel = Zitadel(settings)
    identity = zitadel.call("GET", f"/v2/users/{quote(user_id, safe='')}")["user"]
    if (
        identity.get("username") != "demo"
        or identity["details"]["resourceOwner"] != settings.login_org_id
        or identity.get("state") not in {"USER_STATE_ACTIVE", "USER_STATE_LOCKED"}
        or "human" not in identity
    ):
        raise RuntimeError("Refusing to reset an unexpected demo identity")
    if identity["state"] == "USER_STATE_LOCKED":
        # Anyone can trip the lockout policy with wrong demo passwords.
        zitadel.call("POST", f"/v2/users/{user_id}/unlock", {})
        print("Demo identity was locked out; unlocked it", flush=True)
    zitadel.call(
        "POST",
        f"/v2/users/{user_id}/password",
        {"newPassword": {"password": password, "changeRequired": False}},
    )
    path = settings.data_dir / "users" / f"{User(settings.oidc_issuer, user_id).id}.db"
    reset_book(path, dt.datetime.now(dt.timezone.utc).date())
    print("Demo password and book reset successfully", flush=True)


if __name__ == "__main__":
    main()
