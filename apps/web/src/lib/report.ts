/** Category reports: the external splits of some categories over a stretch of days. */

import type { ExternalSplit, Transaction } from '../api/types';

export interface ReportSplit {
  /** Unique within a report: the transaction id and the split's position. */
  key: string;
  transaction: Transaction;
  split: ExternalSplit;
}

export interface CategoryTotal {
  categoryId: number;
  total: number;
}

export interface PieSlice extends CategoryTotal {
  /** Share of the chart, from 0 to 1. */
  fraction: number;
  /** SVG path of the slice in a circle of radius 1 centred on the origin. */
  path: string;
}

/** The external splits of `transactions` booked exactly in one of `categoryIds`, in transaction order. */
export function reportSplits(transactions: readonly Transaction[], categoryIds: ReadonlySet<number>): ReportSplit[] {
  return transactions.flatMap((transaction) =>
    transaction.splits.flatMap((split, index) =>
      split.type === 'external' && split.category_id != null && categoryIds.has(split.category_id)
        ? [{ key: `${transaction.id}:${index}`, transaction, split }]
        : [],
    ),
  );
}

/** The total of each category, in the order of `categoryIds`, including categories with no splits. */
export function categoryTotals(splits: readonly ReportSplit[], categoryIds: readonly number[]): CategoryTotal[] {
  const totals = new Map(categoryIds.map((id) => [id, 0]));
  for (const { split } of splits) {
    const id = split.category_id;
    if (id != null && totals.has(id)) totals.set(id, totals.get(id)! + split.amount);
  }
  return categoryIds.map((categoryId) => ({ categoryId, total: totals.get(categoryId)! }));
}

const round = (value: number) => Number(value.toFixed(6));

function point(angle: number): string {
  // Clockwise from twelve o'clock.
  return `${round(Math.sin(angle))} ${round(-Math.cos(angle))}`;
}

/**
 * Slices sized by the size of each total, whatever its sign (expenses are
 * negative); categories totalling zero have no slice.
 */
export function pieSlices(totals: readonly CategoryTotal[]): PieSlice[] {
  const sized = totals.filter((t) => t.total !== 0);
  const sum = sized.reduce((acc, t) => acc + Math.abs(t.total), 0);
  let start = 0;
  return sized.map((t) => {
    const fraction = Math.abs(t.total) / sum;
    const end = start + fraction * 2 * Math.PI;
    const path =
      sized.length === 1
        ? 'M 0 -1 A 1 1 0 1 1 0 1 A 1 1 0 1 1 0 -1 Z'
        : `M 0 0 L ${point(start)} A 1 1 0 ${fraction > 0.5 ? 1 : 0} 1 ${point(end)} Z`;
    start = end;
    return { ...t, fraction, path };
  });
}
