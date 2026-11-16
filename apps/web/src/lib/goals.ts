import type { AccountType, Goal, GoalPriority } from '../api/types';
import { monthName, parts, type Day } from './dates';

/** Where an account in debt is heading: zero. */
export interface Target {
  target: number;
  /** Progress toward the target, 1 when reached (may exceed 1). */
  fraction: number;
}

/**
 * The target of an account while its balance is negative: zero, measured from
 * the lowest point of the current debt (`lowPoint`).
 */
export function debtTarget(current: number, lowPoint: number | null | undefined): Target | null {
  if (current < 0 && lowPoint != null && lowPoint < 0) return { target: 0, fraction: 1 - current / lowPoint };
  return null;
}

/** Account types that can hold savings goals: cash-like assets. */
export const GOAL_ACCOUNT_TYPES: readonly AccountType[] = ['checking', 'savings', 'cash', 'other_asset'];

export function canHoldGoals(type: AccountType): boolean {
  return GOAL_ACCOUNT_TYPES.includes(type);
}

export const PRIORITY_LABELS: Record<GoalPriority, string> = { high: 'High', normal: 'Normal', low: 'Low' };

/** Share of the target already saved; 1 or more once reached. */
export function savedFraction(goal: Goal): number {
  return goal.saved_amount / goal.target_amount;
}

export type Eta =
  | { kind: 'reached' }
  /** No complete month of history to average. */
  | { kind: 'unknown' }
  /** The average flow does not move toward the target (or takes too long). */
  | { kind: 'never' }
  | { kind: 'month'; year: number; month: number };

/** Longest forecast worth showing: 100 years. */
const MAX_MONTHS = 1200;

/**
 * The month when `current` reaches `target` (from below) if the balance keeps
 * changing by `averageFlow` every month after the current one.
 */
export function targetEta(current: number, target: number, averageFlow: number | null | undefined, today: Day): Eta {
  const remaining = target - current;
  if (remaining <= 0) return { kind: 'reached' };
  if (averageFlow == null) return { kind: 'unknown' };
  if (averageFlow <= 0) return { kind: 'never' };
  const months = Math.ceil(remaining / averageFlow);
  if (months > MAX_MONTHS) return { kind: 'never' };
  const { year, month } = parts(today);
  const index = year * 12 + (month - 1) + months;
  return { kind: 'month', year: Math.floor(index / 12), month: (index % 12) + 1 };
}

/** `Mar 2027`, `reached`, or an empty string when there is no forecast. */
export function etaLabel(eta: Eta): string {
  switch (eta.kind) {
    case 'reached':
      return 'reached';
    case 'never':
      return '—';
    case 'unknown':
      return '';
    case 'month':
      return `${monthName(eta.month).slice(0, 3)} ${eta.year}`;
  }
}
