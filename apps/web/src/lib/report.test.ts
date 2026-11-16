import { describe, expect, it } from 'vitest';
import type { Transaction } from '../api/types';
import { accountBucket, bucketTotals, categoryBucket, pieSlices, reportSplits } from './report';

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
    const splits = reportSplits(transactions, new Set([categoryBucket(2)]));
    expect(splits.map((s) => s.key)).toEqual(['1:1', '2:1']);
    expect(splits.map((s) => s.amount)).toEqual([-2000, -500]);
  });

  describe('for some accounts', () => {
    // 1 checking, 2 credit card, 3 loan; 7 interest, 8 groceries.
    const flows = [
      // A loan payment: the interest is an expense, the principal moves to the loan.
      transaction(10, [
        { type: 'account', account_id: 1, amount: -1000 },
        { type: 'account', account_id: 3, amount: 900 },
        { type: 'external', amount: -100, category_id: 7 },
      ]),
      // Paying off the card from checking.
      transaction(11, [
        { type: 'account', account_id: 1, amount: -400 },
        { type: 'account', account_id: 2, amount: 400 },
      ]),
      // Groceries on the card.
      transaction(12, [
        { type: 'account', account_id: 2, amount: -250 },
        { type: 'external', amount: -250, category_id: 8 },
      ]),
      // Neither account: a loan fee paid from elsewhere.
      transaction(13, [
        { type: 'account', account_id: 4, amount: -30 },
        { type: 'external', amount: -30, category_id: 7 },
      ]),
    ];
    const all = new Set([categoryBucket(7), categoryBucket(8), accountBucket(2), accountBucket(3), accountBucket(4)]);

    it('counts transfers out of the set and drops moves inside it', () => {
      const splits = reportSplits(flows, all, new Set([1, 2]));
      expect(splits.map((s) => [s.key, s.bucket, s.amount])).toEqual([
        ['10:1', 'account:3', -900],
        ['10:2', 'category:7', -100],
        ['12:1', 'category:8', -250],
      ]);
      // The flows add up to the change in the set's balances.
      expect(splits.reduce((sum, s) => sum + s.amount, 0)).toBe(-1000 - 400 + 400 - 250);
    });

    it('treats transfers with other accounts as flows of a single account', () => {
      const splits = reportSplits(flows, all, new Set([1]));
      expect(splits.map((s) => [s.bucket, s.amount])).toEqual([
        ['account:3', -900],
        ['category:7', -100],
        ['account:2', -400],
      ]);
    });

    it('counts only the share of the reported accounts in a split expense', () => {
      // Dinner paid 60 from checking and 40 from the card.
      const dinner = transaction(14, [
        { type: 'account', account_id: 1, amount: -60 },
        { type: 'account', account_id: 2, amount: -40 },
        { type: 'external', amount: -70, category_id: 8 },
        { type: 'external', amount: -30, category_id: 7 },
      ]);
      expect(reportSplits([dinner], all, new Set([1])).map((s) => [s.bucket, s.amount])).toEqual([
        ['category:8', -42],
        ['category:7', -18],
      ]);
      expect(reportSplits([dinner], all, new Set([1, 2])).map((s) => s.amount)).toEqual([-70, -30]);
    });

    it('keeps income and its withheld expenses whole for the account receiving it', () => {
      // A salary of 1000 with 200 of tax withheld, paid into checking.
      const salary = transaction(15, [
        { type: 'account', account_id: 1, amount: 800 },
        { type: 'external', amount: 1000, category_id: 8 },
        { type: 'external', amount: -200, category_id: 7 },
      ]);
      expect(reportSplits([salary], all, new Set([1])).map((s) => s.amount)).toEqual([1000, -200]);
    });

    it('reports the whole portfolio without accounts', () => {
      expect(reportSplits(flows, all, new Set()).map((s) => s.bucket)).toEqual(['category:7', 'category:8', 'category:7']);
    });
  });
});

describe('bucketTotals', () => {
  it('sums each bucket in the given order, zero when it has no splits', () => {
    const buckets = [categoryBucket(3), categoryBucket(2), categoryBucket(4)];
    const splits = reportSplits(transactions, new Set(buckets));
    expect(bucketTotals(splits, buckets)).toEqual([
      { bucket: 'category:3', total: -1000 },
      { bucket: 'category:2', total: -2500 },
      { bucket: 'category:4', total: 0 },
    ]);
  });
});

describe('pieSlices', () => {
  it('sizes slices by the size of each total and skips zero totals', () => {
    const slices = pieSlices([
      { bucket: 'category:1', total: -3000 },
      { bucket: 'category:2', total: 0 },
      { bucket: 'account:3', total: 1000 },
    ]);
    expect(slices.map((s) => [s.bucket, s.fraction])).toEqual([
      ['category:1', 0.75],
      ['account:3', 0.25],
    ]);
    // Three quarters clockwise from twelve o'clock ends at nine o'clock, with the large arc.
    expect(slices[0]!.path).toBe('M 0 0 L 0 -1 A 1 1 0 1 1 -1 0 Z');
    expect(slices[1]!.path).toBe('M 0 0 L -1 0 A 1 1 0 0 1 0 -1 Z');
  });

  it('draws a single bucket as a full circle', () => {
    const [slice] = pieSlices([{ bucket: 'category:1', total: -10 }]);
    expect(slice!.fraction).toBe(1);
    expect(slice!.path).not.toContain('L');
  });
});
