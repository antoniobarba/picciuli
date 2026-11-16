import { describe, expect, it } from 'vitest';
import type { Transaction } from '../api/types';
import { categoryTotals, pieSlices, reportSplits } from './report';

const transaction = (id: number, splits: Transaction['splits']): Transaction => ({
  id,
  date: '2026-03-10',
  description: null,
  notes: null,
  splits,
  kind: 'expense',
  net_amount: 0,
});

const transactions = [
  transaction(1, [
    { type: 'account', account_id: 1, amount: -3000 },
    { type: 'external', amount: -2000, category_id: 2 },
    { type: 'external', amount: -1000, category_id: 3 },
  ]),
  transaction(2, [
    { type: 'account', account_id: 1, amount: -500 },
    { type: 'external', amount: -500, category_id: 2 },
  ]),
  transaction(3, [
    { type: 'account', account_id: 1, amount: -700 },
    { type: 'external', amount: -700, category_id: null },
  ]),
];

describe('reportSplits', () => {
  it('keeps only the external splits in the chosen categories', () => {
    const splits = reportSplits(transactions, new Set([2]));
    expect(splits.map((s) => s.key)).toEqual(['1:1', '2:1']);
    expect(splits.map((s) => s.split.amount)).toEqual([-2000, -500]);
  });
});

describe('categoryTotals', () => {
  it('sums each category in the given order, zero when it has no splits', () => {
    const splits = reportSplits(transactions, new Set([2, 3, 4]));
    expect(categoryTotals(splits, [3, 2, 4])).toEqual([
      { categoryId: 3, total: -1000 },
      { categoryId: 2, total: -2500 },
      { categoryId: 4, total: 0 },
    ]);
  });
});

describe('pieSlices', () => {
  it('sizes slices by the size of each total and skips zero totals', () => {
    const slices = pieSlices([
      { categoryId: 1, total: -3000 },
      { categoryId: 2, total: 0 },
      { categoryId: 3, total: 1000 },
    ]);
    expect(slices.map((s) => [s.categoryId, s.fraction])).toEqual([
      [1, 0.75],
      [3, 0.25],
    ]);
    // Three quarters clockwise from twelve o'clock ends at nine o'clock, with the large arc.
    expect(slices[0]!.path).toBe('M 0 0 L 0 -1 A 1 1 0 1 1 -1 0 Z');
    expect(slices[1]!.path).toBe('M 0 0 L -1 0 A 1 1 0 0 1 0 -1 Z');
  });

  it('draws a single category as a full circle', () => {
    const [slice] = pieSlices([{ categoryId: 1, total: -10 }]);
    expect(slice!.fraction).toBe(1);
    expect(slice!.path).not.toContain('L');
  });
});
