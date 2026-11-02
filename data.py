from datetime import datetime
from typing import TypedDict

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    URL,
    create_engine,
    event,
    func,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class CategoryRecord(TypedDict):
    id: int
    name: str


class PeriodRecord(TypedDict):
    id: int
    start_date: datetime
    end_date: datetime


class CashFlowRecord(TypedDict):
    id: int
    amount: int
    description: str | None
    category_id: int
    occurred_at: datetime


class CategoryBalance(TypedDict):
    category_id: int
    category_name: str
    balance: int


class PeriodBalanceReport(TypedDict):
    period: PeriodRecord
    categories: list[CategoryBalance]
    total: int


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    cash_flows: Mapped[list["CashFlow"]] = relationship(back_populates="category")
    budgets: Mapped[list["Budget"]] = relationship(back_populates="category")


class CashFlow(Base):
    __tablename__ = "cash_flows"

    id: Mapped[int] = mapped_column(primary_key=True)
    amount: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    category: Mapped[Category] = relationship(back_populates="cash_flows")


class Period(Base):
    __tablename__ = "periods"
    __table_args__ = (
        CheckConstraint("start_date <= end_date", name="valid_period_dates"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    start_date: Mapped[datetime] = mapped_column(DateTime)
    end_date: Mapped[datetime] = mapped_column(DateTime)
    budgets: Mapped[list["Budget"]] = relationship(back_populates="period")


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    amount: Mapped[int] = mapped_column(Integer)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    period_id: Mapped[int] = mapped_column(ForeignKey("periods.id"))
    category: Mapped[Category] = relationship(back_populates="budgets")
    period: Mapped[Period] = relationship(back_populates="budgets")


class Data:
    def __init__(self, filename: str):
        self.engine = create_engine(URL.create("sqlite", database=filename))

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.session_factory = sessionmaker(self.engine)
        Base.metadata.create_all(self.engine)

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _category_dict(category: Category) -> CategoryRecord:
        return {"id": category.id, "name": category.name}

    @staticmethod
    def _period_dict(period: Period) -> PeriodRecord:
        return {
            "id": period.id,
            "start_date": period.start_date,
            "end_date": period.end_date,
        }

    @staticmethod
    def _cash_flow_dict(cash_flow: CashFlow) -> CashFlowRecord:
        return {
            "id": cash_flow.id,
            "amount": cash_flow.amount,
            "description": cash_flow.description,
            "category_id": cash_flow.category_id,
            "occurred_at": cash_flow.occurred_at,
        }

    @staticmethod
    def _validate_period_dates(start_date: datetime, end_date: datetime) -> None:
        if not isinstance(start_date, datetime) or not isinstance(end_date, datetime):
            raise TypeError("period dates must be datetime instances")
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

    @staticmethod
    def _validate_amount(amount: int) -> None:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("amount must be an integer")

    @staticmethod
    def _normalize_category_name(name: str) -> str:
        if not isinstance(name, str):
            raise TypeError("category name must be a string")
        name = name.strip()
        if not name:
            raise ValueError("category name cannot be empty")
        return name

    def create_category(self, name: str) -> CategoryRecord:
        name = self._normalize_category_name(name)
        with self.session_factory.begin() as session:
            category = Category(name=name)
            session.add(category)
            session.flush()
            return self._category_dict(category)

    def get_category(self, category_id: int) -> CategoryRecord:
        with self.session_factory() as session:
            category = session.get(Category, category_id)
            if category is None:
                raise LookupError(f"category {category_id} does not exist")
            return self._category_dict(category)

    def list_categories(self) -> list[CategoryRecord]:
        with self.session_factory() as session:
            categories = session.scalars(
                select(Category).order_by(Category.name, Category.id)
            )
            return [self._category_dict(category) for category in categories]

    def update_category(self, category_id: int, name: str) -> CategoryRecord:
        name = self._normalize_category_name(name)
        with self.session_factory.begin() as session:
            category = session.get(Category, category_id)
            if category is None:
                raise LookupError(f"category {category_id} does not exist")
            category.name = name
            session.flush()
            return self._category_dict(category)

    def delete_category(self, category_id: int) -> None:
        with self.session_factory.begin() as session:
            category = session.get(Category, category_id)
            if category is None:
                raise LookupError(f"category {category_id} does not exist")
            session.delete(category)

    def create_period(
        self, start_date: datetime, end_date: datetime
    ) -> PeriodRecord:
        self._validate_period_dates(start_date, end_date)
        with self.session_factory.begin() as session:
            period = Period(start_date=start_date, end_date=end_date)
            session.add(period)
            session.flush()
            return self._period_dict(period)

    def get_period(self, period_id: int) -> PeriodRecord:
        with self.session_factory() as session:
            period = session.get(Period, period_id)
            if period is None:
                raise LookupError(f"period {period_id} does not exist")
            return self._period_dict(period)

    def list_periods(self) -> list[PeriodRecord]:
        with self.session_factory() as session:
            periods = session.scalars(
                select(Period).order_by(Period.start_date, Period.id)
            )
            return [self._period_dict(period) for period in periods]

    def update_period(
        self, period_id: int, start_date: datetime, end_date: datetime
    ) -> PeriodRecord:
        self._validate_period_dates(start_date, end_date)
        with self.session_factory.begin() as session:
            period = session.get(Period, period_id)
            if period is None:
                raise LookupError(f"period {period_id} does not exist")
            period.start_date = start_date
            period.end_date = end_date
            session.flush()
            return self._period_dict(period)

    def delete_period(self, period_id: int) -> None:
        with self.session_factory.begin() as session:
            period = session.get(Period, period_id)
            if period is None:
                raise LookupError(f"period {period_id} does not exist")
            session.delete(period)

    def create_cash_flow(
        self,
        amount: int,
        category_id: int,
        occurred_at: datetime,
        description: str | None = None,
    ) -> CashFlowRecord:
        self._validate_amount(amount)
        if not isinstance(occurred_at, datetime):
            raise TypeError("occurred_at must be a datetime instance")
        with self.session_factory.begin() as session:
            if session.get(Category, category_id) is None:
                raise LookupError(f"category {category_id} does not exist")
            cash_flow = CashFlow(
                amount=amount,
                category_id=category_id,
                occurred_at=occurred_at,
                description=description,
            )
            session.add(cash_flow)
            session.flush()
            return self._cash_flow_dict(cash_flow)

    def get_cash_flow(self, cash_flow_id: int) -> CashFlowRecord:
        with self.session_factory() as session:
            cash_flow = session.get(CashFlow, cash_flow_id)
            if cash_flow is None:
                raise LookupError(f"cash flow {cash_flow_id} does not exist")
            return self._cash_flow_dict(cash_flow)

    def list_cash_flows(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        category_id: int | None = None,
    ) -> list[CashFlowRecord]:
        if start_date is not None and not isinstance(start_date, datetime):
            raise TypeError("start_date must be a datetime instance")
        if end_date is not None and not isinstance(end_date, datetime):
            raise TypeError("end_date must be a datetime instance")
        if start_date is not None and end_date is not None:
            self._validate_period_dates(start_date, end_date)
        statement = select(CashFlow)
        if start_date is not None:
            statement = statement.where(CashFlow.occurred_at >= start_date)
        if end_date is not None:
            statement = statement.where(CashFlow.occurred_at <= end_date)
        if category_id is not None:
            statement = statement.where(CashFlow.category_id == category_id)
        statement = statement.order_by(CashFlow.occurred_at, CashFlow.id)
        with self.session_factory() as session:
            cash_flows = session.scalars(statement)
            return [self._cash_flow_dict(item) for item in cash_flows]

    def update_cash_flow(
        self,
        cash_flow_id: int,
        amount: int,
        category_id: int,
        occurred_at: datetime,
        description: str | None = None,
    ) -> CashFlowRecord:
        self._validate_amount(amount)
        if not isinstance(occurred_at, datetime):
            raise TypeError("occurred_at must be a datetime instance")
        with self.session_factory.begin() as session:
            cash_flow = session.get(CashFlow, cash_flow_id)
            if cash_flow is None:
                raise LookupError(f"cash flow {cash_flow_id} does not exist")
            if session.get(Category, category_id) is None:
                raise LookupError(f"category {category_id} does not exist")
            cash_flow.amount = amount
            cash_flow.category_id = category_id
            cash_flow.occurred_at = occurred_at
            cash_flow.description = description
            session.flush()
            return self._cash_flow_dict(cash_flow)

    def delete_cash_flow(self, cash_flow_id: int) -> None:
        with self.session_factory.begin() as session:
            cash_flow = session.get(CashFlow, cash_flow_id)
            if cash_flow is None:
                raise LookupError(f"cash flow {cash_flow_id} does not exist")
            session.delete(cash_flow)

    def get_period_balances(self, period_id: int) -> PeriodBalanceReport:
        with self.session_factory() as session:
            period = session.get(Period, period_id)
            if period is None:
                raise LookupError(f"period {period_id} does not exist")

            rows = session.execute(
                select(
                    Category.id,
                    Category.name,
                    func.coalesce(func.sum(CashFlow.amount), 0),
                )
                .outerjoin(
                    CashFlow,
                    (CashFlow.category_id == Category.id)
                    & (CashFlow.occurred_at >= period.start_date)
                    & (CashFlow.occurred_at <= period.end_date),
                )
                .group_by(Category.id, Category.name)
                .order_by(Category.name, Category.id)
            )
            categories = [
                {"category_id": category_id, "category_name": name, "balance": balance}
                for category_id, name, balance in rows
            ]
            return {
                "period": self._period_dict(period),
                "categories": categories,
                "total": sum(category["balance"] for category in categories),
            }
