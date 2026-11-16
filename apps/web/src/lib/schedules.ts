/** Recurring transactions: rule labels, form drafts and API bodies. */

import type {
  CatchUp,
  Schedule,
  ScheduleCreate,
  ScheduleFrequency,
  ScheduleMode,
  Transaction,
} from '../api/types';
import { shiftMonth } from './calendar';
import { parts, shortDate, type Day } from './dates';
import { draftFromTransaction, draftSplits, emptyDraft, InputError, optionalText, parseDate, type TransactionDraft } from './forms';
import type { MoneyFormat } from './money';

export const FREQUENCY_LABELS: Record<ScheduleFrequency, string> = {
  daily: 'Days',
  weekly: 'Weeks',
  monthly: 'Months',
  yearly: 'Years',
};

const UNITS: Record<ScheduleFrequency, [string, string]> = {
  daily: ['day', 'days'],
  weekly: ['week', 'weeks'],
  monthly: ['month', 'months'],
  yearly: ['year', 'years'],
};

export const MODE_LABELS: Record<ScheduleMode, string> = {
  auto: 'Add it automatically',
  confirm: 'Remind me to confirm it',
};

/** Largest number of units between two occurrences (the API limit). */
export const MAX_EVERY = 1000;

/** The day of the month meaning "the last day of every month". */
export const LAST_DAY = 31;

/** `Every month on day 27`, `Every 2 weeks, 3 left`, `Every year, until 01 Jan 2030`. */
export function ruleText(
  schedule: Pick<Schedule, 'frequency' | 'every' | 'day_of_month' | 'end' | 'remaining'>,
): string {
  const [one, many] = UNITS[schedule.frequency];
  let text = schedule.every === 1 ? `Every ${one}` : `Every ${schedule.every} ${many}`;
  if (schedule.frequency === 'monthly' && schedule.day_of_month) {
    text += schedule.day_of_month === LAST_DAY ? ' on the last day' : ` on day ${schedule.day_of_month}`;
  }
  if (schedule.end) text += `, until ${shortDate(schedule.end)}`;
  else if (schedule.remaining != null) text += `, ${schedule.remaining} left`;
  return text;
}

/** `Paused`, `Finished`, `Failed` or nothing, for the status column. */
export function scheduleStatus(schedule: Schedule): 'paused' | 'finished' | 'failed' | null {
  if (schedule.is_finished) return 'finished';
  if (schedule.paused) return 'paused';
  if (schedule.last_error) return 'failed';
  return null;
}

export type EndKind = 'never' | 'date' | 'count';

export interface ScheduleDraft {
  /** What each occurrence records; its date is the first (or next) occurrence. */
  transaction: TransactionDraft;
  frequency: ScheduleFrequency;
  every: string;
  /** Monthly and yearly: fall on the last day of every month. */
  lastDay: boolean;
  endKind: EndKind;
  end: string;
  /** Occurrences left, with `endKind: 'count'`. */
  count: string;
  mode: ScheduleMode;
}

export function emptyScheduleDraft(day: Day, accountId: number | null = null): ScheduleDraft {
  return {
    transaction: emptyDraft(day, accountId),
    frequency: 'monthly',
    every: '1',
    lastDay: false,
    endKind: 'never',
    end: '',
    count: '',
    mode: 'auto',
  };
}

/** A transaction made from the template of a schedule, for drafts and forms. */
export function templateTransaction(schedule: Schedule, date: Day): Transaction {
  return {
    id: 0,
    date,
    description: schedule.description,
    notes: schedule.notes,
    splits: schedule.splits,
    kind: schedule.kind,
    net_amount: schedule.net_amount,
    schedule_id: schedule.id,
  };
}

/** Repeat an existing transaction every month, starting a month after it. */
export function scheduleDraftFromTransaction(transaction: Transaction, money: MoneyFormat): ScheduleDraft {
  const next = shiftMonth(transaction.date, 1);
  return {
    ...emptyScheduleDraft(next),
    transaction: { ...draftFromTransaction(transaction, money), date: next },
    lastDay: parts(transaction.date).day === LAST_DAY,
  };
}

export function scheduleDraftFromSchedule(schedule: Schedule, money: MoneyFormat, today: Day): ScheduleDraft {
  const next = schedule.next_date ?? today;
  return {
    transaction: draftFromTransaction(templateTransaction(schedule, next), money),
    frequency: schedule.frequency,
    every: String(schedule.every),
    lastDay: schedule.day_of_month === LAST_DAY,
    endKind: schedule.end ? 'date' : schedule.remaining != null ? 'count' : 'never',
    end: schedule.end ?? '',
    count: schedule.remaining != null ? String(schedule.remaining) : '',
    mode: schedule.mode,
  };
}

function positiveInteger(text: string, label: string, max?: number): number {
  const cleaned = text.trim();
  const value = Number(cleaned);
  if (!/^\d+$/.test(cleaned) || value < 1 || (max !== undefined && value > max)) {
    throw new InputError(max === undefined ? `${label} must be a whole number of at least 1` : `${label} must be between 1 and ${max}`);
  }
  return value;
}

/** The body creating (or, with `next_date`, updating) a schedule from a draft. */
export function scheduleBody(draft: ScheduleDraft, money: MoneyFormat, today: Day): ScheduleCreate {
  const start = parseDate(draft.transaction.date, today);
  const monthly = draft.frequency === 'monthly' || draft.frequency === 'yearly';
  const end = draft.endKind === 'date' ? parseDate(draft.end, today) : null;
  if (end !== null && end < start) throw new InputError('the end date is before the first occurrence');
  return {
    start,
    splits: draftSplits(draft.transaction, money),
    frequency: draft.frequency,
    every: positiveInteger(draft.every, 'the repeat interval', MAX_EVERY),
    day_of_month: monthly ? (draft.lastDay ? LAST_DAY : parts(start).day) : null,
    end,
    occurrences: draft.endKind === 'count' ? positiveInteger(draft.count, 'the number of times') : null,
    mode: draft.mode,
    description: optionalText(draft.transaction.description),
    notes: optionalText(draft.transaction.notes),
  };
}

/** Schedules waiting for confirmation since `today` or earlier, oldest first. */
export function toConfirm(schedules: readonly Schedule[], today: Day): Schedule[] {
  return schedules
    .filter((s) => s.mode === 'confirm' && !s.paused && s.next_date !== null && s.next_date <= today)
    .sort((a, b) => a.next_date!.localeCompare(b.next_date!) || a.id - b.id);
}

/** Automatic schedules stuck on an error. */
export function failing(schedules: readonly Schedule[]): Schedule[] {
  return schedules.filter((s) => !s.paused && !s.is_finished && s.last_error);
}

/** What catching up did, as one sentence, or `null` when it did nothing worth telling. */
export function catchUpMessage(result: CatchUp): string | null {
  const parts: string[] = [];
  const posted = result.posted.length;
  if (posted) parts.push(`added ${posted} recurring transaction${posted === 1 ? '' : 's'}`);
  if (result.periods.length) {
    parts.push(`started ${result.periods.map((p) => p.name).join(', ')}`);
  }
  const due = result.due.length;
  if (due) parts.push(`${due} recurring transaction${due === 1 ? '' : 's'} to confirm`);
  if (!parts.length) return null;
  const text = parts.join(', ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}
