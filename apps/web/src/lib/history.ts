/**
 * History charts: rows for Recharts built from the months or periods returned
 * by `/reports/history`, one row per month or period, oldest first.
 */

import type { Account, HistoryPoint, Period } from '../api/types';
import { monthName, parts } from './dates';
import type { ById } from './format';

export type HistoryBy = 'month' | 'period';

/** How many months or periods a chart can span. */
export const SPANS = [6, 12, 24, 60] as const;

/** A chart row: the label of its month or period and one number per series. */
export interface HistoryRow {
  label: string;
  /** The month or period is still running: it counts up to today. */
  partial: boolean;
  [series: string]: number | string | boolean;
}

/** Key of a category's series; `null` is the splits without a category. */
export const categoryKey = (id: number | null) => (id === null ? 'uncategorized' : `c${id}`);
export const accountKey = (id: number) => `a${id}`;

/** `Mar 2026` for a month, the period's name for a period. */
export function pointLabel(point: HistoryPoint, periods: ById<Period>): string {
  if (point.period_id !== null) return periods.get(point.period_id)?.name ?? point.start;
  const { year, month } = parts(point.start);
  return `${monthName(month).slice(0, 3)} ${year}`;
}

function rows(points: readonly HistoryPoint[], periods: ById<Period>, values: (p: HistoryPoint) => Record<string, number>) {
  return points.map((point): HistoryRow => ({ label: pointLabel(point, periods), partial: point.partial, ...values(point) }));
}

/** Net worth, assets and debts (what is owed, as a positive amount). */
export function netWorthRows(points: readonly HistoryPoint[], periods: ById<Period>): HistoryRow[] {
  return rows(points, periods, (p) => ({ net: p.net_worth, assets: p.assets, debts: -p.liabilities }));
}

/** Income, expenses (as a positive amount) and what is left of the income. */
export function cashFlowRows(points: readonly HistoryPoint[], periods: ById<Period>): HistoryRow[] {
  return rows(points, periods, (p) => ({ income: p.income, expenses: -p.expenses, net: p.income + p.expenses }));
}

/**
 * The spending of each top-level category in every point, its subcategories
 * included, positive for money spent (an income category shows below zero).
 * `parents` maps a category to its parent.
 */
export function spendingByCategory(
  points: readonly HistoryPoint[],
  parents: ReadonlyMap<number, number | null>,
): Map<number | null, number>[] {
  return points.map((point) => {
    const totals = new Map<number | null, number>();
    for (const { category_id, amount } of point.flows) {
      const id = category_id === null ? null : (parents.get(category_id) ?? category_id);
      totals.set(id, (totals.get(id) ?? 0) - amount);
    }
    return totals;
  });
}

/** The categories with spending, the biggest total spending first. */
export function rankedCategories(spending: readonly Map<number | null, number>[]): (number | null)[] {
  const totals = new Map<number | null, number>();
  for (const point of spending) for (const [id, amount] of point) totals.set(id, (totals.get(id) ?? 0) + amount);
  return [...totals].sort((a, b) => b[1] - a[1]).map(([id]) => id);
}

export function categoryRows(
  points: readonly HistoryPoint[],
  periods: ById<Period>,
  spending: readonly Map<number | null, number>[],
  chosen: readonly (number | null)[],
): HistoryRow[] {
  return points.map((point, index) => ({
    label: pointLabel(point, periods),
    partial: point.partial,
    ...Object.fromEntries(chosen.map((id) => [categoryKey(id), spending[index]?.get(id) ?? 0])),
  }));
}

/** Liabilities: what is owed. */
export const isDebt = (account: Account) => account.account_class === 'liability';
/** Savings: savings accounts and investments, at market value. */
export const isSaving = (account: Account) => account.type === 'savings' || account.type === 'investment';

/** The accounts matching `filter` with a balance in some point, in display order. */
export function chartedAccounts(
  points: readonly HistoryPoint[],
  accounts: readonly Account[],
  filter: (account: Account) => boolean,
): Account[] {
  const seen = new Set(points.flatMap((p) => p.balances.map((b) => b.account_id)));
  return accounts
    .filter((a) => seen.has(a.id) && filter(a))
    .sort((a, b) => a.position - b.position || a.id - b.id);
}

/**
 * The value of each account in every point and their `total`, as owed for
 * debts (a positive amount going down as it is paid off).
 */
export function balanceRows(
  points: readonly HistoryPoint[],
  periods: ById<Period>,
  accounts: readonly Account[],
  owed = false,
): HistoryRow[] {
  const sign = owed ? -1 : 1;
  return rows(points, periods, (point) => {
    const values = new Map(point.balances.map((b) => [b.account_id, sign * b.value]));
    const series = Object.fromEntries(accounts.map((a) => [accountKey(a.id), values.get(a.id) ?? 0]));
    return { ...series, total: accounts.reduce((sum, a) => sum + (values.get(a.id) ?? 0), 0) };
  });
}

/** The change of `key` from the first row to the last. */
export function change(rows: readonly HistoryRow[], key: string): number {
  const first = rows[0]?.[key];
  const last = rows[rows.length - 1]?.[key];
  return typeof first === 'number' && typeof last === 'number' ? last - first : 0;
}

/** The sum of `key` over the rows. */
export function sum(rows: readonly HistoryRow[], key: string): number {
  return rows.reduce((total, row) => total + (typeof row[key] === 'number' ? row[key] : 0), 0);
}
