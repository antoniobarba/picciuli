import { useMemo, useRef, useState, type PointerEvent } from 'react';
import { useSearchParams } from 'react-router';
import { useAccounts, useCategories, useMoney, usePeriods, useTransactions } from '../api/queries';
import { useEditors } from '../app/editors';
import { DateField } from '../components/DateField';
import { TransactionListControls, useTransactionList } from '../components/TransactionListControls';
import { Amount, Empty, Loading, PageHeader } from '../components/ui';
import { covers } from '../lib/calendar';
import { addDays, daysBetween, makeDay, parts, shortDate, todayDay, type Day } from '../lib/dates';
import {
  accountName,
  byId,
  categoryLabel,
  categoryTree,
  periodRange,
  transactionAccounts,
  transactionTitle,
} from '../lib/format';
import { parseDate } from '../lib/forms';
import {
  accountBucket,
  bucketTotals,
  categoryBucket,
  parseBucket,
  pieSlices,
  reportSplits,
  UNCATEGORIZED,
  type Bucket,
  type ReportSplit,
} from '../lib/report';
import { useHotkeys } from '../lib/useHotkeys';

type RangeMode = 'period' | 'days';

const COLORS = ['#0f7b63', '#e07a2e', '#3b6fd8', '#c4302b', '#8e5bd0', '#d4a514', '#1fa3b5', '#d0569a', '#6b8e23', '#7a6a58'];

function tryParse(text: string, today: Day): Day | null {
  try {
    return parseDate(text, today);
  } catch {
    return null;
  }
}

function Check({ label, checked, onToggle }: { label: string; checked: boolean; onToggle: () => void }) {
  return (
    <label>
      <input type="checkbox" checked={checked} onChange={onToggle} />
      {label}
    </label>
  );
}

function toggled<T>(set: ReadonlySet<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

function idParam(value: string | null): number | null {
  return value && /^\d+$/.test(value) ? Number(value) : null;
}

function idsParam(value: string | null): Set<number> {
  return new Set((value ?? '').split(',').map(idParam).filter((id) => id !== null));
}

/**
 * The cash flow of the whole portfolio or of chosen accounts, by category and
 * by transfers with the other accounts, over a period or a range of days.
 *
 * `?period=<id>&categories=<id>,<id>&uncategorized=1` opens it on a period with
 * categories (and the uncategorized splits) ticked.
 */
export function Reports() {
  const money = useMoney();
  const editors = useEditors();
  const today = todayDay();
  const [params] = useSearchParams();
  const periods = usePeriods();
  const categories = useCategories();
  const accounts = useAccounts(true);

  const [mode, setMode] = useState<RangeMode>('period');
  const [chosenPeriodId, setChosenPeriodId] = useState<number | null>(() => idParam(params.get('period')));
  const [startText, setStartText] = useState(() => makeDay(parts(today).year, parts(today).month, 1));
  const [endText, setEndText] = useState(today);
  const [selected, setSelected] = useState<ReadonlySet<number>>(() => idsParam(params.get('categories')));
  const [uncategorized, setUncategorized] = useState(() => params.get('uncategorized') === '1');
  const [selectedAccounts, setSelectedAccounts] = useState<ReadonlySet<number>>(() => new Set());
  const [selectedTransfers, setSelectedTransfers] = useState<ReadonlySet<number>>(() => new Set());
  const [showFilters, setShowFilters] = useState(true);
  const [hover, setHover] = useState<{ bucket: Bucket; x: number; y: number } | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);

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
  const orderedAccounts = useMemo(
    () => [...(accounts.data ?? [])].sort((a, b) => a.position - b.position || a.id - b.id),
    [accounts.data],
  );
  const reported = useMemo(
    () => new Set(orderedAccounts.filter((a) => selectedAccounts.has(a.id)).map((a) => a.id)),
    [orderedAccounts, selectedAccounts],
  );
  // Only accounts outside the reported ones can receive or send transfers.
  const transferAccounts = useMemo(
    () => (reported.size ? orderedAccounts.filter((a) => !reported.has(a.id)) : []),
    [orderedAccounts, reported],
  );
  const chosen = useMemo(
    () => [
      ...tree.filter((c) => selected.has(c.id)).map((c) => categoryBucket(c.id)),
      ...(uncategorized ? [UNCATEGORIZED] : []),
      ...transferAccounts.filter((a) => selectedTransfers.has(a.id)).map((a) => accountBucket(a.id)),
    ],
    [tree, selected, uncategorized, transferAccounts, selectedTransfers],
  );
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

  // Moves to the previous or next period, or shifts the days by as many days as they span.
  const step = (delta: number) => {
    if (mode === 'period') {
      stepPeriod(delta);
    } else if (range?.end) {
      const shift = delta * (daysBetween(range.start, range.end) + 1);
      setStartText(addDays(range.start, shift));
      setEndText(addDays(range.end, shift));
    }
  };
  useHotkeys({ ArrowLeft: () => step(-1), ArrowRight: () => step(1) });

  const transactions = useTransactions({ ...range, newest_first: true }, range !== null && chosen.length > 0);
  const parents = useMemo(() => new Map(tree.map((c) => [c.id, c.parent_id])), [tree]);
  const splits = useMemo(
    () => reportSplits(transactions.data ?? [], chosenSet, reported, parents),
    [transactions.data, chosenSet, reported, parents],
  );
  const scope = JSON.stringify([range, chosen, [...reported]]);
  const paged = useTransactionList(splits, scope, (item: ReportSplit) => item.transaction);
  const totals = useMemo(() => bucketTotals(paged.matches, chosen), [paged.matches, chosen]);
  const total = totals.reduce((sum, t) => sum + t.total, 0);
  const slices = pieSlices(totals);
  const colorOf = (bucket: Bucket) => COLORS[chosen.indexOf(bucket) % COLORS.length]!;
  const labelOf = (bucket: Bucket) => {
    const { kind, id } = parseBucket(bucket);
    if (kind === 'uncategorized') return 'Uncategorized';
    return kind === 'category' ? categoryLabel(id, categoryMap) : `Transfers › ${accountName(id, accountMap)}`;
  };
  const hovered = hover ? slices.find((s) => s.bucket === hover.bucket) : undefined;
  const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;
  const transferCount = transferAccounts.filter((a) => selectedTransfers.has(a.id)).length;
  const filterSummary = [
    reported.size ? plural(reported.size, 'account', 'accounts') : 'Whole portfolio',
    plural(tree.filter((c) => selected.has(c.id)).length, 'category', 'categories'),
    ...(uncategorized ? ['uncategorized'] : []),
    ...(transferCount ? [plural(transferCount, 'transfer', 'transfers')] : []),
  ].join(' · ');

  // A category includes its subcategories, unless they are ticked to show apart.
  const toggle = (categoryId: number) => setSelected(toggled(selected, categoryId));

  const showTooltip = (bucket: Bucket) => (event: PointerEvent<SVGPathElement>) => {
    const box = chartRef.current?.getBoundingClientRect();
    if (box) setHover({ bucket, x: event.clientX - box.left, y: event.clientY - box.top });
  };
  const hideTooltip = (event: PointerEvent) => {
    // A tap keeps its tooltip until the next tap; a mouse hides it on leaving.
    if (event.pointerType === 'mouse') setHover(null);
  };

  return (
    <div className="page">
      <PageHeader title="Reports" />
      <section className="card report-filters" aria-label="Report filters">
        <div className="report-range-bar">
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
          <div className="report-filters-toggle">
            {showFilters ? null : <span className="muted small">{filterSummary}</span>}
            <button
              type="button"
              className="button small"
              aria-expanded={showFilters}
              aria-controls="report-filter-panel"
              onClick={() => setShowFilters(!showFilters)}
            >
              {showFilters ? 'Hide accounts and categories' : 'Show accounts and categories'}
            </button>
          </div>
          {rangeError ? (
            <p className="negative small report-range-error" role="alert">
              {rangeError}
            </p>
          ) : null}
        </div>
        {showFilters ? (
          <div className="report-filter-panel" id="report-filter-panel">
            <div className="report-range">
              <fieldset className="report-categories report-accounts">
                <legend>Accounts</legend>
                <div className="toolbar report-category-actions">
                  <button
                    type="button"
                    className="button small"
                    onClick={() => setSelectedAccounts(new Set())}
                    disabled={!reported.size}
                  >
                    Whole portfolio
                  </button>
                </div>
                {accounts.isLoading ? (
                  <Loading />
                ) : (
                  <>
                    <p className="muted small">
                      {reported.size
                        ? 'Money in and out of the ticked accounts; moves between them cancel out.'
                        : 'Tick accounts to see only their cash flow; with none ticked, the whole portfolio.'}
                    </p>
                    <ul className="report-category-list">
                      {orderedAccounts.map((account) => (
                        <li key={account.id}>
                          <Check
                            label={account.is_closed ? `${account.name} (closed)` : account.name}
                            checked={reported.has(account.id)}
                            onToggle={() => setSelectedAccounts(toggled(selectedAccounts, account.id))}
                          />
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </fieldset>
            </div>
            <div className="report-range">
              <fieldset className="report-categories">
                <legend>Categories</legend>
                <div className="toolbar report-category-actions">
                  <button
                    type="button"
                    className="button small"
                    onClick={() => {
                      setSelected(new Set(tree.filter((c) => c.parent_id === null).map((c) => c.id)));
                      setUncategorized(true);
                      setSelectedTransfers(new Set(transferAccounts.map((a) => a.id)));
                    }}
                    disabled={!tree.length && !transferAccounts.length}
                  >
                    All
                  </button>
                  <button
                    type="button"
                    className="button small"
                    onClick={() => {
                      setSelected(new Set());
                      setUncategorized(false);
                      setSelectedTransfers(new Set());
                    }}
                    disabled={!chosen.length}
                  >
                    None
                  </button>
                </div>
                {categories.isLoading ? (
                  <Loading />
                ) : !tree.length ? (
                  <Empty>There are no categories yet: create them in Categories.</Empty>
                ) : (
                  <>
                  <p className="muted small">
                    A category includes its subcategories; tick a subcategory too to show it apart.
                  </p>
                  <ul className="report-category-list">
                    {tree
                      .filter((c) => c.parent_id === null)
                      .map((parent) => (
                        <li key={parent.id}>
                          <Check label={parent.name} checked={selected.has(parent.id)} onToggle={() => toggle(parent.id)} />
                          {tree.some((c) => c.parent_id === parent.id) ? (
                            <ul>
                              {tree
                                .filter((c) => c.parent_id === parent.id)
                                .map((child) => (
                                  <li key={child.id}>
                                    <Check label={child.name} checked={selected.has(child.id)} onToggle={() => toggle(child.id)} />
                                  </li>
                                ))}
                            </ul>
                          ) : null}
                        </li>
                      ))}
                  </ul>
                  </>
                )}
                {categories.isLoading ? null : (
                  <label className="report-uncategorized">
                    <input type="checkbox" checked={uncategorized} onChange={() => setUncategorized(!uncategorized)} />
                    <em>Uncategorized</em>
                    <span className="muted small">not a category: splits without one</span>
                  </label>
                )}
              </fieldset>
              {transferAccounts.length ? (
                <fieldset className="report-categories">
                  <legend>Transfers with</legend>
                  <ul className="report-category-list">
                    {transferAccounts.map((account) => (
                      <li key={account.id}>
                        <Check
                          label={account.is_closed ? `${account.name} (closed)` : account.name}
                          checked={selectedTransfers.has(account.id)}
                          onToggle={() => setSelectedTransfers(toggled(selectedTransfers, account.id))}
                        />
                      </li>
                    ))}
                  </ul>
                </fieldset>
              ) : null}
            </div>
          </div>
        ) : null}
      </section>

      {!chosen.length ? (
        <Empty>
          {reported.size
            ? 'Choose one or more categories or transfers to see their transactions.'
            : 'Choose one or more categories to see their transactions.'}
        </Empty>
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
                  {paged.items.map(({ key, transaction, split, bucket, amount }) => (
                    <li key={key}>
                      <button type="button" className="transaction-row" onClick={() => editors.editTransaction(transaction)}>
                        <span className="report-swatch" style={{ background: colorOf(bucket) }} aria-hidden="true" />
                        <span className="transaction-main">
                          <span className="transaction-title">{transactionTitle(transaction)}</span>
                          <span className="transaction-sub">
                            {shortDate(transaction.date)} · {transactionAccounts(transaction, accountMap)} ·{' '}
                            {labelOf(bucket)}
                            {split.memo ? ` · ${split.memo}` : ''}
                          </span>
                        </span>
                        <Amount value={amount} money={money} />
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
              <div className="pie-wrap" ref={chartRef}>
                <svg
                  className="pie"
                  viewBox="-1.05 -1.05 2.1 2.1"
                  role="img"
                  aria-label="Total of each category"
                  onPointerLeave={hideTooltip}
                >
                  {slices.map((slice) => (
                    <path
                      key={slice.bucket}
                      d={slice.path}
                      fill={colorOf(slice.bucket)}
                      className={hovered?.bucket === slice.bucket ? 'hovered' : undefined}
                      onPointerEnter={showTooltip(slice.bucket)}
                      onPointerMove={showTooltip(slice.bucket)}
                      onPointerDown={showTooltip(slice.bucket)}
                    />
                  ))}
                </svg>
                {hover && hovered ? (
                  <div className="pie-tooltip" role="tooltip" style={{ left: hover.x, top: hover.y }}>
                    <strong>{labelOf(hovered.bucket)}</strong>
                    <span>
                      {money.amount(hovered.total)} ({Math.round(hovered.fraction * 100)}%)
                    </span>
                  </div>
                ) : null}
              </div>
            ) : (
              <Empty>Nothing to chart.</Empty>
            )}
            <ul className="report-legend" aria-label="Category totals">
              {totals.map((t) => {
                const slice = slices.find((s) => s.bucket === t.bucket);
                return (
                  <li key={t.bucket}>
                    <span className="report-swatch" style={{ background: colorOf(t.bucket) }} aria-hidden="true" />
                    <span className="report-legend-name">{labelOf(t.bucket)}</span>
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
