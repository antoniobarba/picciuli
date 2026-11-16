# Wishlist

A review of Picciuli from the point of view of someone with a salary,
everyday expenses, debts, savings and small investments, who wants to track
every expense, budget each month, pay off debt and reach savings goals.
It is based on the code and documentation, not on running the app.

**Overall:** The basics are well built: exact money handling, split
transactions, loan principal/interest, budgets with subcategories, goals with
a target month (ETA), investment gains, import/export, keyboard shortcuts and
an installable app. The main gaps are in the daily routine and in planning
ahead. The app records the past well but does little to help plan the coming
months, and entering every expense takes more effort than it should.

## Functionality

### High priority
1. (deleted, done)
2. (deleted, done)
3. (deleted, done)
4. **Monthly plan.** Budgets cover expenses only. Add a plan per period:
   expected income, then fixed bills, debt payments, savings goals and
   budgets. Show "left to assign / safe to spend", and planned versus actual
   for income, savings and debt too.
5. **Bank statement import (CSV, then OFX/CAMT).** The only import is a
   Picciuli database file. Logging every expense by hand will be skipped
   sooner or later. Add CSV import with column mapping, duplicate detection
   and rules ("description contains ESSELUNGA → Food").
6. (deleted, done)

### Medium priority

7. **Remembered descriptions.** Typing a description you've used before
   should suggest it and fill in the category, account and usual amount.
8. **Tags** (for example "holiday-2026", "work-reimbursable") across
   categories, usable in Reports.
9. **Reconciliation.** Mark transactions as cleared and match a bank
   statement balance. This catches missing entries.
10. **History charts.** Reports only has a pie chart for one stretch of time.
    Add net worth over time, monthly income versus expenses, a spending trend
    per category, and debt going down and savings going up.
11. **Budget options:** roll leftover or overspent amounts into the next
    month; annual or sinking-fund budgets (car insurance, gifts) set aside
    monthly; percentage budgets (for example 50/30/20).
12. **Upcoming bills and projected balance.** A short list of the next
    scheduled payments, plus each account's expected balance at the end of
    the month.

### Lower priority

13. Attach receipt photos to transactions.
14. Export transactions or reports to CSV for spreadsheets and accountants.
15. Alerts, through the installed app or email: a budget at 80%/100%, a bill
    due, a goal reached.
16. Sharing a book with a partner or family member (today each user has their
    own book).

## User interface and graphics

1. **The Overview needs a real dashboard.** It now shows a calendar, the
   day's transactions and the period's categories. Account balances were
   removed recently. For this user, the first screen should answer: how much
   can I still spend this month, how are my budgets doing, what bills are
   coming, net worth and its trend, and progress on debts and goals. Consider
   cards above the calendar or a separate dashboard tab.
2. **Budget progress in colour.** The Budgets screen
   ([Budgets.tsx](apps/web/src/screens/Budgets.tsx)) shows red only when over
   budget. Add amber near the limit, and a "pace" marker showing how much
   should have been spent by today.
3. **Goal and debt cards.** Goal progress is a thin bar in a wide table, and
   on phones the Goal, Progress and ETA columns are hidden
   ([Accounts.tsx](apps/web/src/screens/Accounts.tsx)). Mobile users never see
   their goals. Use cards with a progress ring, the target date and the
   amount needed per month.
4. **Calendar heatmap.** Shade days by how much was spent, and mark upcoming
   scheduled transactions.
5. **Category icons and colours,** reused in lists, the pie chart and
   budgets. This makes long lists much quicker to scan.
6. **Theme switch.** Dark mode follows the operating system only; add
   Light / Dark / System in Settings.
7. **Better empty states.** Many empty screens show only one line of text; a
   short explanation with a button to act would help new users.

## Ease of use

1. **Guided setup for new users.** A new book is completely empty: no
   categories, no periods, no budgets. Then "create an account first",
   "create a period first" and "create a category first" messages block the
   user one at a time. Add a short wizard: currency → accounts with balances
   → starter categories (suggested, editable) → payday-based monthly periods
   → optional budgets based on income.
2. **Hide accounting terms.** Words like "Split", "account lines vs external
   lines", "± totals must match", "open-ended period" and "enter a mortgage
   as -150000" ([AccountForm.tsx](apps/web/src/forms/AccountForm.tsx)) are
   accounting jargon. Suggested changes:
   - for liabilities, ask "How much do you owe?" as a positive number and
     change the sign internally;
   - rename Split to "Multiple categories" and offer a separate "Loan payment"
     form (amount → principal and interest worked out automatically);
   - replace "Periods" with "Months / pay cycles" for most users and keep
     custom periods as an advanced option.
3. **Faster expense entry.**
   - Remember the last account used and the categories you use most.
   - Show recent or frequent categories as tappable chips on mobile instead of
     a long dropdown.
   - Add "Save and add another".
   - Open the number keypad on mobile (`inputmode="decimal"`).
4. **Mobile navigation.** On phones, Reports and Categories sit behind
   "More". For tracking expenses, Budgets plus a central large "+" button
   probably matter more than Investments in the bottom bar. Consider letting
   users choose the tabs.
5. **One transaction list.** Transactions appear in the Overview (one day
   only, no search), the Register, and the category/period/budget dialogs,
   but there's no single "All transactions" screen with filters for date,
   account, category, amount and text, plus multi-select for bulk
   recategorize or delete.

## Quality-of-life improvements

1. **Undo.** After deleting or editing, show "Deleted · Undo" instead of only
   a confirmation before the action.
2. **Duplicate transaction** in the ⋯ menu, and **Split evenly** in the split
   editor.
3. **Search in the Overview,** or a global search in the command palette
   (Ctrl+K) that finds transactions.
4. **A calculator in amount fields:** typing `12.50+8.30` gives the total.
5. **Quick actions from the home-screen icon** (installed-app shortcuts) for
   "New expense", and a share target for receipt photos.
6. **Offline entry.** The app opens without a network but can't save
   anything. Queue new transactions and sync them later, since many expenses
   are logged in shops with poor signal.
7. **Category budget hints.** When creating a budget, show the last 3 months'
   average for that category.
8. **Automatic backups:** a scheduled export or an email reminder, beyond the
   manual SQLite export.
9. **Rounding savings** ("round up to save") and **income splitting on
   payday** (for example 10% to savings automatically).
10. **Number format by country** (for example 1.234,50 € versus €1,234.50).
    Today only the symbol and decimal digits can be set.

## Suggested order

1. Recurring transactions and payday-based monthly periods (biggest time
   saver).
2. Guided setup with starter categories, plus simpler liability, loan and
   split forms.
3. Debt planner (interest rates, snowball/avalanche) and savings goals with
   dates.
4. Dashboard on the Overview, with history charts in Reports.
5. CSV bank import with rules, and remembered descriptions.
6. Undo, duplicate, a full transaction list with bulk edit, and offline
   entry.
