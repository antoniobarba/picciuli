"""Investment endpoints: valuations, buying, selling and price refreshes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from picciuli.limits import MAX_ID
from picciuli_api.deps import BookDep, ContextDep
from picciuli_api.errors import PROVIDER_RESPONSES
from picciuli_api.schemas.accounts import NetWorthOut
from picciuli_api.schemas.base import Date, PathId, QueryDate, QueryPositiveDecimal
from picciuli_api.schemas.investments import (
    AccountValuationOut,
    BuyCreate,
    HoldingOut,
    PriceUpdateOut,
    RefreshExchangeRates,
    RefreshPrices,
    SaleCostOut,
    SellCreate,
)
from picciuli_api.schemas.transactions import TransactionOut

router = APIRouter(prefix="/investments", tags=["investments"])


@router.get("/valuations")
def list_valuations(
    book: BookDep, as_of: QueryDate = None, include_closed: bool = False
) -> list[AccountValuationOut]:
    """Market value of every account."""
    found = book.investments.valuations(as_of=as_of, include_closed=include_closed)
    return [AccountValuationOut.model_validate(v) for v in found]


@router.get("/net-worth")
def market_net_worth(book: BookDep, as_of: QueryDate = None) -> NetWorthOut:
    """Net worth with holdings at market value."""
    return NetWorthOut.model_validate(book.investments.net_worth(as_of=as_of))


@router.post("/buy", status_code=status.HTTP_201_CREATED)
def buy(book: BookDep, body: BuyCreate) -> TransactionOut:
    """Record a purchase of shares, paid from cash or from another account."""
    transaction = book.investments.record_buy(
        body.date,
        account_id=body.account_id,
        security_id=body.security_id,
        quantity=body.quantity,
        cost=body.cost,
        from_account_id=body.from_account_id,
        fee=body.fee,
        fee_category_id=body.fee_category_id,
        description=body.description,
        notes=body.notes,
    )
    return TransactionOut.model_validate(transaction)


@router.put("/buy/{transaction_id:int}")
def update_buy(
    book: BookDep, transaction_id: PathId, body: BuyCreate
) -> TransactionOut:
    """Replace a transaction with a purchase of shares, keeping its id."""
    transaction = book.investments.update_buy(
        transaction_id,
        body.date,
        account_id=body.account_id,
        security_id=body.security_id,
        quantity=body.quantity,
        cost=body.cost,
        from_account_id=body.from_account_id,
        fee=body.fee,
        fee_category_id=body.fee_category_id,
        description=body.description,
        notes=body.notes,
    )
    return TransactionOut.model_validate(transaction)


@router.post("/sell", status_code=status.HTTP_201_CREATED)
def sell(book: BookDep, body: SellCreate) -> TransactionOut:
    """Record a sale of shares with its realized gain or loss."""
    transaction = book.investments.record_sell(
        body.date,
        account_id=body.account_id,
        security_id=body.security_id,
        quantity=body.quantity,
        proceeds=body.proceeds,
        to_account_id=body.to_account_id,
        fee=body.fee,
        fee_category_id=body.fee_category_id,
        tax=body.tax,
        tax_category_id=body.tax_category_id,
        gain_category_id=body.gain_category_id,
        description=body.description,
        notes=body.notes,
    )
    return TransactionOut.model_validate(transaction)


@router.put("/sell/{transaction_id:int}")
def update_sell(
    book: BookDep, transaction_id: PathId, body: SellCreate
) -> TransactionOut:
    """Replace a transaction with a sale of shares, keeping its id.

    The cost of the sold shares is computed again, ignoring the transaction.
    """
    transaction = book.investments.update_sell(
        transaction_id,
        body.date,
        account_id=body.account_id,
        security_id=body.security_id,
        quantity=body.quantity,
        proceeds=body.proceeds,
        to_account_id=body.to_account_id,
        fee=body.fee,
        fee_category_id=body.fee_category_id,
        tax=body.tax,
        tax_category_id=body.tax_category_id,
        gain_category_id=body.gain_category_id,
        description=body.description,
        notes=body.notes,
    )
    return TransactionOut.model_validate(transaction)


@router.post("/refresh-prices", responses=PROVIDER_RESPONSES)
def refresh_prices(
    book: BookDep, context: ContextDep, body: RefreshPrices | None = None
) -> PriceUpdateOut:
    """Download the latest prices and the exchange rates they need.

    Quotes are shared between users and reused for 15 minutes (configurable),
    so refreshing often does not overload the price provider.
    """
    body = body or RefreshPrices()
    settings = book.settings.get()
    update = book.investments.refresh_prices(
        context.providers.prices(settings.price_provider),
        rate_provider=context.providers.rates(settings.rate_provider),
        security_ids=body.security_ids,
        history_start=body.history_start,
    )
    return PriceUpdateOut.model_validate(update)


@router.post("/refresh-exchange-rates", responses=PROVIDER_RESPONSES)
def refresh_exchange_rates(
    book: BookDep, context: ContextDep, body: RefreshExchangeRates | None = None
) -> PriceUpdateOut:
    """Download the latest exchange rates (shared cache, like prices)."""
    body = body or RefreshExchangeRates()
    settings = book.settings.get()
    update = book.investments.refresh_exchange_rates(
        context.providers.rates(settings.rate_provider),
        currencies=body.currencies,
        history_start=body.history_start,
    )
    return PriceUpdateOut.model_validate(update)


@router.get("/{account_id:int}/valuation")
def account_valuation(
    book: BookDep, account_id: PathId, as_of: QueryDate = None
) -> AccountValuationOut:
    """Market value of one account."""
    valuation = book.investments.valuation(account_id, as_of=as_of)
    return AccountValuationOut.model_validate(valuation)


@router.get("/{account_id:int}/holdings")
def account_holdings(
    book: BookDep, account_id: PathId, as_of: QueryDate = None
) -> list[HoldingOut]:
    """Securities held in one account."""
    found = book.investments.holdings(account_id, as_of=as_of)
    return [HoldingOut.model_validate(h) for h in found]


@router.get("/{account_id:int}/sale-cost")
def sale_cost(
    book: BookDep,
    account_id: PathId,
    security_id: Annotated[int, Query(ge=1, le=MAX_ID)],
    quantity: Annotated[QueryPositiveDecimal, Query(examples=["1.5"])],
    date: Date,
    excluding: Annotated[int | None, Query(ge=1, le=MAX_ID)] = None,
) -> SaleCostOut:
    """Cost basis that selling `quantity` shares on `date` would remove.

    `excluding` ignores one transaction, such as the sale being edited.
    """
    cost = book.investments.sale_cost(
        account_id, security_id, quantity, date=date, excluding=excluding
    )
    return SaleCostOut(cost=cost)
