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
    symbol: str
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
    loan_id: int | None
    principal_amount: int | None


class LoanRecord(TypedDict):
    id: int
    name: str
    amount: int
    current_principal: int
    total_interest_paid: int


class SavingsTargetRecord(TypedDict):
    id: int
    name: str
    amount: int
    accrued_amount: int


class FinancialTotalsRecord(TypedDict):
    loans_pending: int
    savings_accrued: int


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
    symbol: Mapped[str] = mapped_column(String(12))
    sort_order: Mapped[int] = mapped_column(Integer)
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
    __table_args__ = (
        CheckConstraint(
            "(loan_id IS NULL AND principal_amount IS NULL) OR "
            "(loan_id IS NOT NULL AND principal_amount IS NOT NULL "
            "AND savings_target_id IS NULL AND amount < 0 "
            "AND principal_amount >= amount "
            "AND principal_amount <= -amount)",
            name="valid_loan_payment",
        ),
        CheckConstraint(
            "savings_target_id IS NULL OR "
            "(loan_id IS NULL AND principal_amount IS NULL AND amount != 0)",
            name="valid_savings_contribution",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    amount: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(String)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    loan_id: Mapped[int | None] = mapped_column(
        ForeignKey("loans.id", ondelete="RESTRICT"), nullable=True
    )
    principal_amount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    savings_target_id: Mapped[int | None] = mapped_column(
        ForeignKey("savings_targets.id", ondelete="RESTRICT"), nullable=True
    )
    category: Mapped[Category] = relationship(back_populates="cash_flows")
    loan: Mapped["Loan | None"] = relationship(back_populates="payments")
    savings_target: Mapped["SavingsTarget | None"] = relationship(
        back_populates="payments"
    )


class Loan(Base):
    __tablename__ = "loans"
    __table_args__ = (CheckConstraint("amount > 0", name="positive_loan_amount"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    amount: Mapped[int] = mapped_column(Integer)
    payments: Mapped[list[CashFlow]] = relationship(back_populates="loan")


class SavingsTarget(Base):
    __tablename__ = "savings_targets"
    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_savings_target_amount"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    amount: Mapped[int] = mapped_column(Integer)
    payments: Mapped[list[CashFlow]] = relationship(
        back_populates="savings_target"
    )


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
        if (
            missing_columns
            and set(missing_columns) <= {"cash_flows"}
            and missing_columns.get("cash_flows", set())
            <= {"loan_id", "principal_amount", "savings_target_id"}
        ):
            with self.engine.begin() as connection:
                missing_cash_flow_columns = missing_columns.get("cash_flows", set())
                if "loan_id" in missing_cash_flow_columns:
                    connection.exec_driver_sql(
                        "ALTER TABLE cash_flows ADD COLUMN loan_id "
                        "INTEGER REFERENCES loans(id) ON DELETE RESTRICT"
                    )
                if "principal_amount" in missing_cash_flow_columns:
                    connection.exec_driver_sql(
                        "ALTER TABLE cash_flows ADD COLUMN principal_amount INTEGER"
                    )
                if "savings_target_id" in missing_cash_flow_columns:
                    connection.exec_driver_sql(
                        "ALTER TABLE cash_flows ADD COLUMN savings_target_id "
                        "INTEGER REFERENCES savings_targets(id) ON DELETE RESTRICT"
                    )
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
        self._migrate_cash_flow_constraints()
        with self.session_factory.begin() as session:
            if session.get(CurrencySetting, 1) is None:
                session.add(CurrencySetting(id=1, currency="$"))

    def _migrate_cash_flow_constraints(self) -> None:
        with self.engine.connect() as connection:
            constraints = inspect(connection).get_check_constraints("cash_flows")
        constraints_by_name = {
            constraint["name"]: "".join(
                (constraint["sqltext"] or "").lower().split()
            )
            for constraint in constraints
        }
        old_loan_constraint = (
            "valid_loan_payment" in constraints_by_name
            and "principal_amount>=0" in constraints_by_name["valid_loan_payment"]
        )
        old_savings_constraint = (
            "valid_savings_contribution" in constraints_by_name
            and "amount<0" in constraints_by_name["valid_savings_contribution"]
        )
        if not old_loan_constraint and not old_savings_constraint:
            return

        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
            try:
                with connection.begin():
                    connection.exec_driver_sql(
                        """
                        CREATE TABLE cash_flows_new (
                            id INTEGER NOT NULL PRIMARY KEY,
                            amount INTEGER NOT NULL,
                            description VARCHAR,
                            category_id INTEGER NOT NULL
                                REFERENCES categories(id),
                            occurred_at DATETIME NOT NULL,
                            loan_id INTEGER REFERENCES loans(id)
                                ON DELETE RESTRICT,
                            principal_amount INTEGER,
                            savings_target_id INTEGER
                                REFERENCES savings_targets(id)
                                ON DELETE RESTRICT,
                            CONSTRAINT valid_loan_payment CHECK (
                                (loan_id IS NULL AND principal_amount IS NULL) OR
                                (loan_id IS NOT NULL AND principal_amount IS NOT NULL
                                 AND savings_target_id IS NULL AND amount < 0
                                 AND principal_amount >= amount
                                 AND principal_amount <= -amount)
                            ),
                            CONSTRAINT valid_savings_contribution CHECK (
                                savings_target_id IS NULL OR
                                (loan_id IS NULL AND principal_amount IS NULL
                                 AND amount != 0)
                            )
                        )
                        """
                    )
                    connection.exec_driver_sql(
                        """
                        INSERT INTO cash_flows_new (
                            id, amount, description, category_id, occurred_at,
                            loan_id, principal_amount, savings_target_id
                        )
                        SELECT
                            id, amount, description, category_id, occurred_at,
                            loan_id, principal_amount, savings_target_id
                        FROM cash_flows
                        """
                    )
                    connection.exec_driver_sql("DROP TABLE cash_flows")
                    connection.exec_driver_sql(
                        "ALTER TABLE cash_flows_new RENAME TO cash_flows"
                    )
            finally:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                connection.commit()

    def close(self) -> None:
        self.engine.dispose()

    @staticmethod
    def _category_dict(category: Category) -> CategoryRecord:
        return {
            "id": category.id,
            "name": category.name,
            "symbol": category.symbol,
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
            "loan_id": cash_flow.loan_id,
            "principal_amount": cash_flow.principal_amount,
            "savings_target_id": cash_flow.savings_target_id,
        }

    @staticmethod
    def _loan_dict(loan: Loan, payments: list[CashFlow]) -> LoanRecord:
        principal_paid = sum(payment.principal_amount or 0 for payment in payments)
        interest_paid = sum(
            abs(payment.amount) - abs(payment.principal_amount or 0)
            for payment in payments
        )
        return {
            "id": loan.id,
            "name": loan.name,
            "amount": loan.amount,
            "current_principal": loan.amount - principal_paid,
            "total_interest_paid": interest_paid,
        }

    @staticmethod
    def _savings_target_dict(
        target: SavingsTarget, payments: list[CashFlow]
    ) -> SavingsTargetRecord:
        return {
            "id": target.id,
            "name": target.name,
            "amount": target.amount,
            "accrued_amount": sum(-payment.amount for payment in payments),
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

    @staticmethod
    def _normalize_loan_name(name: str) -> str:
        if not isinstance(name, str):
            raise TypeError("loan name must be a string")
        name = name.strip()
        if not name:
            raise ValueError("loan name cannot be empty")
        return name

    @staticmethod
    def _normalize_savings_target_name(name: str) -> str:
        if not isinstance(name, str):
            raise TypeError("savings target name must be a string")
        name = name.strip()
        if not name:
            raise ValueError("savings target name cannot be empty")
        return name

    @staticmethod
    def _validate_loan_payment(
        session,
        amount: int,
        loan_id: int | None,
        principal_amount: int | None,
        cash_flow_id: int | None = None,
    ) -> None:
        if loan_id is None:
            if principal_amount is not None:
                raise ValueError("principal amount requires a loan")
            return
        if principal_amount is None:
            raise ValueError("principal amount is required for a loan payment")
        Data._validate_amount(principal_amount)
        if amount >= 0:
            raise ValueError("loan payment total amount must be negative")
        if principal_amount < amount or principal_amount > abs(amount):
            raise ValueError(
                "principal change must be between the negative and positive "
                "total payment"
            )
        loan = session.get(Loan, loan_id)
        if loan is None:
            raise LookupError(f"loan {loan_id} does not exist")
        statement = select(func.coalesce(func.sum(CashFlow.principal_amount), 0)).where(
            CashFlow.loan_id == loan_id
        )
        if cash_flow_id is not None:
            statement = statement.where(CashFlow.id != cash_flow_id)
        principal_paid = session.scalar(statement) or 0
        if principal_amount > loan.amount - principal_paid:
            raise ValueError("principal amount exceeds the remaining loan principal")

    @staticmethod
    def _validate_savings_contribution(
        session,
        amount: int,
        savings_target_id: int | None,
        loan_id: int | None,
        principal_amount: int | None,
        cash_flow_id: int | None = None,
    ) -> None:
        if savings_target_id is None:
            return
        if loan_id is not None or principal_amount is not None:
            raise ValueError("a cash-flow item can belong to only one goal")
        if amount == 0:
            raise ValueError("savings contribution amount cannot be zero")
        target = session.get(SavingsTarget, savings_target_id)
        if target is None:
            raise LookupError(f"savings target {savings_target_id} does not exist")
        statement = select(
            func.coalesce(func.sum(-CashFlow.amount), 0)
        ).where(CashFlow.savings_target_id == savings_target_id)
        if cash_flow_id is not None:
            statement = statement.where(CashFlow.id != cash_flow_id)
        accrued = session.scalar(statement) or 0
        change = -amount
        if change > target.amount - accrued:
            raise ValueError("savings contribution exceeds the remaining target amount")
        if change < -accrued:
            raise ValueError("savings withdrawal exceeds the accrued amount")

    def create_loan(self, name: str, amount: int) -> LoanRecord:
        name = self._normalize_loan_name(name)
        self._validate_amount(amount)
        if amount <= 0:
            raise ValueError("loan amount must be greater than zero")
        with self.session_factory.begin() as session:
            loan = Loan(name=name, amount=amount)
            session.add(loan)
            session.flush()
            return self._loan_dict(loan, [])

    def get_loan(self, loan_id: int) -> LoanRecord:
        with self.session_factory() as session:
            loan = session.get(Loan, loan_id)
            if loan is None:
                raise LookupError(f"loan {loan_id} does not exist")
            payments = session.scalars(
                select(CashFlow)
                .where(CashFlow.loan_id == loan_id)
                .order_by(CashFlow.occurred_at, CashFlow.id)
            ).all()
            return self._loan_dict(loan, payments)

    def list_loans(self) -> list[LoanRecord]:
        with self.session_factory() as session:
            loans = session.scalars(select(Loan).order_by(Loan.name, Loan.id)).all()
            return [
                self._loan_dict(
                    loan,
                    session.scalars(
                        select(CashFlow)
                        .where(CashFlow.loan_id == loan.id)
                        .order_by(CashFlow.occurred_at, CashFlow.id)
                    ).all(),
                )
                for loan in loans
            ]

    def create_savings_target(self, name: str, amount: int) -> SavingsTargetRecord:
        name = self._normalize_savings_target_name(name)
        self._validate_amount(amount)
        if amount <= 0:
            raise ValueError("savings target amount must be greater than zero")
        with self.session_factory.begin() as session:
            target = SavingsTarget(name=name, amount=amount)
            session.add(target)
            session.flush()
            return self._savings_target_dict(target, [])

    def get_savings_target(self, target_id: int) -> SavingsTargetRecord:
        with self.session_factory() as session:
            target = session.get(SavingsTarget, target_id)
            if target is None:
                raise LookupError(f"savings target {target_id} does not exist")
            payments = session.scalars(
                select(CashFlow)
                .where(CashFlow.savings_target_id == target_id)
                .order_by(CashFlow.occurred_at, CashFlow.id)
            ).all()
            return self._savings_target_dict(target, payments)

    def list_savings_targets(self) -> list[SavingsTargetRecord]:
        with self.session_factory() as session:
            targets = session.scalars(
                select(SavingsTarget).order_by(
                    SavingsTarget.name, SavingsTarget.id
                )
            ).all()
            return [
                self._savings_target_dict(
                    target,
                    session.scalars(
                        select(CashFlow)
                        .where(CashFlow.savings_target_id == target.id)
                        .order_by(CashFlow.occurred_at, CashFlow.id)
                    ).all(),
                )
                for target in targets
            ]

    def get_financial_totals(self) -> FinancialTotalsRecord:
        with self.session_factory() as session:
            loans_pending = session.scalar(
                select(
                    func.coalesce(
                        func.sum(
                            Loan.amount
                            - select(
                                func.coalesce(func.sum(CashFlow.principal_amount), 0)
                            )
                            .where(CashFlow.loan_id == Loan.id)
                            .scalar_subquery()
                        ),
                        0,
                    )
                )
            )
            savings_accrued = session.scalar(
                select(
                    func.coalesce(
                        func.sum(-CashFlow.amount),
                        0,
                    )
                ).where(CashFlow.savings_target_id.is_not(None))
            )
            return {
                "loans_pending": loans_pending or 0,
                "savings_accrued": savings_accrued or 0,
            }

    @staticmethod
    def _normalize_category_symbol(symbol: str | None, name: str) -> str:
        if symbol is None:
            symbol = (
                "".join(part[0] for part in name.split())[:4] or name[:4]
            ).upper()
        if not isinstance(symbol, str):
            raise TypeError("category symbol must be a string")
        symbol = symbol.strip()
        if not symbol:
            raise ValueError("category symbol cannot be empty")
        if len(symbol) > 12:
            raise ValueError("category symbol cannot exceed 12 characters")
        if not symbol.isprintable():
            raise ValueError("category symbol must contain printable characters")
        return symbol

    def create_category(
        self,
        name: str,
        parent_id: int | None = None,
        symbol: str | None = None,
    ) -> CategoryRecord:
        name = self._normalize_category_name(name)
        symbol = self._normalize_category_symbol(symbol, name)
        with self.session_factory.begin() as session:
            parent = None
            if parent_id is not None:
                parent = session.get(Category, parent_id)
                if parent is None:
                    raise LookupError(f"parent category {parent_id} does not exist")
                if parent.parent_id is not None:
                    raise ValueError("subcategories cannot have their own subcategories")
            sibling_parent_id = parent.id if parent is not None else None
            sibling_parent_filter = (
                Category.parent_id.is_(None)
                if sibling_parent_id is None
                else Category.parent_id == sibling_parent_id
            )
            last_order = session.scalar(
                select(func.max(Category.sort_order)).where(sibling_parent_filter)
            )
            category = Category(
                name=name,
                symbol=symbol,
                parent=parent,
                sort_order=(last_order or 0) + 1,
            )
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
                select(Category).order_by(Category.sort_order, Category.id)
            ).all()
            roots = [category for category in categories if category.parent_id is None]
            ordered = []
            for root in roots:
                ordered.append(root)
                ordered.extend(sorted(root.children, key=lambda child: (child.sort_order, child.id)))
            return [self._category_dict(category) for category in ordered]

    def update_category(
        self,
        category_id: int,
        name: str,
        parent_id: int | None = None,
        symbol: str | None = None,
        position: int | None = None,
    ) -> CategoryRecord:
        name = self._normalize_category_name(name)
        with self.session_factory.begin() as session:
            category = session.get(Category, category_id)
            if category is None:
                raise LookupError(f"category {category_id} does not exist")
            symbol = self._normalize_category_symbol(
                symbol if symbol is not None else category.symbol,
                name,
            )
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
            old_parent_id = category.parent_id
            new_parent_id = parent.id if parent is not None else None
            old_siblings = session.scalars(
                select(Category)
                .where(Category.parent_id == old_parent_id)
                .order_by(Category.sort_order, Category.id)
            ).all()
            current_group = [
                sibling for sibling in old_siblings if sibling.id != category_id
            ]
            if old_parent_id == new_parent_id:
                current_group.insert(
                    next(
                        (
                            index
                            for index, sibling in enumerate(old_siblings)
                            if sibling.id == category_id
                        ),
                        len(current_group),
                    ),
                    category,
                )
            target_siblings = current_group if old_parent_id == new_parent_id else session.scalars(
                select(Category)
                .where(Category.parent_id == new_parent_id)
                .order_by(Category.sort_order, Category.id)
            ).all()
            target_siblings = [
                sibling for sibling in target_siblings if sibling.id != category_id
            ]
            if position is None:
                position = (
                    current_group.index(category) + 1
                    if old_parent_id == new_parent_id
                    else len(target_siblings) + 1
                )
            if not isinstance(position, int) or isinstance(position, bool):
                raise TypeError("category position must be an integer")
            if position < 1 or position > len(target_siblings) + 1:
                raise ValueError(
                    f"category position must be between 1 and {len(target_siblings) + 1}"
                )
            target_siblings.insert(position - 1, category)
            if old_parent_id != new_parent_id:
                for index, sibling in enumerate(current_group, start=1):
                    sibling.sort_order = index
            category.parent = parent
            category.name = name
            category.symbol = symbol
            for index, sibling in enumerate(target_siblings, start=1):
                sibling.sort_order = index
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
                if (
                    existing.end_date is None
                    and existing.start_date < start_date
                ):
                    existing.end_date = start_date - timedelta(microseconds=1)

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
        loan_id: int | None = None,
        principal_amount: int | None = None,
        savings_target_id: int | None = None,
    ) -> CashFlowRecord:
        self._validate_amount(amount)
        if not isinstance(occurred_at, datetime):
            raise TypeError("occurred_at must be a datetime instance")
        with self.session_factory.begin() as session:
            if session.get(Category, category_id) is None:
                raise LookupError(f"category {category_id} does not exist")
            self._validate_loan_payment(
                session, amount, loan_id, principal_amount
            )
            self._validate_savings_contribution(
                session,
                amount,
                savings_target_id,
                loan_id,
                principal_amount,
            )
            cash_flow = CashFlow(
                amount=amount,
                category_id=category_id,
                occurred_at=occurred_at,
                description=description,
                loan_id=loan_id,
                principal_amount=principal_amount,
                savings_target_id=savings_target_id,
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
        loan_id: int | None = None,
        savings_target_id: int | None = None,
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
        if loan_id is not None:
            statement = statement.where(CashFlow.loan_id == loan_id)
        if savings_target_id is not None:
            statement = statement.where(
                CashFlow.savings_target_id == savings_target_id
            )
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
        loan_id: int | None = None,
        principal_amount: int | None = None,
        savings_target_id: int | None = None,
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
            self._validate_loan_payment(
                session,
                amount,
                loan_id,
                principal_amount,
                cash_flow.id if loan_id == cash_flow.loan_id else None,
            )
            self._validate_savings_contribution(
                session,
                amount,
                savings_target_id,
                loan_id,
                principal_amount,
                (
                    cash_flow.id
                    if savings_target_id == cash_flow.savings_target_id
                    else None
                ),
            )
            cash_flow.amount = amount
            cash_flow.category_id = category_id
            cash_flow.occurred_at = occurred_at
            cash_flow.description = description
            cash_flow.loan_id = loan_id
            cash_flow.principal_amount = principal_amount
            cash_flow.savings_target_id = savings_target_id
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
                    Category.sort_order,
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
                .group_by(
                    Category.id,
                    Category.name,
                    Category.parent_id,
                    Category.sort_order,
                )
                .order_by(Category.sort_order, Category.id)
            )
            balances = {
                category_id: {
                    "category_id": category_id,
                    "category_name": name,
                    "parent_id": parent_id,
                    "is_parent": False,
                    "balance": balance,
                }
                for category_id, name, parent_id, _, balance in rows
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
                categories.extend(children)
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
