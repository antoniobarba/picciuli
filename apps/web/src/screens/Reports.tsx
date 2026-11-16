import { useMemo, useState } from 'react';
import { useAccounts, useCategories, useMoney, usePeriods, useTransactions } from '../api/queries';
import type { Category } from '../api/types';
import { useEditors } from '../app/editors';
import { DateField } from '../components/DateField';
import { TransactionListControls, useTransactionList } from '../components/TransactionListControls';
import { Amount, Empty, Loading, PageHeader } from '../components/ui';
import { covers } from '../lib/calendar';
import { makeDay, parts, shortDate, todayDay, type Day } from '../lib/dates';
import { byId, categoryLabel, categoryTree, periodRange, transactionAccounts, transactionTitle } from '../lib/format';
import { parseDate } from '../lib/forms';
import { categoryTotals, pieSlices, reportSplits, type ReportSplit } from '../lib/report';

type RangeMode = 'period' | 'days';

const COLORS = ['#0f7b63', '#e07a2e', '#3b6fd8', '#c4302b', '#8e5bd0', '#d4a514', '#1fa3b5', '#d0569a', '#6b8e23', '#7a6a58'];

function tryParse(text: string, today: Day): Day | null {
  try {
    return parseDate(text, today);
  } catch {
    return null;
  }
}

function CategoryCheckbox({
  category,
  checked,
  onToggle,
}: {
  category: Category;
  checked: boolean;
  onToggle: (category: Category) => void;
}) {
  return (
    <label>
      <input type="checkbox" checked={checked} onChange={() => onToggle(category)} />
      {category.name}
    </label>
  );
}

/** The external splits of chosen categories over a period or a range of days, with a total per category. */
export function Reports() {
  const money = useMoney();
  const editors = useEditors();
  const today = todayDay();
  const periods = usePeriods();
  const categories = useCategories();
  const accounts = useAccounts(true);

  const [mode, setMode] = useState<RangeMode>('period');
  const [chosenPeriodId, setChosenPeriodId] = useState<number | null>(null);
  const [startText, setStartText] = useState(() => makeDay(parts(today).year, parts(today).month, 1));
  const [endText, setEndText] = useState(today);
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => new Set());

  const ordered = useMemo(
    () => [...(periods.data ?? [])].sort((a, b) => a.start.localeCompare(b.start) || a.id - b.id),
    [periods.data],
  );
  const period =
    ordered.find((p) => p.id === chosenPeriodId) ??
    [...ordered].reverse().find((p) => covers(p, today)) ??
    ordered[ordered.length - 1] ??
    null;
  const stepPeriod = (delta: number) => {
    if (!period) return;
    const next = ordered[ordered.findIndex((p) => p.id === period.id) + delta];
    if (next) setChosenPeriodId(next.id);
  };

  const tree = useMemo(() => categoryTree(categories.data ?? []), [categories.data]);
  const categoryMap = useMemo(() => byId(categories.data), [categories.data]);
  const accountMap = useMemo(() => byId(accounts.data), [accounts.data]);
  const chosen = useMemo(() => tree.filter((c) => selected.has(c.id)).map((c) => c.id), [tree, selected]);
  const chosenSet = useMemo(() => new Set(chosen), [chosen]);

  let range: { start: Day; end?: Day } | null = null;
  let rangeError: string | null = null;
  if (mode === 'period') {
    if (period) range = { start: period.start, ...(period.end ? { end: period.end } : {}) };
  } else {
    const start = tryParse(startText, today);
    const end = tryParse(endText, today);
    if (!start || !end) rangeError = 'Enter both the first and the last day.';
    else if (start > end) rangeError = 'The first day comes after the last day.';
    else range = { start, end };
  }

  const transactions = useTransactions({ ...range, newest_first: true }, range !== null && chosen.length > 0);
  const splits = useMemo(() => reportSplits(transactions.data ?? [], chosenSet), [transactions.data, chosenSet]);
  const scope = JSON.stringify([range, chosen]);
  const paged = useTransactionList(splits, scope, (item: ReportSplit) => item.transaction);
  const totals = useMemo(() => categoryTotals(paged.matches, chosen), [paged.matches, chosen]);
  const total = totals.reduce((sum, t) => sum + t.total, 0);
  const slices = pieSlices(totals);
  const colorOf = (categoryId: number) => COLORS[chosen.indexOf(categoryId) % COLORS.length]!;

  const toggle = (category: Category) => {
    const next = new Set(selected);
    const on = !next.has(category.id);
    const family = [category, ...(category.parent_id === null ? tree.filter((c) => c.parent_id === category.id) : [])];
    for (const c of family) {
      if (on) next.add(c.id);
      else next.delete(c.id);
    }
    setSelected(next);
  };

  return (
    <div className="page">
      <PageHeader title="Reports" />
      <section className="card report-filters" aria-label="Report filters">
        <div className="report-range">
          <div className="segmented" role="tablist" aria-label="Range">
            {(['period', 'days'] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={mode === value}
                className={mode === value ? 'active' : ''}
                onClick={() => setMode(value)}
              >
                {value === 'period' ? 'Period' : 'Days'}
              </button>
            ))}
          </div>
          {mode === 'period' ? (
            periods.isLoading ? (
              <Loading />
            ) : !period ? (
              <Empty>There are no periods yet: create one in Periods, or choose days.</Empty>
            ) : (
              <div className="period-picker">
                <button
                  type="button"
                  className="icon-button"
                  onClick={() => stepPeriod(-1)}
                  disabled={ordered[0]?.id === period.id}
                  aria-label="Previous period"
                >
                  ‹
                </button>
                <select aria-label="Period" value={period.id} onChange={(e) => setChosenPeriodId(Number(e.target.value))}>
                  {ordered.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({periodRange(p)})
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="icon-button"
                  onClick={() => stepPeriod(1)}
                  disabled={ordered[ordered.length - 1]?.id === period.id}
                  aria-label="Next period"
                >
                  ›
                </button>
              </div>
            )
          ) : (
            <div className="form-row report-days">
              <DateField label="From" value={startText} onChange={setStartText} today={today} />
              <DateField label="To" value={endText} onChange={setEndText} today={today} />
            </div>
          )}
          {rangeError ? (
            <p className="negative small" role="alert">
              {rangeError}
            </p>
          ) : null}
        </div>
        <fieldset className="report-categories">
          <legend>Categories</legend>
          <div className="toolbar report-category-actions">
            <button
              type="button"
              className="button small"
              onClick={() => setSelected(new Set(tree.map((c) => c.id)))}
              disabled={!tree.length}
            >
              All
            </button>
            <button type="button" className="button small" onClick={() => setSelected(new Set())} disabled={!selected.size}>
              None
            </button>
          </div>
          {categories.isLoading ? (
            <Loading />
          ) : !tree.length ? (
            <Empty>There are no categories yet: create them in Categories.</Empty>
          ) : (
            <ul className="report-category-list">
              {tree
                .filter((c) => c.parent_id === null)
                .map((parent) => (
                  <li key={parent.id}>
                    <CategoryCheckbox category={parent} checked={selected.has(parent.id)} onToggle={toggle} />
                    {tree.some((c) => c.parent_id === parent.id) ? (
                      <ul>
                        {tree
                          .filter((c) => c.parent_id === parent.id)
                          .map((child) => (
                            <li key={child.id}>
                              <CategoryCheckbox category={child} checked={selected.has(child.id)} onToggle={toggle} />
                            </li>
                          ))}
                      </ul>
                    ) : null}
                  </li>
                ))}
            </ul>
          )}
        </fieldset>
      </section>

      {!chosen.length ? (
        <Empty>Choose one or more categories to see their transactions.</Empty>
      ) : !range ? null : (
        <div className="report-results">
          <section className="card report-splits" aria-label="Transactions">
            <TransactionListControls list={paged} />
            <div className="item-transactions">
              {transactions.isLoading ? (
                <Loading />
              ) : paged.items.length === 0 ? (
                <Empty>{splits.length === 0 ? 'No transactions in these categories.' : 'No matching transactions.'}</Empty>
              ) : (
                <ul className="transaction-list" aria-label="Splits">
                  {paged.items.map(({ key, transaction, split }) => (
                    <li key={key}>
                      <button type="button" className="transaction-row" onClick={() => editors.editTransaction(transaction)}>
                        <span className="report-swatch" style={{ background: colorOf(split.category_id!) }} aria-hidden="true" />
                        <span className="transaction-main">
                          <span className="transaction-title">{transactionTitle(transaction)}</span>
                          <span className="transaction-sub">
                            {shortDate(transaction.date)} · {transactionAccounts(transaction, accountMap)} ·{' '}
                            {categoryLabel(split.category_id, categoryMap)}
                            {split.memo ? ` · ${split.memo}` : ''}
                          </span>
                        </span>
                        <Amount value={split.amount} money={money} />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="totals">
              <span>
                {paged.count} split{paged.count === 1 ? '' : 's'}
              </span>
              <span>
                Total <Amount value={total} money={money} bold />
              </span>
            </div>
          </section>

          <section className="card report-chart" aria-label="By category">
            <div className="card-header">
              <h2>By category</h2>
            </div>
            {slices.length ? (
              <svg className="pie" viewBox="-1.05 -1.05 2.1 2.1" role="img" aria-label="Total of each category">
                {slices.map((slice) => (
                  <path key={slice.categoryId} d={slice.path} fill={colorOf(slice.categoryId)}>
                    <title>
                      {categoryLabel(slice.categoryId, categoryMap)}: {money.amount(slice.total)} (
                      {Math.round(slice.fraction * 100)}%)
                    </title>
                  </path>
                ))}
              </svg>
            ) : (
              <Empty>Nothing to chart.</Empty>
            )}
            <ul className="report-legend" aria-label="Category totals">
              {totals.map((t) => {
                const slice = slices.find((s) => s.categoryId === t.categoryId);
                return (
                  <li key={t.categoryId}>
                    <span className="report-swatch" style={{ background: colorOf(t.categoryId) }} aria-hidden="true" />
                    <span className="report-legend-name">{categoryLabel(t.categoryId, categoryMap)}</span>
                    <span className="muted small">{slice ? `${Math.round(slice.fraction * 100)}%` : '—'}</span>
                    <Amount value={t.total} money={money} />
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}
