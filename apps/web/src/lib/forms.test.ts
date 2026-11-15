import { describe, expect, it } from 'vitest';
import type { Transaction } from '../api/types';
import {
  draftFromTransaction,
  draftSplits,
  emptyDraft,
  emptyLine,
  InputError,
  lineTotals,
  parseDate,
  simpleLines,
  type TransactionDraft,
} from './forms';
import { MoneyFormat } from './money';

const TODAY = '2025-03-12';
const money = new MoneyFormat('€', 2);

describe('parseDate', () => {
  it.each([
    ['2025-02-03', '2025-02-03'],
    [' 3/2/2025 ', '2025-02-03'],
    ['3.2.25', '2025-02-03'],
    ['3/2', '2025-02-03'],
    ['5', '2025-03-05'],
    ['Today', TODAY],
    ['+1', '2025-03-13'],
    ['-12', '2025-02-28'],
  ])('parses %s', (text, expected) => {
    expect(parseDate(text, TODAY)).toBe(expected);
  });

  it.each(['', '  ', '2025-02-30', '32', '1/2/3/4', 'soon', '+x'])('rejects %s', (text) => {
    expect(() => parseDate(text, TODAY)).toThrow(InputError);
  });
});

const draft = (changes: Partial<TransactionDraft>): TransactionDraft => ({
  ...emptyDraft(TODAY),
  ...changes,
});

describe('draftSplits', () => {
  it('builds expenses, income and transfers', () => {
    expect(draftSplits(draft({ amount: '12,50', accountId: 1, categoryId: 4 }), money)).toEqual([
      { type: 'account', account_id: 1, amount: -1250 },
      { type: 'external', amount: -1250, category_id: 4 },
    ]);
    expect(draftSplits(draft({ kind: 'income', amount: '3', accountId: 1, categoryId: 0 }), money)).toEqual([
      { type: 'account', account_id: 1, amount: 300 },
      { type: 'external', amount: 300, category_id: null },
    ]);
    expect(
      draftSplits(draft({ kind: 'transfer', amount: '5', accountId: 1, toAccountId: 2 }), money),
    ).toEqual([
      { type: 'account', account_id: 1, amount: -500 },
      { type: 'account', account_id: 2, amount: 500 },
    ]);
  });

  it.each<[Partial<TransactionDraft>, string]>([
    [{ amount: '' }, 'an amount is required'],
    [{ amount: '-1', accountId: 1 }, 'positive'],
    [{ amount: '1' }, 'choose an account'],
    [{ kind: 'transfer', amount: '1', accountId: 1 }, 'destination'],
    [{ kind: 'transfer', amount: '1', accountId: 1, toAccountId: 1 }, 'different'],
    [{ kind: 'split', lines: [{ ...emptyLine(), amount: '1' }] }, 'account or category'],
    [{ kind: 'split', lines: [{ ...emptyLine('a:1'), amount: ' ' }] }, 'needs an amount'],
    [{ kind: 'split', lines: [{ ...emptyLine('c:1'), amount: '0' }] }, 'cannot be zero'],
  ])('rejects %j', (changes, message) => {
    expect(() => draftSplits(draft(changes), money)).toThrow(message);
  });

  it('ignores empty split lines and totals the valid ones', () => {
    const lines = [
      { ...emptyLine('a:1'), amount: '-30' },
      { ...emptyLine('c:2'), amount: '-10', memo: 'food' },
      { ...emptyLine('c:0'), amount: 'oops' },
      emptyLine(),
    ];
    expect(lineTotals(lines, money)).toEqual([-3000, -1000]);
    const balanced = [...lines.slice(0, 2), { ...emptyLine('c:0'), amount: '-20' }, emptyLine()];
    expect(draftSplits(draft({ kind: 'split', lines: balanced }), money)).toEqual([
      { type: 'account', account_id: 1, amount: -3000, memo: null },
      { type: 'external', amount: -1000, category_id: 2, memo: 'food' },
      { type: 'external', amount: -2000, category_id: null, memo: null },
    ]);
    expect(() => draftSplits(draft({ kind: 'split', lines: lines.slice(0, 2) }), money)).toThrow(
      'the account lines (-€30.00) and the income/expense lines (-€10.00) must match',
    );
  });

  it('switches a simple draft to at least three split lines', () => {
    const lines = simpleLines(draft({ amount: '7', accountId: 1, categoryId: 3 }), money);
    expect(lines.map((l) => [l.target, l.amount])).toEqual([
      ['a:1', '-7.00'],
      ['c:3', '-7.00'],
      ['', ''],
    ]);
    expect(simpleLines(draft({ accountId: 2 }), money)[0]!.target).toBe('a:2');
  });
});

describe('draftFromTransaction', () => {
  const base = { id: 1, date: '2025-03-01', description: 'd', notes: 'n', net_amount: 0 };

  it('opens simple shapes in the simple form', () => {
    const expense: Transaction = {
      ...base,
      kind: 'expense',
      splits: [
        { type: 'account', account_id: 1, amount: -500 },
        { type: 'external', amount: -500, category_id: null },
      ],
    };
    expect(draftFromTransaction(expense, money)).toMatchObject({
      kind: 'expense',
      amount: '5.00',
      accountId: 1,
      categoryId: 0,
      date: '2025-03-01',
      description: 'd',
      notes: 'n',
    });
    const transfer: Transaction = {
      ...base,
      kind: 'transfer',
      splits: [
        { type: 'account', account_id: 2, amount: 900 },
        { type: 'account', account_id: 1, amount: -900 },
      ],
    };
    expect(draftFromTransaction(transfer, money)).toMatchObject({
      kind: 'transfer',
      amount: '9.00',
      accountId: 1,
      toAccountId: 2,
    });
  });

  it('opens purchases in the split editor and keeps the shares', () => {
    const buy: Transaction = {
      ...base,
      kind: 'transfer',
      splits: [
        { type: 'account', account_id: 5, amount: 10000, security_id: 7, quantity: '1.5' },
        { type: 'account', account_id: 1, amount: -10000 },
      ],
    };
    const result = draftFromTransaction(buy, money);
    expect(result.kind).toBe('split');
    expect(result.lines[0]).toMatchObject({ target: 'a:5', securityId: 7, quantity: '1.5' });
    expect(draftSplits(result, money)[0]).toEqual({
      type: 'account',
      account_id: 5,
      amount: 10000,
      memo: null,
      security_id: 7,
      quantity: '1.5',
    });
  });
});
