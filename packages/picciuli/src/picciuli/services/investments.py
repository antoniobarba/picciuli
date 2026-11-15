"""Investments: buying and selling shares, valuations and price refreshes."""

from __future__ import annotations

import builtins
import datetime as dt
from collections.abc import Callable, Collection
from decimal import Decimal
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from picciuli import _validation as v
from picciuli._db.queries import (
    ShareMove,
    account_balances,
    get_row,
    latest_prices,
    latest_rates,
    share_moves,
    to_account,
    to_exchange_rate,
    to_price,
    to_security,
)
from picciuli._db.session import UnitOfWork
from picciuli._db.tables import AccountRow, SecurityRow
from picciuli._decimal import (
    from_scaled,
    market_value,
    positive_decimal,
    share_of,
    to_scaled,
)
from picciuli.errors import PriceProviderError, ValidationError
from picciuli.model import (
    AccountClass,
    AccountSplit,
    AccountType,
    AccountValuation,
    CostMethod,
    ExchangeRate,
    ExternalSplit,
    Holding,
    NetWorth,
    Price,
    PriceUpdate,
    Settings,
    Split,
    Transaction,
)
from picciuli.prices import PricePoint, PriceProvider, create_provider
from picciuli.rates import ExchangeRateProvider, create_rate_provider

from .securities import store_price, store_rate
from .settings import read_settings
from .transactions import TransactionService

__all__ = ["InvestmentService"]

_T = TypeVar("_T")


def _fee(value: object, field: str) -> int:
    return v.non_negative_amount(value, field)


def _consume(lots: list[list[int]], quantity: int) -> int:
    """Remove `quantity` from the oldest lots and return their cost."""
    cost = 0
    while quantity > 0 and lots:
        lot = lots[0]
        if lot[0] <= quantity:
            cost += lot[1]
            quantity -= lot[0]
            lots.pop(0)
        else:
            part = share_of(lot[1], Decimal(quantity), Decimal(lot[0]))
            cost += part
            lot[0] -= quantity
            lot[1] -= part
            quantity = 0
    return cost


def _sale_cost(moves: list[ShareMove], quantity: int, method: CostMethod) -> int:
    held = sum(m.quantity for m in moves)
    basis = sum(m.amount for m in moves)
    if quantity > held:
        raise ValidationError(
            f"cannot sell {from_scaled(quantity)} shares: only "
            f"{from_scaled(held)} are held on that day"
        )
    if quantity == held:
        return basis
    if method is CostMethod.AVERAGE:
        return share_of(basis, Decimal(quantity), Decimal(held))
    lots: list[list[int]] = []
    for move in moves:
        if move.quantity > 0:
            lots.append([move.quantity, move.amount])
        else:
            _consume(lots, -move.quantity)
    return _consume(lots, quantity)


def _valuation(
    session: Session,
    account: AccountRow,
    as_of: dt.date | None,
    settings: Settings,
    prices: dict[int, Price],
    rates: dict[str, ExchangeRate],
) -> AccountValuation:
    balance = account_balances(session, until=as_of, account_ids=[account.id])[
        account.id
    ]
    totals: dict[int, list[int]] = {}
    for move in share_moves(session, account_id=account.id, until=as_of):
        total = totals.setdefault(move.security_id, [0, 0])
        total[0] += move.quantity
        total[1] += move.amount
    holdings = []
    for security_id, (quantity, cost) in totals.items():
        if quantity == 0 and cost == 0:
            continue
        security = to_security(get_row(session, SecurityRow, security_id, "security"))
        shares = from_scaled(quantity)
        price = prices.get(security_id)
        rate: Decimal | None = None
        if security.currency == settings.currency_code:
            rate = Decimal(1)
        elif security.currency in rates:
            rate = rates[security.currency].rate
        value = None
        if price is not None and rate is not None:
            value = market_value(shares, price.price, rate, settings.minor_digits)
        holdings.append(
            Holding(
                security=security,
                quantity=shares,
                cost_basis=cost,
                price=None if price is None else price.price,
                price_date=None if price is None else price.date,
                exchange_rate=rate,
                market_value=value,
            )
        )
    holdings.sort(key=lambda h: h.security.name.casefold())
    return AccountValuation(
        account=to_account(account),
        as_of=as_of,
        balance=balance,
        holdings=tuple(holdings),
    )


def _market_data(
    session: Session, as_of: dt.date | None
) -> tuple[Settings, dict[int, Price], dict[str, ExchangeRate]]:
    prices = {k: to_price(r) for k, r in latest_prices(session, as_of=as_of).items()}
    rates = {
        k: to_exchange_rate(r) for k, r in latest_rates(session, as_of=as_of).items()
    }
    return read_settings(session), prices, rates


class InvestmentService:
    """Record purchases and sales of shares and value investment accounts.

    Obtain it as [`Book.investments`][picciuli.Book.investments].

    The ledger balance of an investment account is its uninvested cash plus
    the *cost* of the shares it holds. Price changes are not transactions: the
    [market value][picciuli.services.InvestmentService.valuation] is computed
    on demand from the quantities held and the stored prices and exchange
    rates.

    Buying 1 share for 35 € from a checking account is a transfer that also
    moves the share: checking −35, investment +35 (+1 share). Selling it later
    for 40 € removes the share at its cost and records the 5 € realized gain as
    income: investment −35 (−1 share), checking +40, external +5.
    """

    def __init__(self, uow: UnitOfWork, transactions: TransactionService) -> None:
        self._uow = uow
        self._transactions = transactions

    def valuation(
        self, account_id: int, *, as_of: dt.date | None = None
    ) -> AccountValuation:
        """Return the holdings and market value of an account at the end of a day.

        Each holding is valued with the latest price on or before the day,
        converted with the latest exchange rate on or before the day.

        Args:
            account_id: The account (of any type; accounts without shares
                simply have no holdings).
            as_of: Day of the valuation; `None` includes every transaction and
                uses the latest prices.

        Raises:
            NotFoundError: If the account does not exist.
        """
        as_of = v.optional_date(as_of, "as_of")
        with self._uow.session() as session:
            account = get_row(session, AccountRow, account_id, "account")
            settings, prices, rates = _market_data(session, as_of)
            return _valuation(session, account, as_of, settings, prices, rates)

    def holdings(
        self, account_id: int, *, as_of: dt.date | None = None
    ) -> builtins.list[Holding]:
        """Return the holdings of an account (see `valuation`).

        Raises:
            NotFoundError: If the account does not exist.
        """
        return builtins.list(self.valuation(account_id, as_of=as_of).holdings)

    def valuations(
        self, *, as_of: dt.date | None = None, include_closed: bool = False
    ) -> builtins.list[AccountValuation]:
        """Return the valuation of every investment account, in display order.

        Args:
            as_of: Day of the valuations; `None` uses everything.
            include_closed: Whether to include accounts closed on or before
                `as_of` (or closed at all when `as_of` is `None`).
        """
        as_of = v.optional_date(as_of, "as_of")
        with self._uow.session() as session:
            settings, prices, rates = _market_data(session, as_of)
            rows = session.scalars(
                select(AccountRow)
                .where(AccountRow.type == AccountType.INVESTMENT.value)
                .order_by(AccountRow.position, AccountRow.id)
            )
            result = []
            for row in rows:
                closed = row.closed_on is not None and (
                    as_of is None or row.closed_on <= as_of
                )
                if closed and not include_closed:
                    continue
                result.append(_valuation(session, row, as_of, settings, prices, rates))
            return result

    def net_worth(self, *, as_of: dt.date | None = None) -> NetWorth:
        """Return net worth with investment accounts at market value.

        Holdings without a known market value count at cost.

        Args:
            as_of: Day of the computation; `None` uses everything.
        """
        as_of = v.optional_date(as_of, "as_of")
        assets = liabilities = 0
        with self._uow.session() as session:
            settings, prices, rates = _market_data(session, as_of)
            balances = account_balances(session, until=as_of)
            for row in session.scalars(select(AccountRow)):
                value = balances[row.id]
                if row.type == AccountType.INVESTMENT.value:
                    value = _valuation(
                        session, row, as_of, settings, prices, rates
                    ).market_value
                if AccountType(row.type).account_class is AccountClass.LIABILITY:
                    liabilities += value
                else:
                    assets += value
        return NetWorth(as_of=as_of, assets=assets, liabilities=liabilities)

    def sale_cost(
        self,
        account_id: int,
        security_id: int,
        quantity: Decimal | int,
        *,
        date: dt.date,
    ) -> int:
        """Return the cost basis that selling `quantity` shares would remove.

        It uses the [cost method][picciuli.model.Settings] of the
        book and the transactions dated on or before `date`. Useful to preview
        the realized gain before recording a sale.

        Raises:
            NotFoundError: If the account or the security does not exist.
            ValidationError: If an argument is invalid or not enough shares
                are held.
        """
        day = v.date(date, "date")
        shares = positive_decimal(quantity, "quantity")
        with self._uow.session() as session:
            get_row(session, AccountRow, account_id, "account")
            get_row(session, SecurityRow, security_id, "security")
            moves = share_moves(
                session, account_id=account_id, security_id=security_id, until=day
            )
            return _sale_cost(
                moves, to_scaled(shares), read_settings(session).cost_method
            )

    def record_buy(
        self,
        date: dt.date,
        *,
        account_id: int,
        security_id: int,
        quantity: Decimal | int,
        cost: int,
        from_account_id: int | None = None,
        fee: int = 0,
        fee_category_id: int | None = None,
        description: str | None = None,
        notes: str | None = None,
    ) -> Transaction:
        """Record a purchase of shares.

        The shares enter `account_id` at `cost`, which becomes their cost
        basis. The money comes from `from_account_id`, or from the cash of the
        investment account itself when it is `None`. A `fee` is paid by the
        same account and recorded as an expense; to include it in the cost
        basis instead, add it to `cost`.

        Args:
            date: Day of the purchase.
            account_id: Investment account receiving the shares.
            security_id: The security bought.
            quantity: Positive number of shares (up to 8 decimals).
            cost: Positive price paid for the shares, in minor units.
            from_account_id: Account paying, or `None` for the investment
                account's own cash.
            fee: Commission, in minor units (zero or positive).
            fee_category_id: Category of the fee expense.
            description: Short description; defaults to "Buy <security>".
            notes: Free text.

        Raises:
            ValidationError: If an argument is invalid.
            NotFoundError: If an account, the security or a category does not
                exist.
            ConflictError: If an account is closed.
        """
        shares = positive_decimal(quantity, "quantity")
        cost = v.positive_amount(cost, "cost")
        fee = _fee(fee, "fee")
        payer = account_id if from_account_id is None else from_account_id
        with self._uow.session() as session:
            security = get_row(session, SecurityRow, security_id, "security")
            splits: list[Split] = [
                AccountSplit(
                    account_id, cost, security_id=security_id, quantity=shares
                ),
                AccountSplit(payer, -(cost + fee)),
            ]
            if fee:
                splits.append(ExternalSplit(-fee, fee_category_id, "Fee"))
            return self._transactions.create(
                date,
                splits,
                description=description or f"Buy {security.name}",
                notes=notes,
            )

    def record_sell(
        self,
        date: dt.date,
        *,
        account_id: int,
        security_id: int,
        quantity: Decimal | int,
        proceeds: int,
        to_account_id: int | None = None,
        fee: int = 0,
        fee_category_id: int | None = None,
        tax: int = 0,
        tax_category_id: int | None = None,
        gain_category_id: int | None = None,
        description: str | None = None,
        notes: str | None = None,
    ) -> Transaction:
        """Record a sale of shares and its realized gain or loss.

        The cost of the sold shares is computed with the book's
        [cost method][picciuli.model.Settings] from the
        transactions dated on or before the sale, and removed from the account.
        The difference between `proceeds` and that cost is recorded as an
        external split in `gain_category_id`: positive (income) for a gain,
        negative (expense) for a loss. The money received, minus fee and tax,
        goes to `to_account_id`, or stays in the investment account as cash.

        Recorded sales keep their amounts: editing earlier purchases or
        changing the cost method later does not recompute them.

        Args:
            date: Day of the sale.
            account_id: Investment account holding the shares.
            security_id: The security sold.
            quantity: Positive number of shares sold.
            proceeds: Gross amount received for the shares, in minor units
                (positive).
            to_account_id: Account receiving the money, or `None` for the
                investment account's own cash.
            fee: Commission, in minor units (zero or positive).
            fee_category_id: Category of the fee expense.
            tax: Tax withheld on the sale, in minor units (zero or positive).
            tax_category_id: Category of the tax expense.
            gain_category_id: Category of the realized gain or loss.
            description: Short description; defaults to "Sell <security>".
            notes: Free text.

        Raises:
            ValidationError: If an argument is invalid or not enough shares
                are held.
            NotFoundError: If an account, the security or a category does not
                exist.
            ConflictError: If an account is closed.
        """
        day = v.date(date, "date")
        shares = positive_decimal(quantity, "quantity")
        proceeds = v.positive_amount(proceeds, "proceeds")
        fee = _fee(fee, "fee")
        tax = _fee(tax, "tax")
        receiver = account_id if to_account_id is None else to_account_id
        with self._uow.session() as session:
            get_row(session, AccountRow, account_id, "account")
            security = get_row(session, SecurityRow, security_id, "security")
            moves = share_moves(
                session, account_id=account_id, security_id=security_id, until=day
            )
            cost = _sale_cost(
                moves, to_scaled(shares), read_settings(session).cost_method
            )
            splits: list[Split] = [
                AccountSplit(
                    account_id, -cost, security_id=security_id, quantity=-shares
                )
            ]
            received = proceeds - fee - tax
            if received:
                splits.append(AccountSplit(receiver, received))
            gain = proceeds - cost
            if gain:
                splits.append(ExternalSplit(gain, gain_category_id, "Realized gain"))
            if fee:
                splits.append(ExternalSplit(-fee, fee_category_id, "Fee"))
            if tax:
                splits.append(ExternalSplit(-tax, tax_category_id, "Tax"))
            return self._transactions.create(
                day,
                splits,
                description=description or f"Sell {security.name}",
                notes=notes,
            )

    def refresh_prices(
        self,
        provider: PriceProvider | None = None,
        *,
        rate_provider: ExchangeRateProvider | None = None,
        security_ids: Collection[int] | None = None,
        history_start: dt.date | None = None,
    ) -> PriceUpdate:
        """Download and store prices and the exchange rates they need.

        For every security with a symbol (or only those in `security_ids`),
        the latest quote is stored as the price of its trading day, replacing
        an earlier quote of the same day. Calling this repeatedly, for example
        every minute from a user interface, therefore keeps one price per day
        that follows the market. With `history_start`, daily closing prices
        since that day are stored too.

        Exchange rates are downloaded, with the exchange-rate provider, for
        every currency of those securities that differs from the book's
        [currency code][picciuli.model.Settings].

        Network access happens before the database is touched; failures of
        single securities or currencies are reported in
        [`PriceUpdate.errors`][picciuli.model.PriceUpdate] and do not stop the
        others.

        Args:
            provider: Price provider to use; `None` creates the one selected
                in the book settings.
            rate_provider: Exchange-rate provider to use; `None` creates the
                one selected in the book settings (only if a rate is needed).
            security_ids: Securities to refresh; `None` refreshes all those
                with a symbol.
            history_start: First day of the daily history to download, or
                `None` for the latest quotes only.

        Raises:
            NotFoundError: If a security in `security_ids` does not exist.
            ValidationError: If an argument is invalid.
            PriceProviderError: If the price provider in the settings is
                unknown.
        """
        history_start = v.optional_date(history_start, "history_start")
        with self._uow.session() as session:
            settings = read_settings(session)
            if security_ids is None:
                rows = builtins.list(
                    session.scalars(
                        select(SecurityRow).where(SecurityRow.symbol.is_not(None))
                    )
                )
            else:
                rows = [
                    get_row(
                        session, SecurityRow, v.identifier(i, "security id"), "security"
                    )
                    for i in security_ids
                ]
            securities = [to_security(row) for row in rows]
        if provider is None:
            provider = create_provider(settings.price_provider)
        today = dt.date.today()
        errors: list[str] = []
        prices: list[tuple[int, dt.date, Decimal]] = []
        currencies: set[str] = set()
        for security in securities:
            if security.symbol is None:
                errors.append(f"{security.name}: no symbol to look up")
                continue
            try:
                quote = provider.latest(security.symbol)
                if quote.currency is not None and quote.currency != security.currency:
                    errors.append(
                        f"{security.name}: {security.symbol} is quoted in "
                        f"{quote.currency}, not {security.currency}"
                    )
                    continue
                points = _history(provider, security.symbol, history_start, today)
            except PriceProviderError as exc:
                errors.append(f"{security.name}: {exc}")
                continue
            prices.extend((security.id, p.date, p.price) for p in points)
            prices.append((security.id, quote.date, quote.price))
            if security.currency != settings.currency_code:
                currencies.add(security.currency)
        rates = _fetch_rates(
            rate_provider, settings, currencies, history_start, today, errors
        )
        with self._uow.session() as session:
            stored_prices = [
                to_price(store_price(session, sid, day, price, provider.id))
                for sid, day, price in prices
            ]
            stored_rates = [
                to_exchange_rate(store_rate(session, currency, day, rate))
                for currency, day, rate in rates
            ]
        return PriceUpdate(
            prices=_last_per_key(stored_prices, lambda p: (p.security_id, p.date)),
            exchange_rates=_last_per_key(stored_rates, lambda r: (r.currency, r.date)),
            errors=tuple(errors),
        )

    def refresh_exchange_rates(
        self,
        rate_provider: ExchangeRateProvider | None = None,
        *,
        currencies: Collection[str] | None = None,
        history_start: dt.date | None = None,
    ) -> PriceUpdate:
        """Download and store exchange rates into the book currency.

        Args:
            rate_provider: Provider to use; `None` creates the one selected in
                the book settings.
            currencies: ISO codes to refresh; `None` refreshes every currency
                of the securities that differs from the book currency.
            history_start: First day of the daily history to download, or
                `None` for the latest rates only.

        Returns:
            The stored rates, with no prices, and one error message per
            currency that could not be refreshed.

        Raises:
            ValidationError: If an argument is invalid.
        """
        history_start = v.optional_date(history_start, "history_start")
        with self._uow.session() as session:
            settings = read_settings(session)
            if currencies is None:
                codes = {
                    row
                    for row in session.scalars(select(SecurityRow.currency).distinct())
                }
            else:
                codes = {v.currency_code(c) for c in currencies}
        codes.discard(settings.currency_code or "")
        errors: list[str] = []
        rates = _fetch_rates(
            rate_provider, settings, codes, history_start, dt.date.today(), errors
        )
        with self._uow.session() as session:
            stored = [
                to_exchange_rate(store_rate(session, currency, day, rate))
                for currency, day, rate in rates
            ]
        return PriceUpdate(
            prices=(),
            exchange_rates=_last_per_key(stored, lambda r: (r.currency, r.date)),
            errors=tuple(errors),
        )


def _fetch_rates(
    rate_provider: ExchangeRateProvider | None,
    settings: Settings,
    currencies: Collection[str],
    history_start: dt.date | None,
    today: dt.date,
    errors: builtins.list[str],
) -> builtins.list[tuple[str, dt.date, Decimal]]:
    """Download rates of `currencies` into the book currency; record failures."""
    rates: builtins.list[tuple[str, dt.date, Decimal]] = []
    if not currencies:
        return rates
    code = settings.currency_code
    if code is None:
        errors.extend(
            f"{currency}: set the book currency code to convert prices"
            for currency in sorted(currencies)
        )
        return rates
    if rate_provider is None:
        try:
            rate_provider = create_rate_provider(settings.rate_provider)
        except PriceProviderError as exc:
            errors.append(f"exchange rates: {exc}")
            return rates
    for currency in sorted(currencies):
        try:
            quote = rate_provider.latest(currency, code)
            points = (
                []
                if history_start is None or history_start > today
                else rate_provider.history(currency, code, history_start, today)
            )
        except PriceProviderError as exc:
            errors.append(f"{currency}: {exc}")
            continue
        rates.extend((currency, p.date, p.rate) for p in points)
        rates.append((currency, quote.date, quote.rate))
    return rates


def _history(
    provider: PriceProvider, symbol: str, start: dt.date | None, today: dt.date
) -> builtins.list[PricePoint]:
    if start is None or start > today:
        return []
    return provider.history(symbol, start, today)


def _last_per_key(
    items: builtins.list[_T], key: Callable[[_T], object]
) -> tuple[_T, ...]:
    result: dict[object, _T] = {}
    for item in items:
        result[key(item)] = item
    return tuple(result.values())
