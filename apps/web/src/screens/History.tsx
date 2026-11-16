import { useMemo, useState, type ReactNode } from 'react';
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
  type TooltipValueType,
} from 'recharts';
import { useAccounts, useCategories, useHistory, useMoney, usePeriods } from '../api/queries';
import type { Account } from '../api/types';
import { Amount, Empty, Loading } from '../components/ui';
import { todayDay } from '../lib/dates';
import { byId, categoryLabel } from '../lib/format';
import {
  accountKey,
  balanceRows,
  cashFlowRows,
  categoryKey,
  categoryRows,
  change,
  chartedAccounts,
  isDebt,
  isSaving,
  netWorthRows,
  rankedCategories,
  spendingByCategory,
  SPANS,
  sum,
  type HistoryBy,
  type HistoryRow,
} from '../lib/history';
import type { MoneyFormat } from '../lib/money';
import { CHART_COLORS } from '../lib/report';
import { useHotkeys } from '../lib/useHotkeys';

const INCOME = '#0f7b63';
const EXPENSES = '#c4302b';
const NET = '#3b6fd8';
const TOP_CATEGORIES = 5;

interface Series {
  key: string;
  name: string;
  color: string;
  kind: 'bar' | 'line' | 'area';
  dashed?: boolean;
}

function ChartTooltip({
  active,
  payload,
  label,
  money,
}: Pick<TooltipContentProps<TooltipValueType, string>, 'active' | 'payload' | 'label'> & { money: MoneyFormat }) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload as HistoryRow | undefined;
  return (
    <div className="chart-tooltip">
      <strong>
        {label}
        {row?.partial ? <span className="muted"> (so far)</span> : null}
      </strong>
      {payload.map((entry) => (
        <span key={String(entry.dataKey)} className="chart-tooltip-row">
          <span className="report-swatch" style={{ background: entry.color }} aria-hidden="true" />
          <span className="chart-tooltip-name">{entry.name}</span>
          {money.amount(Number(entry.value))}
        </span>
      ))}
    </div>
  );
}

function Chart({ rows, series, money }: { rows: readonly HistoryRow[]; series: readonly Series[]; money: MoneyFormat }) {
  const tick = (value: number) => money.compact(value).replace(/^\+/, '');
  return (
    <div className="history-chart">
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={rows as HistoryRow[]} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="label" tickLine={false} minTickGap={12} />
          <YAxis tickFormatter={tick} width={52} tickLine={false} axisLine={false} />
          <ReferenceLine y={0} className="history-zero" />
          <Tooltip
            content={({ active, payload, label }) => (
              <ChartTooltip active={active} payload={payload} label={label} money={money} />
            )}
            cursor={{ fillOpacity: 0.08 }}
          />
          <Legend iconType="circle" iconSize={9} />
          {series.map((s) =>
            s.kind === 'bar' ? (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.name}
                fill={s.color}
                radius={[3, 3, 0, 0]}
                maxBarSize={28}
                isAnimationActive={false}
              />
            ) : s.kind === 'area' ? (
              <Area
                key={s.key}
                dataKey={s.key}
                name={s.name}
                stroke={s.color}
                fill={s.color}
                fillOpacity={0.15}
                strokeWidth={2}
                type="linear"
                isAnimationActive={false}
              />
            ) : (
              <Line
                key={s.key}
                dataKey={s.key}
                name={s.name}
                stroke={s.color}
                strokeWidth={2}
                strokeDasharray={s.dashed ? '5 4' : undefined}
                dot={rows.length <= 24 ? { r: 2.5 } : false}
                type="linear"
                isAnimationActive={false}
              />
            ),
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

function ChartCard({ title, summary, children }: { title: string; summary?: ReactNode; children: ReactNode }) {
  return (
    <section className="card history-card" aria-label={title}>
      <div className="card-header">
        <h2>{title}</h2>
      </div>
      {summary ? <dl className="history-summary">{summary}</dl> : null}
      {children}
    </section>
  );
}

function Figure({
  label,
  value,
  money,
  plus = false,
  plain = false,
}: {
  label: string;
  value: number;
  money: MoneyFormat;
  plus?: boolean;
  /** Without the colour of its sign, for amounts owed. */
  plain?: boolean;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {plain ? (
          <span className="amount bold">{money.amount(value, { plus })}</span>
        ) : (
          <Amount value={value} money={money} plus={plus} bold />
        )}
      </dd>
    </div>
  );
}

function accountSeries(accounts: readonly Account[], totalName: string): Series[] {
  return [
    ...accounts.map(
      (a, index): Series => ({
        key: accountKey(a.id),
        name: a.name,
        color: CHART_COLORS[index % CHART_COLORS.length]!,
        kind: 'line',
      }),
    ),
    ...(accounts.length > 1 ? [{ key: 'total', name: totalName, color: 'currentColor', kind: 'line' as const, dashed: true }] : []),
  ];
}

/**
 * Net worth, income against expenses, spending by category, debts and
 * savings over the last months or periods, a few at a time.
 */
export function History() {
  const money = useMoney();
  const today = todayDay();
  const [by, setBy] = useState<HistoryBy>('month');
  const [span, setSpan] = useState<number>(12);
  const [offset, setOffset] = useState(0);
  const [picked, setPicked] = useState<ReadonlySet<number | null> | null>(null);
  const history = useHistory(by, span, offset, today);
  const periods = usePeriods();
  const accounts = useAccounts(true);
  const categories = useCategories();

  const points = useMemo(() => history.data ?? [], [history.data]);
  const periodMap = useMemo(() => byId(periods.data), [periods.data]);
  const categoryMap = useMemo(() => byId(categories.data), [categories.data]);
  const parents = useMemo(() => new Map((categories.data ?? []).map((c) => [c.id, c.parent_id])), [categories.data]);

  const started = (periods.data ?? []).filter((p) => p.start <= today).length;
  const first = points[0];
  const earlier =
    by === 'period' ? offset + span < started : first !== undefined && (first.balances.length > 0 || first.flows.length > 0);
  const step = (delta: number) => {
    if (delta < 0 && earlier) setOffset(offset + span);
    if (delta > 0 && offset > 0) setOffset(Math.max(0, offset - span));
  };
  useHotkeys({ ArrowLeft: () => step(-1), ArrowRight: () => step(1) });

  const worth = useMemo(() => netWorthRows(points, periodMap), [points, periodMap]);
  const flows = useMemo(() => cashFlowRows(points, periodMap), [points, periodMap]);
  const spending = useMemo(() => spendingByCategory(points, parents), [points, parents]);
  const ranked = useMemo(() => rankedCategories(spending), [spending]);
  const chosen = picked ? ranked.filter((id) => picked.has(id)) : ranked.slice(0, TOP_CATEGORIES);
  const chosenSet = new Set(chosen);
  const byCategory = categoryRows(points, periodMap, spending, chosen);
  const debtAccounts = useMemo(() => chartedAccounts(points, accounts.data ?? [], isDebt), [points, accounts.data]);
  const savingAccounts = useMemo(() => chartedAccounts(points, accounts.data ?? [], isSaving), [points, accounts.data]);
  const debts = useMemo(() => balanceRows(points, periodMap, debtAccounts, true), [points, periodMap, debtAccounts]);
  const savings = useMemo(() => balanceRows(points, periodMap, savingAccounts), [points, periodMap, savingAccounts]);

  const nameOf = (id: number | null) => (id === null ? 'Uncategorized' : categoryLabel(id, categoryMap));
  const colorOf = (id: number | null) => CHART_COLORS[ranked.indexOf(id) % CHART_COLORS.length]!;
  const toggle = (id: number | null) => {
    const next = new Set(chosenSet);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setPicked(next);
  };
  const last = worth[worth.length - 1];
  const unit = by === 'month' ? 'month' : 'period';
  const rangeText = points.length ? `${worth[0]!.label} – ${last!.label}` : '';

  return (
    <>
      <section className="card report-filters history-controls" aria-label="History range">
        <div className="report-range-bar">
          <div className="segmented" role="tablist" aria-label="Group by">
            {(['month', 'period'] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={by === value}
                className={by === value ? 'active' : ''}
                onClick={() => {
                  setBy(value);
                  setOffset(0);
                }}
              >
                {value === 'month' ? 'Months' : 'Periods'}
              </button>
            ))}
          </div>
          <label className="history-span">
            <span className="muted small">Show</span>
            <select
              aria-label="Span"
              value={span}
              onChange={(e) => {
                setSpan(Number(e.target.value));
                setOffset(0);
              }}
            >
              {SPANS.map((value) => (
                <option key={value} value={value}>
                  {value} {unit}s
                </option>
              ))}
            </select>
          </label>
          <div className="period-picker history-step">
            <button
              type="button"
              className="icon-button"
              onClick={() => step(-1)}
              disabled={!earlier}
              aria-label={`Earlier ${unit}s`}
            >
              ‹
            </button>
            <span className="history-range">{rangeText}</span>
            <button
              type="button"
              className="icon-button"
              onClick={() => step(1)}
              disabled={offset === 0}
              aria-label={`Later ${unit}s`}
            >
              ›
            </button>
          </div>
        </div>
        {last?.partial ? <p className="muted small">The last {unit} counts up to today.</p> : null}
      </section>

      {history.isLoading ? (
        <Loading />
      ) : history.isError ? (
        <Empty>The history could not be loaded.</Empty>
      ) : !points.length ? (
        <Empty>
          {by === 'period'
            ? 'There are no periods yet: create one in Periods, or show months.'
            : 'Nothing to show yet.'}
        </Empty>
      ) : (
        <div className="history-grid">
          <ChartCard
            title="Net worth"
            summary={
              <>
                <Figure label="Now" value={last!.net as number} money={money} />
                <Figure label="Change" value={change(worth, 'net')} money={money} plus />
              </>
            }
          >
            <Chart
              rows={worth}
              money={money}
              series={[
                { key: 'net', name: 'Net worth', color: INCOME, kind: 'area' },
                { key: 'assets', name: 'Assets', color: NET, kind: 'line' },
                { key: 'debts', name: 'Debts', color: EXPENSES, kind: 'line' },
              ]}
            />
          </ChartCard>

          <ChartCard
            title="Income and expenses"
            summary={
              <>
                <Figure label="Income" value={sum(flows, 'income')} money={money} />
                <Figure label="Expenses" value={-sum(flows, 'expenses')} money={money} />
                <Figure label="Left over" value={sum(flows, 'net')} money={money} plus />
              </>
            }
          >
            <Chart
              rows={flows}
              money={money}
              series={[
                { key: 'income', name: 'Income', color: INCOME, kind: 'bar' },
                { key: 'expenses', name: 'Expenses', color: EXPENSES, kind: 'bar' },
                { key: 'net', name: 'Left over', color: NET, kind: 'line' },
              ]}
            />
          </ChartCard>

          <ChartCard title="Spending by category">
            {ranked.length ? (
              <>
                <Chart
                  rows={byCategory}
                  money={money}
                  series={chosen.map((id) => ({ key: categoryKey(id), name: nameOf(id), color: colorOf(id), kind: 'line' }))}
                />
                <ul className="report-legend history-categories" aria-label="Categories">
                  {ranked.map((id) => (
                    <li key={categoryKey(id)}>
                      <label>
                        <input type="checkbox" checked={chosenSet.has(id)} onChange={() => toggle(id)} />
                        <span className="report-swatch" style={{ background: colorOf(id) }} aria-hidden="true" />
                        <span className="report-legend-name">{nameOf(id)}</span>
                      </label>
                      <Amount value={spending.reduce((total, point) => total + (point.get(id) ?? 0), 0)} money={money} />
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <Empty>No income or expenses in these {unit}s.</Empty>
            )}
          </ChartCard>

          <ChartCard
            title="Debts"
            summary={
              debtAccounts.length ? (
                <>
                  <Figure label="Owed now" value={debts[debts.length - 1]!.total as number} money={money} plain />
                  {change(debts, 'total') <= 0 ? (
                    <Figure label="Paid off" value={-change(debts, 'total')} money={money} plain />
                  ) : (
                    <Figure label="More owed" value={change(debts, 'total')} money={money} plain />
                  )}
                </>
              ) : undefined
            }
          >
            {debtAccounts.length ? (
              <Chart rows={debts} money={money} series={accountSeries(debtAccounts, 'All debts')} />
            ) : (
              <Empty>No debts in these {unit}s.</Empty>
            )}
          </ChartCard>

          <ChartCard
            title="Savings"
            summary={
              savingAccounts.length ? (
                <>
                  <Figure label="Now" value={savings[savings.length - 1]!.total as number} money={money} />
                  <Figure label="Change" value={change(savings, 'total')} money={money} plus />
                </>
              ) : undefined
            }
          >
            {savingAccounts.length ? (
              <>
                <p className="muted small history-note">Savings accounts and investments at market value.</p>
                <Chart rows={savings} money={money} series={accountSeries(savingAccounts, 'All savings')} />
              </>
            ) : (
              <Empty>No savings or investment accounts with money in these {unit}s.</Empty>
            )}
          </ChartCard>
        </div>
      )}
    </>
  );
}
