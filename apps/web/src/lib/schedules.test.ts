import { describe, expect, it } from 'vitest';
import type { CatchUp, Schedule, Transaction } from '../api/types';
import { emptyDraft, InputError } from './forms';
import { MoneyFormat } from './money';
import {
  catchUpMessage,
  emptyScheduleDraft,
  ruleText,
  scheduleBody,
  scheduleDraftFromSchedule,
  scheduleDraftFromTransaction,
  toConfirm,
  type ScheduleDraft,
} from './schedules';

const money = new MoneyFormat('€', 2);
const today = '2026-11-16';

function schedule(overrides: Partial<Schedule> = {}): Schedule {
  return {
    id: 1,
    description: 'Rent',
    notes: null,
    splits: [
      { type: 'account', account_id: 1, amount: -80000 },
      { type: 'external', amount: -80000, category_id: 2 },
    ],
    frequency: 'monthly',
    every: 1,
    day_of_month: 31,
    next_date: '2026-11-30',
    end: null,
    remaining: null,
    mode: 'auto',
    paused: false,
    last_error: null,
    kind: 'expense',
    net_amount: -80000,
    is_finished: false,
    ...overrides,
  };
}

describe('ruleText', () => {
  it('describes the repetition and its end', () => {
    expect(ruleText(schedule())).toBe('Every month on the last day');
    expect(ruleText(schedule({ day_of_month: 27, remaining: 3 }))).toBe('Every month on day 27, 3 left');
    expect(ruleText(schedule({ frequency: 'weekly', every: 2, day_of_month: null }))).toBe('Every 2 weeks');
    expect(ruleText(schedule({ frequency: 'yearly', end: '2030-01-01' }))).toBe('Every year, until 01 Jan 2030');
  });
});

describe('scheduleBody', () => {
  const draft = (changes: Partial<ScheduleDraft> = {}): ScheduleDraft => ({
    ...emptyScheduleDraft('2026-11-27', 1),
    transaction: { ...emptyDraft('2026-11-27', 1), amount: '1800', categoryId: 2, kind: 'income', description: ' Salary ' },
    ...changes,
  });

  it('builds a monthly schedule on the day of its first date', () => {
    expect(scheduleBody(draft(), money, today)).toEqual({
      start: '2026-11-27',
      splits: [
        { type: 'account', account_id: 1, amount: 180000 },
        { type: 'external', amount: 180000, category_id: 2 },
      ],
      frequency: 'monthly',
      every: 1,
      day_of_month: 27,
      end: null,
      occurrences: null,
      mode: 'auto',
      description: 'Salary',
      notes: null,
    });
  });

  it('handles the last day, other units, end dates and counts', () => {
    expect(scheduleBody(draft({ lastDay: true }), money, today).day_of_month).toBe(31);
    const weekly = scheduleBody(draft({ frequency: 'weekly', every: '2', endKind: 'count', count: '6' }), money, today);
    expect([weekly.day_of_month, weekly.every, weekly.occurrences, weekly.end]).toEqual([null, 2, 6, null]);
    const ending = scheduleBody(draft({ endKind: 'date', end: '31/12/2027', mode: 'confirm' }), money, today);
    expect([ending.end, ending.occurrences, ending.mode]).toEqual(['2027-12-31', null, 'confirm']);
  });

  it('rejects impossible rules', () => {
    expect(() => scheduleBody(draft({ every: '0' }), money, today)).toThrow(InputError);
    expect(() => scheduleBody(draft({ every: '1.5' }), money, today)).toThrow('between 1 and 1000');
    expect(() => scheduleBody(draft({ endKind: 'count', count: '' }), money, today)).toThrow('number of times');
    expect(() => scheduleBody(draft({ endKind: 'date', end: '2026-01-01' }), money, today)).toThrow('before the first');
  });
});

describe('drafts', () => {
  it('repeats a transaction from a month later', () => {
    const transaction: Transaction = {
      id: 9,
      date: '2026-01-31',
      description: 'Gym',
      notes: null,
      kind: 'expense',
      net_amount: -3000,
      splits: [
        { type: 'account', account_id: 1, amount: -3000 },
        { type: 'external', amount: -3000, category_id: null },
      ],
    };
    const draft = scheduleDraftFromTransaction(transaction, money);
    expect([draft.transaction.date, draft.transaction.amount, draft.lastDay]).toEqual(['2026-02-28', '30.00', true]);
    expect(scheduleBody(draft, money, today).day_of_month).toBe(31);
  });

  it('edits a schedule from its next date', () => {
    const draft = scheduleDraftFromSchedule(schedule({ remaining: 4 }), money, today);
    expect([draft.transaction.date, draft.transaction.kind, draft.transaction.amount]).toEqual([
      '2026-11-30',
      'expense',
      '800.00',
    ]);
    expect([draft.lastDay, draft.endKind, draft.count]).toEqual([true, 'count', '4']);
  });
});

it('lists schedules waiting for confirmation, oldest first', () => {
  const waiting = [
    schedule({ id: 1, mode: 'confirm', next_date: '2026-11-10' }),
    schedule({ id: 2, mode: 'confirm', next_date: '2026-11-01' }),
    schedule({ id: 3, mode: 'confirm', next_date: '2026-12-01' }),
    schedule({ id: 4, mode: 'confirm', next_date: '2026-11-02', paused: true }),
    schedule({ id: 5, next_date: '2026-11-02' }),
  ];
  expect(toConfirm(waiting, today).map((s) => s.id)).toEqual([2, 1]);
});

it('summarizes a catch-up', () => {
  const empty: CatchUp = { periods: [], posted: [], due: [], failed: [] };
  expect(catchUpMessage(empty)).toBeNull();
  const result = {
    ...empty,
    posted: [{}, {}] as CatchUp['posted'],
    periods: [{ id: 1, name: 'December 2026', start: '2026-11-27', end: '2026-12-26' }],
    due: [{ schedule_id: 1, date: '2026-11-10' }],
  };
  expect(catchUpMessage(result)).toBe(
    'Added 2 recurring transactions, started December 2026, 1 recurring transaction to confirm',
  );
});
