/** Calendar logic of the overview. */

import type { Period, Transaction } from '../api/types';
import { addDays, daysInMonth, makeDay, parts, weekday, type Day } from './dates';

export const WEEKS = 6;

export interface DayFlow {
  /** Sum of the external splits (income minus expenses). */
  net: number;
  count: number;
  transfersOnly: boolean;
}

/** Six Monday-first weeks covering a month. */
export function monthGrid(year: number, month: number): Day[][] {
  const first = makeDay(year, month, 1);
  const start = addDays(first, -weekday(first));
  return Array.from({ length: WEEKS }, (_, week) =>
    Array.from({ length: 7 }, (_, day) => addDays(start, week * 7 + day)),
  );
}

export function visibleRange(year: number, month: number): [Day, Day] {
  const grid = monthGrid(year, month);
  return [grid[0]![0]!, grid[WEEKS - 1]![6]!];
}

/** Move a day by whole months, clamping it to the length of the month. */
export function shiftMonth(day: Day, months: number): Day {
  const { year, month, day: date } = parts(day);
  const index = year * 12 + month - 1 + months;
  const newYear = Math.floor(index / 12);
  const newMonth = index - newYear * 12 + 1;
  return makeDay(newYear, newMonth, Math.min(date, daysInMonth(newYear, newMonth)));
}

export function dayFlows(transactions: Iterable<Transaction>): Map<Day, DayFlow> {
  const totals = new Map<Day, DayFlow>();
  for (const transaction of transactions) {
    const current = totals.get(transaction.date) ?? { net: 0, count: 0, transfersOnly: true };
    totals.set(transaction.date, {
      net: current.net + transaction.net_amount,
      count: current.count + 1,
      transfersOnly: current.transfersOnly && transaction.kind === 'transfer',
    });
  }
  return totals;
}

/**
 * The period to show for a day: keep the current one while it covers the day,
 * otherwise the most recently started. `covering` is ordered as returned by
 * `GET /periods?on=` (most recently started first).
 */
export function choosePeriod(covering: readonly Period[], currentId: number | null): Period | null {
  return covering.find((period) => period.id === currentId) ?? covering[0] ?? null;
}

/** Previous (`step = -1`) or next (`step = 1`) covering period, chronologically, wrapping. */
export function cyclePeriod(
  covering: readonly Period[],
  currentId: number | null,
  step: number,
): Period | null {
  if (!covering.length) return null;
  const ordered = [...covering].reverse();
  const found = ordered.findIndex((period) => period.id === currentId);
  const index = found >= 0 ? found : ordered.length - 1;
  const length = ordered.length;
  return ordered[(((index + step) % length) + length) % length] ?? null;
}

/** Whether a period covers a day. */
export function covers(period: Period, day: Day): boolean {
  return period.start <= day && (period.end === null || day <= period.end);
}
