import { describe, expect, it } from 'vitest';
import type { Period, Transaction } from '../api/types';
import { choosePeriod, cyclePeriod, dayFlows, monthGrid, shiftMonth, visibleRange } from './calendar';
import { addDays, daysBetween, longDate, shortDate, weekday } from './dates';

const period = (id: number, start: string, end: string | null = null): Period => ({
  id,
  name: `P${id}`,
  start,
  end,
});

const transaction = (date: string, net: number, kind: Transaction['kind']): Transaction => ({
  id: Math.random(),
  date,
  description: null,
  notes: null,
  splits: [],
  kind,
  net_amount: net,
});

describe('dates', () => {
  it('does day arithmetic across months and years', () => {
    expect(addDays('2024-02-28', 1)).toBe('2024-02-29');
    expect(addDays('2025-01-01', -1)).toBe('2024-12-31');
    expect(daysBetween('2025-03-01', '2025-03-31')).toBe(30);
    expect(weekday('2025-02-03')).toBe(0);
    expect(shortDate('2025-02-03')).toBe('03 Feb 2025');
    expect(longDate('2025-02-03')).toBe('Monday 03 February 2025');
  });
});

describe('monthGrid', () => {
  it('shows six Monday-first weeks', () => {
    const grid = monthGrid(2025, 2);
    expect(grid).toHaveLength(6);
    expect(grid[0]![0]).toBe('2025-01-27');
    expect(grid[0]![5]).toBe('2025-02-01');
    expect(visibleRange(2025, 2)).toEqual(['2025-01-27', '2025-03-09']);
  });
});

describe('shiftMonth', () => {
  it('clamps the day', () => {
    expect(shiftMonth('2025-01-31', 1)).toBe('2025-02-28');
    expect(shiftMonth('2024-03-31', -1)).toBe('2024-02-29');
    expect(shiftMonth('2025-12-15', 1)).toBe('2026-01-15');
    expect(shiftMonth('2025-01-15', -13)).toBe('2023-12-15');
  });
});

describe('dayFlows', () => {
  it('adds up each day and spots transfer-only days', () => {
    const flows = dayFlows([
      transaction('2025-02-03', -500, 'expense'),
      transaction('2025-02-03', 2000, 'income'),
      transaction('2025-02-04', 0, 'transfer'),
    ]);
    expect(flows.get('2025-02-03')).toEqual({ net: 1500, count: 2, transfersOnly: false });
    expect(flows.get('2025-02-04')).toEqual({ net: 0, count: 1, transfersOnly: true });
  });
});

describe('periods', () => {
  // Most recently started first, as returned by GET /periods?on=.
  const covering = [period(3, '2025-02-10'), period(2, '2025-02-05'), period(1, '2025-02-01')];

  it('keeps the current period while it covers the day', () => {
    expect(choosePeriod(covering, 2)?.id).toBe(2);
    expect(choosePeriod(covering, 9)?.id).toBe(3);
    expect(choosePeriod([], 1)).toBeNull();
  });

  it('cycles chronologically and wraps', () => {
    expect(cyclePeriod(covering, 3, 1)?.id).toBe(1);
    expect(cyclePeriod(covering, 1, 1)?.id).toBe(2);
    expect(cyclePeriod(covering, 1, -1)?.id).toBe(3);
  });
});
