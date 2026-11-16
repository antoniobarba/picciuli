import { monthName, parts, type Day } from './dates';

/** Where an account is heading: its goal, or zero while it is in debt. */
export interface Target {
  target: number;
  /** Progress toward the target, 1 when reached (may exceed 1). */
  fraction: number;
}

/**
 * The target of an account. A goal wins; otherwise a negative balance heads to
 * zero, measured from the lowest point of the current debt (`lowPoint`).
 */
export function accountTarget(goal: number | null | undefined, current: number, lowPoint: number | null | undefined): Target | null {
  if (goal) return { target: goal, fraction: current / goal };
  if (current < 0 && lowPoint != null && lowPoint < 0) return { target: 0, fraction: 1 - current / lowPoint };
  return null;
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
