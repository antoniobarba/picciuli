"""DDL of schema version 3, exactly as created by the 3.x releases."""

SCHEMA_V3 = """
CREATE TABLE meta (
	"key" VARCHAR NOT NULL,
	value VARCHAR NOT NULL,
	PRIMARY KEY ("key")
);
CREATE TABLE accounts (
	id INTEGER NOT NULL,
	name VARCHAR COLLATE "NOCASE" NOT NULL,
	type VARCHAR NOT NULL,
	opening_balance INTEGER NOT NULL,
	opening_date DATE,
	goal INTEGER,
	notes TEXT,
	position INTEGER NOT NULL,
	closed_on DATE,
	PRIMARY KEY (id),
	CONSTRAINT ck_account_type CHECK (type IN ('checking', 'savings', 'cash',
		'investment', 'other_asset', 'credit_card', 'loan', 'mortgage',
		'other_liability')),
	CONSTRAINT ck_account_dates CHECK (closed_on IS NULL OR opening_date IS NULL
		OR closed_on >= opening_date),
	CONSTRAINT ck_account_position CHECK (position >= 1),
	UNIQUE (name)
);
CREATE TABLE categories (
	id INTEGER NOT NULL,
	name VARCHAR COLLATE "NOCASE" NOT NULL,
	symbol VARCHAR(12) NOT NULL,
	parent_id INTEGER,
	position INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_category_symbol CHECK (length(symbol) BETWEEN 1 AND 12),
	CONSTRAINT ck_category_parent CHECK (parent_id IS NULL OR parent_id != id),
	CONSTRAINT ck_category_position CHECK (position >= 1),
	UNIQUE (name),
	FOREIGN KEY(parent_id) REFERENCES categories (id) ON DELETE RESTRICT
);
CREATE TABLE periods (
	id INTEGER NOT NULL,
	name VARCHAR NOT NULL,
	start_date DATE NOT NULL,
	end_date DATE,
	PRIMARY KEY (id),
	CONSTRAINT ck_period_dates CHECK (end_date IS NULL OR start_date <= end_date)
);
CREATE INDEX ix_periods_start_date ON periods (start_date);
CREATE TABLE transactions (
	id INTEGER NOT NULL,
	date DATE NOT NULL,
	description VARCHAR,
	notes TEXT,
	PRIMARY KEY (id)
);
CREATE INDEX ix_transactions_date ON transactions (date);
CREATE TABLE securities (
	id INTEGER NOT NULL,
	name VARCHAR COLLATE "NOCASE" NOT NULL,
	symbol VARCHAR,
	isin VARCHAR(12),
	currency VARCHAR(3) NOT NULL,
	kind VARCHAR NOT NULL,
	notes TEXT,
	PRIMARY KEY (id),
	CONSTRAINT ck_security_kind CHECK (kind IN ('stock', 'etf', 'fund', 'bond',
		'crypto', 'other')),
	CONSTRAINT ck_security_currency CHECK (length(currency) = 3),
	UNIQUE (name),
	UNIQUE (isin)
);
CREATE TABLE exchange_rates (
	id INTEGER NOT NULL,
	currency VARCHAR(3) NOT NULL,
	date DATE NOT NULL,
	rate INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_exchange_rate_positive CHECK (rate > 0),
	CONSTRAINT ck_exchange_rate_currency CHECK (length(currency) = 3),
	CONSTRAINT uq_exchange_rate_currency_date UNIQUE (currency, date)
);
CREATE TABLE budgets (
	id INTEGER NOT NULL,
	category_id INTEGER NOT NULL,
	period_id INTEGER NOT NULL,
	amount INTEGER NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_budget_amount CHECK (amount >= 0),
	CONSTRAINT uq_budget_category_period UNIQUE (category_id, period_id),
	FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE CASCADE,
	FOREIGN KEY(period_id) REFERENCES periods (id) ON DELETE CASCADE
);
CREATE TABLE trades (
	transaction_id INTEGER NOT NULL,
	kind VARCHAR NOT NULL,
	account_id INTEGER NOT NULL,
	security_id INTEGER NOT NULL,
	quantity INTEGER NOT NULL,
	amount INTEGER NOT NULL,
	other_account_id INTEGER,
	fee INTEGER NOT NULL,
	fee_category_id INTEGER,
	tax INTEGER NOT NULL,
	tax_category_id INTEGER,
	gain_category_id INTEGER,
	PRIMARY KEY (transaction_id),
	CONSTRAINT ck_trade_kind CHECK (kind IN ('buy', 'sell')),
	CONSTRAINT ck_trade_quantity CHECK (quantity > 0),
	CONSTRAINT ck_trade_amount CHECK (amount > 0),
	CONSTRAINT ck_trade_fees CHECK (fee >= 0 AND tax >= 0),
	CONSTRAINT ck_trade_buy CHECK (kind = 'sell' OR (tax = 0 AND
		tax_category_id IS NULL AND gain_category_id IS NULL)),
	FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE CASCADE,
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT,
	FOREIGN KEY(security_id) REFERENCES securities (id) ON DELETE RESTRICT,
	FOREIGN KEY(other_account_id) REFERENCES accounts (id) ON DELETE RESTRICT,
	FOREIGN KEY(fee_category_id) REFERENCES categories (id) ON DELETE RESTRICT,
	FOREIGN KEY(tax_category_id) REFERENCES categories (id) ON DELETE RESTRICT,
	FOREIGN KEY(gain_category_id) REFERENCES categories (id) ON DELETE RESTRICT
);
CREATE TABLE splits (
	id INTEGER NOT NULL,
	transaction_id INTEGER NOT NULL,
	position INTEGER NOT NULL,
	account_id INTEGER,
	category_id INTEGER,
	amount INTEGER NOT NULL,
	memo VARCHAR,
	security_id INTEGER,
	quantity INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT ck_split_amount CHECK (amount != 0 OR security_id IS NOT NULL),
	CONSTRAINT ck_split_kind CHECK (account_id IS NULL OR category_id IS NULL),
	CONSTRAINT ck_split_security CHECK ((security_id IS NULL AND quantity IS NULL)
		OR (security_id IS NOT NULL AND quantity IS NOT NULL AND quantity != 0
		AND account_id IS NOT NULL)),
	FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE CASCADE,
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT,
	FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE RESTRICT,
	FOREIGN KEY(security_id) REFERENCES securities (id) ON DELETE RESTRICT
);
CREATE INDEX ix_splits_category ON splits (category_id);
CREATE INDEX ix_splits_security ON splits (security_id);
CREATE INDEX ix_splits_account ON splits (account_id);
CREATE INDEX ix_splits_transaction_id ON splits (transaction_id);
CREATE TABLE prices (
	id INTEGER NOT NULL,
	security_id INTEGER NOT NULL,
	date DATE NOT NULL,
	price INTEGER NOT NULL,
	source VARCHAR,
	PRIMARY KEY (id),
	CONSTRAINT ck_price_positive CHECK (price > 0),
	CONSTRAINT uq_price_security_date UNIQUE (security_id, date),
	FOREIGN KEY(security_id) REFERENCES securities (id) ON DELETE CASCADE
);
"""
