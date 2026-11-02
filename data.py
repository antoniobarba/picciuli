from datetime import datetime, timedelta
from typing import TypedDict

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    URL,
    create_engine,
    event,
    func,
    inspect,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class CategoryRecord(TypedDict):
    id: int
    name: str
    parent_id: int | None
    parent_name: str | None


class PeriodRecord(TypedDict):
    id: int
    name: str
    start_date: datetime
    end_date: datetime | None


class CashFlowRecord(TypedDict):
    id: int
    amount: int
    description: str | None
    category_id: int
    occurred_at: datetime


class CategoryBalance(TypedDict):
    category_id: int
    category_name: str
    parent_id: int | None
    is_parent: bool
    balance: int


class PeriodBalanceReport(TypedDict):
    period: PeriodRecord
    categories: list[CategoryBalance]
    total: int


class BudgetRecord(TypedDict):
    id: int
    amount: int
    category_id: int
    period_id: int


class BudgetBalance(TypedDict):
    category_id: int
    category_name: str
    budget: int
    balance: int
    remaining: int


class PeriodBudgetReport(TypedDict):
    period: PeriodRecord
    categories: list[BudgetBalance]
    total_budget: int
    total_balance: int
    total_remaining: int


class Base(DeclarativeBase):
    pass


class CurrencySetting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=True,
    )
    parent: Mapped["Category | None"] = relationship(
        back_populates="children",
        remote_side=lambda: Category.id,
    )
    children: Mapped[list["Category"]] = relationship(
        back_populates="parent",
        passive_deletes=True,
    )
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
        CheckConstraint(
            "end_date IS NULL OR start_date <= end_date",
            name="valid_period_dates",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    start_date: Mapped[datetime] = mapped_column(DateTime)
    end_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    budgets: Mapped[list["Budget"]] = relationship(back_populates="period")


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="nonnegative_budget_amount"),
        UniqueConstraint("category_id", "period_id", name="unique_category_period_budget"),
    )

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
        with self.engine.connect() as connection:
            inspector = inspect(connection)
            missing_columns = {
                table_name: set(table.columns.keys())
                - {column["name"] for column in inspector.get_columns(table_name)}
                for table_name, table in Base.metadata.tables.items()
            }
        missing_columns = {
            table_name: missing
            for table_name, missing in missing_columns.items()
            if missing
        }
        if missing_columns:
            self.engine.dispose()
            details = "; ".join(
                f"{table}: {', '.join(sorted(columns))}"
                for table, columns in missing_columns.items()
            )
            raise RuntimeError(
                "The database schema is outdated "
                f"({details}); automatic migrations are not supported. "
                "Use a new database file."
            )
        with self.session_factory.begin() as session:
            if session.get(CurrencySetting, 1) is None:
                session.add(CurrencySetting(id=1, currency="$"))

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _category_dict(category: Category) -> CategoryRecord:
        return {
            "id": category.id,
            "name": category.name,
            "parent_id": category.parent_id,
            "parent_name": category.parent.name if category.parent else None,
        }

    @staticmethod
    def _period_dict(period: Period) -> PeriodRecord:
        return {
            "id": period.id,
            "name": period.name,
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
    def _budget_dict(budget: Budget) -> BudgetRecord:
        return {
            "id": budget.id,
            "amount": budget.amount,
            "category_id": budget.category_id,
            "period_id": budget.period_id,
        }

    @staticmethod
    def _validate_period_dates(
        start_date: datetime, end_date: datetime | None
    ) -> None:
        if not isinstance(start_date, datetime):
            raise TypeError("start_date must be a datetime instance")
        if end_date is not None and not isinstance(end_date, datetime):
            raise TypeError("end_date must be a datetime instance or None")
        if end_date is not None and start_date > end_date:
            raise ValueError("start_date must be on or before end_date")

    @staticmethod
    def _default_period_name(start_date: datetime) -> str:
        return start_date.strftime("%B %Y")

    @staticmethod
    def _validate_amount(amount: int) -> None:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("amount must be an integer")

    @staticmethod
    def _validate_budget_amount(amount: int) -> None:
        Data._validate_amount(amount)
        if amount < 0:
            raise ValueError("budget amount cannot be negative")

    @staticmethod
    def _normalize_category_name(name: str) -> str:
        if not isinstance(name, str):
            raise TypeError("category name must be a string")
        name = name.strip()
        if not name:
            raise ValueError("category name cannot be empty")
        return name

    def create_category(
        self, name: str, parent_id: int | None = None
    ) -> CategoryRecord:
        name = self._normalize_category_name(name)
        with self.session_factory.begin() as session:
            parent = None
            if parent_id is not None:
                parent = session.get(Category, parent_id)
                if parent is None:
                    raise LookupError(f"parent category {parent_id} does not exist")
                if parent.parent_id is not None:
                    raise ValueError("subcategories cannot have their own subcategories")
            category = Category(name=name, parent=parent)
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
            categories = session.scalars(select(Category).order_by(Category.name)).all()
            roots = [category for category in categories if category.parent_id is None]
            ordered = []
            for root in roots:
                ordered.append(root)
                ordered.extend(
                    sorted(root.children, key=lambda child: child.name.casefold())
                )
            return [self._category_dict(category) for category in ordered]

    def update_category(
        self,
        category_id: int,
        name: str,
        parent_id: int | None = None,
    ) -> CategoryRecord:
        name = self._normalize_category_name(name)
        with self.session_factory.begin() as session:
            category = session.get(Category, category_id)
            if category is None:
                raise LookupError(f"category {category_id} does not exist")
            if category.children and parent_id is not None:
                raise ValueError("a parent category cannot become a subcategory")
            parent = None
            if parent_id is not None:
                if parent_id == category_id:
                    raise ValueError("a category cannot be its own parent")
                parent = session.get(Category, parent_id)
                if parent is None:
                    raise LookupError(f"parent category {parent_id} does not exist")
                if parent.parent_id is not None:
                    raise ValueError("subcategories cannot have their own subcategories")
            category.parent = parent
            category.name = name
            session.flush()
            return self._category_dict(category)

    def delete_category(self, category_id: int) -> None:
        with self.session_factory.begin() as session:
            category = session.get(Category, category_id)
            if category is None:
                raise LookupError(f"category {category_id} does not exist")
            if category.children:
                raise ValueError("delete subcategories before deleting this category")
            session.delete(category)

    def get_currency(self) -> str:
        with self.session_factory() as session:
            setting = session.get(CurrencySetting, 1)
            if setting is None:
                raise RuntimeError("currency setting is missing")
            return setting.currency

    def set_currency(self, currency: str) -> str:
        if not isinstance(currency, str):
            raise TypeError("currency must be a string")
        currency = currency.strip()
        if not currency:
            raise ValueError("currency cannot be empty")
        if not currency.isprintable():
            raise ValueError("currency must contain only printable characters")
        with self.session_factory.begin() as session:
            setting = session.get(CurrencySetting, 1)
            if setting is None:
                setting = CurrencySetting(id=1, currency=currency)
                session.add(setting)
            else:
                setting.currency = currency
        return currency

    def create_period(
        self,
        start_date: datetime,
        end_date: datetime | None = None,
        name: str | None = None,
    ) -> PeriodRecord:
        self._validate_period_dates(start_date, end_date)
        if name is not None:
            name = self._normalize_category_name(name)
        name = name or self._default_period_name(start_date)
        with self.session_factory.begin() as session:
            periods = session.scalars(
                select(Period).order_by(Period.start_date)
            ).all()
            for existing in periods:
                if existing.end_date is None:
                    if existing.start_date >= start_date:
                        raise ValueError(
                            "a new period must start after the current open period"
                        )
                    existing.end_date = start_date - timedelta(microseconds=1)
            new_end = end_date or datetime.max
            for existing in periods:
                existing_end = existing.end_date or datetime.max
                if (
                    existing.start_date <= new_end
                    and start_date <= existing_end
                ):
                    raise ValueError("period dates cannot overlap")

            period = Period(name=name, start_date=start_date, end_date=end_date)
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
        self,
        period_id: int,
        start_date: datetime,
        end_date: datetime | None,
        name: str | None = None,
    ) -> PeriodRecord:
        self._validate_period_dates(start_date, end_date)
        if name is not None:
            name = self._normalize_category_name(name)
        with self.session_factory.begin() as session:
            period = session.get(Period, period_id)
            if period is None:
                raise LookupError(f"period {period_id} does not exist")
            other_periods = session.scalars(
                select(Period).where(Period.id != period_id)
            )
            for other in other_periods:
                period_end = end_date or datetime.max
                other_end = other.end_date or datetime.max
                if start_date <= other_end and other.start_date <= period_end:
                    raise ValueError("period dates cannot overlap")
            period.start_date = start_date
            period.end_date = end_date
            if name is not None:
                period.name = name
            session.flush()
            return self._period_dict(period)

    def get_period_for_date(self, day: datetime) -> PeriodRecord | None:
        if not isinstance(day, datetime):
            raise TypeError("day must be a datetime instance")
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1) - timedelta(microseconds=1)
        with self.session_factory() as session:
            period = session.scalar(
                select(Period)
                .where(
                    Period.start_date <= day_end,
                    (Period.end_date.is_(None)) | (Period.end_date >= day_start),
                )
                .order_by(Period.start_date.desc())
            )
            return self._period_dict(period) if period is not None else None

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
                    Category.parent_id,
                    func.coalesce(func.sum(CashFlow.amount), 0),
                )
                .outerjoin(
                    CashFlow,
                    (CashFlow.category_id == Category.id)
                    & (CashFlow.occurred_at >= period.start_date)
                    & (
                        (CashFlow.occurred_at <= period.end_date)
                        if period.end_date is not None
                        else True
                    ),
                )
                .group_by(Category.id, Category.name, Category.parent_id)
                .order_by(Category.name, Category.id)
            )
            balances = {
                category_id: {
                    "category_id": category_id,
                    "category_name": name,
                    "parent_id": parent_id,
                    "is_parent": False,
                    "balance": balance,
                }
                for category_id, name, parent_id, balance in rows
            }
            children_by_parent: dict[int, list[CategoryBalance]] = {}
            for category in balances.values():
                if category["parent_id"] is not None:
                    children_by_parent.setdefault(category["parent_id"], []).append(
                        category
                    )

            categories: list[CategoryBalance] = []
            for category in balances.values():
                if category["parent_id"] is not None:
                    continue
                children = children_by_parent.get(category["category_id"], [])
                if children:
                    category["is_parent"] = True
                    category["balance"] += sum(
                        child["balance"] for child in children
                    )
                categories.append(category)
                categories.extend(
                    sorted(children, key=lambda child: child["category_name"].casefold())
                )
            total = sum(
                category["balance"]
                for category in categories
                if category["parent_id"] is None
            )
            return {
                "period": self._period_dict(period),
                "categories": categories,
                "total": total,
            }

    def create_budget(
        self, amount: int, category_id: int, period_id: int
    ) -> BudgetRecord:
        self._validate_budget_amount(amount)
        with self.session_factory.begin() as session:
            if session.get(Category, category_id) is None:
                raise LookupError(f"category {category_id} does not exist")
            if session.get(Period, period_id) is None:
                raise LookupError(f"period {period_id} does not exist")
            budget = Budget(
                amount=amount,
                category_id=category_id,
                period_id=period_id,
            )
            session.add(budget)
            session.flush()
            return self._budget_dict(budget)

    def get_budget(self, budget_id: int) -> BudgetRecord:
        with self.session_factory() as session:
            budget = session.get(Budget, budget_id)
            if budget is None:
                raise LookupError(f"budget {budget_id} does not exist")
            return self._budget_dict(budget)

    def list_budgets(
        self,
        period_id: int | None = None,
        category_id: int | None = None,
    ) -> list[BudgetRecord]:
        statement = select(Budget)
        if period_id is not None:
            statement = statement.where(Budget.period_id == period_id)
        if category_id is not None:
            statement = statement.where(Budget.category_id == category_id)
        statement = statement.order_by(Budget.period_id, Budget.category_id)
        with self.session_factory() as session:
            budgets = session.scalars(statement)
            return [self._budget_dict(budget) for budget in budgets]

    def update_budget(
        self,
        budget_id: int,
        amount: int,
        category_id: int,
        period_id: int,
    ) -> BudgetRecord:
        self._validate_budget_amount(amount)
        with self.session_factory.begin() as session:
            budget = session.get(Budget, budget_id)
            if budget is None:
                raise LookupError(f"budget {budget_id} does not exist")
            if session.get(Category, category_id) is None:
                raise LookupError(f"category {category_id} does not exist")
            if session.get(Period, period_id) is None:
                raise LookupError(f"period {period_id} does not exist")
            budget.amount = amount
            budget.category_id = category_id
            budget.period_id = period_id
            session.flush()
            return self._budget_dict(budget)

    def delete_budget(self, budget_id: int) -> None:
        with self.session_factory.begin() as session:
            budget = session.get(Budget, budget_id)
            if budget is None:
                raise LookupError(f"budget {budget_id} does not exist")
            session.delete(budget)

    def get_period_budget_report(self, period_id: int) -> PeriodBudgetReport:
        with self.session_factory() as session:
            period = session.get(Period, period_id)
            if period is None:
                raise LookupError(f"period {period_id} does not exist")

            budget_rows = session.execute(
                select(Budget, Category.name)
                .join(Category, Budget.category_id == Category.id)
                .where(Budget.period_id == period_id)
                .order_by(Category.name, Category.id)
            )
            balances = dict(
                session.execute(
                    select(CashFlow.category_id, func.sum(CashFlow.amount))
                    .where(
                        CashFlow.occurred_at >= period.start_date,
                        (
                            CashFlow.occurred_at <= period.end_date
                            if period.end_date is not None
                            else True
                        ),
                    )
                    .group_by(CashFlow.category_id)
                ).all()
            )
            categories = []
            for budget, category_name in budget_rows:
                balance = balances.get(budget.category_id, 0) or 0
                categories.append(
                    {
                        "category_id": budget.category_id,
                        "category_name": category_name,
                        "budget": budget.amount,
                        "balance": balance,
                        "remaining": budget.amount + balance,
                    }
                )
            return {
                "period": self._period_dict(period),
                "categories": categories,
                "total_budget": sum(item["budget"] for item in categories),
                "total_balance": sum(item["balance"] for item in categories),
                "total_remaining": sum(item["remaining"] for item in categories),
            }
