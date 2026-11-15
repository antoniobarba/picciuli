"""DDL of schema version 1, exactly as created by the 2.0 development releases."""

SCHEMA_V1 = """
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
CREATE TABLE splits (
	id INTEGER NOT NULL,
	transaction_id INTEGER NOT NULL,
	position INTEGER NOT NULL,
	account_id INTEGER,
	category_id INTEGER,
	amount INTEGER NOT NULL,
	memo VARCHAR,
	PRIMARY KEY (id),
	CONSTRAINT ck_split_amount CHECK (amount != 0),
	CONSTRAINT ck_split_kind CHECK (account_id IS NULL OR category_id IS NULL),
	FOREIGN KEY(transaction_id) REFERENCES transactions (id) ON DELETE CASCADE,
	FOREIGN KEY(account_id) REFERENCES accounts (id) ON DELETE RESTRICT,
	FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE RESTRICT
);
CREATE INDEX ix_splits_transaction_id ON splits (transaction_id);
CREATE INDEX ix_splits_account ON splits (account_id);
CREATE INDEX ix_splits_category ON splits (category_id);
"""
