# Migrating from v1

The original Picciuli console application (tag `v1-legacy`) stored everything as
cash flows of one implicit account, with loans and savings targets attached to
them. `tools/migrate_v1.py` converts such a file into the new format:

```bash
python tools/migrate_v1.py finance.db finance-v2.db [--main-account "Main"]
```

The old file is opened read-only. The new file must not already exist, and it is
removed if the conversion fails. The whole conversion runs in a single
transaction.

## Mapping

| v1                                   | v2                                                                       |
|--------------------------------------|--------------------------------------------------------------------------|
| currency                             | `settings.currency`                                                      |
| category (parent, symbol, order)     | category (names identical except for case get a ` (2)` suffix)           |
| period (datetimes)                   | period (dates; open-ended periods stay open-ended)                       |
| budget                               | budget                                                                   |
| *(implicit)*                         | checking account **Main** holding every cash flow                        |
| cash flow `a` in category C          | Main `a` / external `a` [C]                                              |
| loan of amount A                     | LOAN account with opening balance −A                                     |
| loan repayment `a`, principal `p ≥ 0`| Main `a` / loan `+p` / external `a+p` [C] (the interest)                 |
| new borrowing `a`, principal `p < 0` | Main `a−p` / loan `p` / external `a` [C] (a purchase financed by the loan)|
| savings target of amount T           | SAVINGS account with goal T                                              |
| savings contribution `a`             | transfer: Main `a` / savings `−a` (no category)                          |

Splits with a zero amount are omitted.

## Checks and differences

After the conversion the script checks that:

- each loan's balance equals minus its old remaining principal;
- each savings account's balance equals its old accrued amount;
- Main's balance equals the old overall total, minus any new borrowing (which
  Main never actually paid).

If any check fails, the conversion is aborted. The script reports warnings when
the result intentionally differs from v1:

- **Savings contributions** become transfers, which have no category. In v1
  they counted as expenses in their category, so v2 category totals and budgets
  show less spending for those categories.
- **New borrowing** is treated as a purchase financed by the loan. The full
  amount is an expense in its category, the loan grows, and Main only pays the
  difference (fees).
- **Renamed categories or accounts**, when names clashed.

Review these points after migrating, then start recording directly into the new
accounts: for example, change Main's type or opening balance, or split it into
real bank accounts with transfers.
