import { describe, expect, it } from 'vitest';
import type { Account, HistoryPoint, Period } from '../api/types';
import {
  balanceRows,
  cashFlowRows,
  categoryRows,
  change,
  chartedAccounts,
  isDebt,
  isSaving,
  netWorthRows,
  pointLabel,
  rankedCategories,
  spendingByCategory,
  sum,
} from './history';

const point = (start: string, extra: Partial<HistoryPoint> = {}): HistoryPoint => ({
  start,
  end: start,
  period_id: null,
  partial: false,
  income: 0,
  expenses: 0,
  flows: [],
  balances: [],
  assets: 0,
  liabilities: 0,
  net_worth: 0,
  ...extra,
});

const account = (id: number, type: Account['type'], position = id): Account => ({
  id,
  name: `A${id}`,
  type,
  account_class: ['credit_card', 'loan', 'mortgage', 'other_liability'].includes(type) ? 'liability' : 'asset',
  opening_balance: 0,
  opening_date: null,
  notes: null,
  position,
  closed_on: null,
  is_closed: false,
  debt_terms: null,
});

const periods = new Map<number, Period>([[7, { id: 7, name: 'Payday March', start: '2026-03-27', end: null }]]);

describe('history', () => {
  const points = [
    point('2026-01-01', {
      income: 2000,
      expenses: -500,
      assets: 9000,
      liabilities: -4000,
      net_worth: 5000,
      flows: [
        { category_id: 2, amount: -300 },
        { category_id: 3, amount: -100 },
        { category_id: 1, amount: -50 },
        { category_id: 4, amount: 2000 },
        { category_id: null, amount: -50 },
      ],
      balances: [
        { account_id: 1, balance: 3000, value: 3000 },
        { account_id: 2, balance: 6000, value: 6000 },
        { account_id: 3, balance: -4000, value: -4000 },
      ],
    }),
    point('2026-02-01', {
      partial: true,
      income: 2100,
      expenses: -700,
      assets: 9800,
      liabilities: -3500,
      net_worth: 6300,
      flows: [{ category_id: 3, amount: -700 }],
      balances: [
        { account_id: 2, balance: 6000, value: 6800 },
        { account_id: 3, balance: -3500, value: -3500 },
      ],
    }),
  ];

  it('labels months and periods', () => {
    expect(pointLabel(points[0]!, periods)).toBe('Jan 2026');
    expect(pointLabel(point('2026-03-27', { period_id: 7 }), periods)).toBe('Payday March');
  });

  it('charts net worth with debts owed as positive amounts', () => {
    const rows = netWorthRows(points, periods);
    expect(rows[1]).toEqual({ label: 'Feb 2026', partial: true, net: 6300, assets: 9800, debts: 3500 });
    expect(change(rows, 'net')).toBe(1300);
  });

  it('charts income against expenses and what is left over', () => {
    const rows = cashFlowRows(points, periods);
    expect(rows.map((r) => [r.income, r.expenses, r.net])).toEqual([
      [2000, 500, 1500],
      [2100, 700, 1400],
    ]);
    expect(sum(rows, 'net')).toBe(2900);
  });

  it('rolls subcategories into their parent and ranks categories by spending', () => {
    // 2 and 3 are subcategories of 1; 4 is an income category.
    const parents = new Map<number, number | null>([
      [1, null],
      [2, 1],
      [3, 1],
      [4, null],
    ]);
    const spending = spendingByCategory(points, parents);
    expect([...spending[0]!]).toEqual([
      [1, 450],
      [4, -2000],
      [null, 50],
    ]);
    const ranked = rankedCategories(spending);
    expect(ranked).toEqual([1, null, 4]);
    expect(categoryRows(points, periods, spending, [1, null])).toEqual([
      { label: 'Jan 2026', partial: false, c1: 450, uncategorized: 50 },
      { label: 'Feb 2026', partial: true, c1: 700, uncategorized: 0 },
    ]);
  });

  it('charts debts going down and savings with investments at market value', () => {
    const accounts = [account(1, 'checking'), account(2, 'investment'), account(3, 'loan'), account(4, 'savings')];
    const debts = chartedAccounts(points, accounts, isDebt);
    const savings = chartedAccounts(points, accounts, isSaving);
    expect(debts.map((a) => a.id)).toEqual([3]);
    // The savings account never had money: nothing to chart.
    expect(savings.map((a) => a.id)).toEqual([2]);

    const owed = balanceRows(points, periods, debts, true);
    expect(owed.map((r) => [r.a3, r.total])).toEqual([
      [4000, 4000],
      [3500, 3500],
    ]);
    expect(change(owed, 'total')).toBe(-500);
    expect(balanceRows(points, periods, savings).map((r) => r.total)).toEqual([6000, 6800]);
  });
});
