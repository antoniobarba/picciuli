import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { unwrap } from '../api/client';
import {
  useAccounts,
  useApiMutation,
  useBudgetReport,
  useCategories,
  useMoney,
  usePeriodsOn,
  usePeriodSummary,
  useTransactions,
} from '../api/queries';
import type { BudgetReport, Period, PeriodSummary, Transaction } from '../api/types';
import { useEditors } from '../app/editors';
import { Calendar } from '../components/Calendar';
import { DateField } from '../components/DateField';
import { useConfirm, useNotify } from '../components/feedback';
import { FormDialog } from '../components/forms';
import { Amount, Empty, RowMenu } from '../components/ui';
import { choosePeriod, cyclePeriod, dayFlows, shiftMonth, visibleRange } from '../lib/calendar';
import { isValidDay, longDate, parts, todayDay, type Day } from '../lib/dates';
import {
  byId,
  periodRange,
  transactionAccounts,
  transactionCategory,
  transactionTitle,
  transferAmount,
} from '../lib/format';
import { parseDate } from '../lib/forms';
import type { MoneyFormat } from '../lib/money';
import { useHotkeys } from '../lib/useHotkeys';
import { PeriodForm } from '../forms/PeriodForm';

function dayFromParams(value: string | null): Day | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const { year, month, day } = parts(value);
  return isValidDay(year, month, day) ? value : null;
}

export function Overview() {
  const money = useMoney();
  const editors = useEditors();
  const confirm = useConfirm();
  const notify = useNotify();
  const today = todayDay();
  const [params, setParams] = useSearchParams();
  const day = dayFromParams(params.get('day')) ?? today;
  const [periodId, setPeriodId] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [dialog, setDialog] = useState<'goto' | 'period' | null>(null);

  const selectDay = (next: Day) => {
    setParams(next === today ? {} : { day: next }, { replace: true });
    setSelectedId(null);
  };

  const { year, month } = parts(day);
  const [start, end] = visibleRange(year, month);
  const accounts = useAccounts(true);
  const categories = useCategories();
  const transactions = useTransactions({ start, end });
  const covering = usePeriodsOn(day).data ?? [];
  const period = choosePeriod(covering, periodId);
  const summary = usePeriodSummary(period?.id ?? null).data;
  const budgets = useBudgetReport(period?.id ?? null).data;

  const flows = useMemo(() => dayFlows(transactions.data ?? []), [transactions.data]);
  const dayTransactions = useMemo(
    () => (transactions.data ?? []).filter((transaction) => transaction.date === day),
    [transactions.data, day],
  );
  const accountMap = useMemo(() => byId(accounts.data), [accounts.data]);
  const categoryMap = useMemo(() => byId(categories.data), [categories.data]);
  const hasOpenAccounts = (accounts.data ?? []).some((account) => !account.is_closed);

  const remove = useApiMutation((api, id: number) =>
    unwrap(api.DELETE('/api/v1/transactions/{transaction_id}', { params: { path: { transaction_id: id } } })),
  );

  const selected =
    dayTransactions.find((t) => t.id === selectedId) ?? (dayTransactions.length === 1 ? dayTransactions[0] : undefined);

  const newTransaction = (on: Day = day) => {
    if (accounts.data && !hasOpenAccounts) {
      notify('Create an account first: open Accounts, then New.', { title: 'No accounts', kind: 'warning' });
      return;
    }
    editors.newTransaction({ day: on });
  };

  const deleteTransaction = async (transaction: Transaction | undefined) => {
    if (!transaction) {
      notify('No transaction selected on this day.');
      return;
    }
    if (await confirm({ title: `Delete “${transactionTitle(transaction)}”?` })) {
      try {
        await remove.mutateAsync(transaction.id);
      } catch (error) {
        notify(error instanceof Error ? error.message : String(error), { title: 'Cannot do that', kind: 'error' });
      }
    }
  };

  const cycle = (step: number) => {
    if (covering.length < 2) {
      notify('No other period covers this day.');
      return;
    }
    setPeriodId(cyclePeriod(covering, period?.id ?? null, step)?.id ?? null);
  };

  useHotkeys({
    n: () => newTransaction(),
    e: () => (selected ? editors.editTransaction(selected) : notify('No transaction selected on this day.')),
    d: () => void deleteTransaction(selected),
    Delete: () => void deleteTransaction(selected),
    t: () => selectDay(today),
    g: () => setDialog('goto'),
    '[': () => cycle(-1),
    ']': () => cycle(1),
    p: () => setDialog('period'),
    PageUp: () => selectDay(shiftMonth(day, -1)),
    PageDown: () => selectDay(shiftMonth(day, 1)),
  });

  return (
    <div className="overview">
      <div className="overview-calendar">
        <PeriodTitle period={period} covering={covering} onCycle={cycle} onStart={() => setDialog('period')} />
        <Calendar
          day={day}
          today={today}
          flows={flows}
          period={period}
          money={money}
          onSelect={selectDay}
          onActivate={newTransaction}
          onMonth={(step) => selectDay(shiftMonth(day, step))}
          autoFocus={window.matchMedia?.('(pointer: fine)').matches}
        />
        {summary ? (
          <div className="period-totals">
            <span>
              Income <Amount value={summary.income} money={money} />
            </span>
            <span>
              Expenses <Amount value={summary.expenses} money={money} />
            </span>
            <span>
              Net <Amount value={summary.net} money={money} plus bold />
            </span>
          </div>
        ) : null}
      </div>

      <div className="overview-details">
        <section className="card day-panel" aria-label="Transactions of the day">
          <div className="card-header">
            <h2>
              {longDate(day)}
              <small>
                {day === today ? ' · today' : ''} · {dayTransactions.length} transaction
                {dayTransactions.length === 1 ? '' : 's'}
              </small>
            </h2>
            <button type="button" className="button primary small hide-mobile" onClick={() => newTransaction()}>
              + New
            </button>
          </div>
          {!accounts.isLoading && !hasOpenAccounts ? (
            <Empty>
              Welcome! Start by creating an account in <Link to="/accounts">Accounts</Link>.
            </Empty>
          ) : dayTransactions.length === 0 ? (
            <Empty>No transactions on this day.</Empty>
          ) : (
            <ul className="transaction-list">
              {dayTransactions.map((transaction) => (
                <li key={transaction.id} className={transaction.id === selected?.id ? 'selected' : ''}>
                  <button
                    type="button"
                    className="transaction-row"
                    onClick={() => {
                      setSelectedId(transaction.id);
                      editors.editTransaction(transaction);
                    }}
                    onFocus={() => setSelectedId(transaction.id)}
                  >
                    <span className="transaction-main">
                      <span className="transaction-title">{transactionTitle(transaction)}</span>
                      <span className="transaction-sub">
                        {transactionAccounts(transaction, accountMap)} · {transactionCategory(transaction, categoryMap)}
                      </span>
                    </span>
                    {transaction.kind === 'transfer' ? (
                      <Amount value={transferAmount(transaction)} money={money} muted />
                    ) : (
                      <Amount value={transaction.net_amount} money={money} />
                    )}
                  </button>
                  <RowMenu
                    actions={[
                      { label: 'Edit', onSelect: () => editors.editTransaction(transaction), shortcut: 'e' },
                      { label: 'Delete', onSelect: () => void deleteTransaction(transaction), danger: true, shortcut: 'd' },
                    ]}
                  />
                </li>
              ))}
            </ul>
          )}
        </section>

        <PeriodPanel summary={summary ?? null} budgets={budgets ?? null} money={money} hasPeriod={period !== null} />
      </div>

      <button type="button" className="fab" onClick={() => newTransaction()} aria-label="New transaction">
        +
      </button>

      {dialog === 'goto' ? <GoToDialog day={day} onClose={() => setDialog(null)} onGo={selectDay} /> : null}
      {dialog === 'period' ? (
        <PeriodForm
          open
          start={day}
          onClose={() => setDialog(null)}
          onSaved={(created) => setPeriodId(created.id)}
        />
      ) : null}
    </div>
  );
}

function PeriodTitle({
  period,
  covering,
  onCycle,
  onStart,
}: {
  period: Period | null;
  covering: Period[];
  onCycle: (step: number) => void;
  onStart: () => void;
}) {
  if (!period) {
    return (
      <div className="period-title">
        <span>
          <strong>No period</strong> covers this day
        </span>
        <button type="button" className="button small" onClick={onStart}>
          Start one
        </button>
      </div>
    );
  }
  const index = [...covering].reverse().findIndex((p) => p.id === period.id) + 1;
  return (
    <div className="period-title">
      {covering.length > 1 ? (
        <button type="button" className="icon-button" onClick={() => onCycle(-1)} aria-label="Previous period">
          ‹
        </button>
      ) : null}
      <span>
        <strong>{period.name}</strong> <span className="muted">{periodRange(period)}</span>
        {covering.length > 1 ? (
          <span className="muted">
            {' '}
            [{index}/{covering.length}]
          </span>
        ) : null}
      </span>
      {covering.length > 1 ? (
        <button type="button" className="icon-button" onClick={() => onCycle(1)} aria-label="Next period">
          ›
        </button>
      ) : null}
    </div>
  );
}

function PeriodPanel({
  summary,
  budgets,
  money,
  hasPeriod,
}: {
  summary: PeriodSummary | null;
  budgets: BudgetReport | null;
  money: MoneyFormat;
  hasPeriod: boolean;
}) {
  if (!hasPeriod || !summary) return null;
  const lines = new Map((budgets?.lines ?? []).map((line) => [line.category.id, line]));
  const rows = summary.categories.filter((item) => item.total || lines.has(item.category.id));
  return (
    <section className="card" aria-label="Period categories">
      <div className="card-header">
        <h2>{summary.period.name}</h2>
      </div>
      {rows.length === 0 && !summary.uncategorized ? (
        <Empty>Nothing spent or earned in this period yet.</Empty>
      ) : (
        <table className="table compact">
          <thead>
            <tr>
              <th>Category</th>
              <th className="num">Actual</th>
              <th className="num">Budget</th>
              <th className="num">Left</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => {
              const line = lines.get(item.category.id);
              return (
                <tr key={item.category.id} className={item.category.parent_id !== null ? 'child' : ''}>
                  <td>{item.category.name}</td>
                  <td className="num">
                    <Amount value={item.total} money={money} />
                  </td>
                  <td className="num">{line ? money.amount(line.budget.amount) : ''}</td>
                  <td className="num">{line ? <Amount value={line.remaining} money={money} /> : ''}</td>
                </tr>
              );
            })}
            {summary.uncategorized ? (
              <tr>
                <td>
                  <em>Uncategorized</em>
                </td>
                <td className="num">
                  <Amount value={summary.uncategorized} money={money} />
                </td>
                <td />
                <td />
              </tr>
            ) : null}
          </tbody>
          {budgets && budgets.lines.length ? (
            <tfoot>
              <tr>
                <th>Budgeted total</th>
                <td className="num">
                  <Amount value={budgets.total_actual} money={money} bold />
                </td>
                <td className="num bold">{money.amount(budgets.total_budget)}</td>
                <td className="num">
                  <Amount value={budgets.total_remaining} money={money} bold />
                </td>
              </tr>
            </tfoot>
          ) : null}
        </table>
      )}
    </section>
  );
}

function GoToDialog({ day, onClose, onGo }: { day: Day; onClose: () => void; onGo: (day: Day) => void }) {
  const [text, setText] = useState(day);
  const today = todayDay();
  return (
    <FormDialog
      open
      onClose={onClose}
      title="Go to date"
      saveLabel="Go"
      onSubmit={() => onGo(parseDate(text, today))}
      help="2025-02-03, 3/2/2025, 3/2, 3, today, +7, -30"
    >
      <DateField label="Date" value={text} onChange={setText} today={today} autoFocus />
    </FormDialog>
  );
}
