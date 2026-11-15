/**
 * Turn what the user typed into API bodies, ported from the TUI's `forms.py`.
 * Keeping this logic free of components makes it easy to test.
 */

import type { SplitIn, Transaction } from '../api/types';
import { addDays, daysInMonth, isValidDay, makeDay, monthTitle, parts, type Day } from './dates';
import { InputError, MoneyFormat, parseQuantity } from './money';

export { InputError };

/** Choice value meaning "no category" or "no account" (identifiers are positive). */
export const NONE_ID = 0;

/**
 * Parse a typed day: `2025-02-03`, `3/2/2025`, `3/2` (this year), `3` (this
 * month), `today`, and offsets such as `+1` or `-7` days from `today`.
 */
export function parseDate(text: string, today: Day): Day {
  const cleaned = text.trim().toLowerCase();
  if (!cleaned) throw new InputError('a date is required');
  if (cleaned === 'today') return today;
  const invalid = () =>
    new InputError(`invalid date: '${text.trim()}' (use YYYY-MM-DD or DD/MM/YYYY)`);
  if (/^[+-]\d+$/.test(cleaned)) return addDays(today, Number(cleaned));
  const t = parts(today);
  let year: number;
  let month: number;
  let day: number;
  const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(cleaned);
  if (iso) {
    [year, month, day] = [Number(iso[1]), Number(iso[2]), Number(iso[3])];
  } else if (/^\d+([./]\d+){0,2}$/.test(cleaned)) {
    const numbers = cleaned.split(/[./]/).map(Number);
    if (numbers.length === 1) {
      [year, month, day] = [t.year, t.month, numbers[0]!];
    } else if (numbers.length === 2) {
      [year, month, day] = [t.year, numbers[1]!, numbers[0]!];
    } else {
      const y = numbers[2]!;
      [year, month, day] = [y < 100 ? y + 2000 : y, numbers[1]!, numbers[0]!];
    }
  } else {
    throw invalid();
  }
  if (!isValidDay(year, month, day)) throw invalid();
  return makeDay(year, month, day);
}

export function optionalDate(text: string, today: Day): Day | null {
  return text.trim() ? parseDate(text, today) : null;
}

export function optionalAmount(text: string, money: MoneyFormat): number | null {
  return text.trim() ? money.parse(text) : null;
}

export function positiveAmount(text: string, money: MoneyFormat): number {
  if (!text.trim()) throw new InputError('an amount is required');
  const amount = money.parse(text);
  if (amount <= 0) throw new InputError('enter a positive amount');
  return amount;
}

export function nonNegativeAmount(text: string, money: MoneyFormat, label: string): number {
  const value = optionalAmount(text, money) ?? 0;
  if (value < 0) throw new InputError(`the ${label} cannot be negative`);
  return value;
}

export function optionalText(text: string): string | null {
  return text.trim() || null;
}

export function requiredId(value: number | null | undefined, label: string): number {
  if (!value) throw new InputError(`choose ${label}`);
  return value;
}

/** The default name of a period starting on `start`, e.g. `February 2025`. */
export function defaultPeriodName(start: Day): string {
  const { year, month } = parts(start);
  return monthTitle(year, month);
}

/** Last day of the month of `day`. */
export function endOfMonth(day: Day): Day {
  const { year, month } = parts(day);
  return makeDay(year, month, daysInMonth(year, month));
}

// Transactions

export type EntryKind = 'expense' | 'income' | 'transfer' | 'split';

export const ENTRY_KIND_LABELS: Record<EntryKind, string> = {
  expense: 'Expense',
  income: 'Income',
  transfer: 'Transfer',
  split: 'Split',
};

export function accountTarget(accountId: number): string {
  return `a:${accountId}`;
}

export function categoryTarget(categoryId: number | null | undefined): string {
  return `c:${categoryId || NONE_ID}`;
}

/** One split line as typed in the split editor. */
export interface LineDraft {
  /** `a:<account id>` or `c:<category id>` (`c:0` for uncategorized). */
  target: string;
  /** Signed amount text. */
  amount: string;
  memo: string;
  /** Kept unchanged when an existing purchase or sale is edited. */
  securityId: number | null;
  quantity: string;
}

export function emptyLine(target = ''): LineDraft {
  return { target, amount: '', memo: '', securityId: null, quantity: '' };
}

export interface TransactionDraft {
  kind: EntryKind;
  date: string;
  description: string;
  notes: string;
  amount: string;
  accountId: number | null;
  categoryId: number | null;
  toAccountId: number | null;
  lines: LineDraft[];
}

export function emptyDraft(date: Day, accountId: number | null = null): TransactionDraft {
  return {
    kind: 'expense',
    date,
    description: '',
    notes: '',
    amount: '',
    accountId,
    categoryId: NONE_ID,
    toAccountId: null,
    lines: [],
  };
}

function lineSplit(line: LineDraft, money: MoneyFormat): SplitIn {
  const match = /^([ac]):(\d+)$/.exec(line.target);
  if (!match) throw new InputError('choose an account or category for every split line');
  if (!line.amount.trim()) throw new InputError('every split line needs an amount');
  const amount = money.parse(line.amount);
  const id = Number(match[2]);
  const shares = match[1] === 'a' && line.securityId !== null;
  if (amount === 0 && !shares) throw new InputError('split amounts cannot be zero');
  const memo = optionalText(line.memo);
  if (match[1] === 'a') {
    if (shares) {
      return {
        type: 'account',
        account_id: id,
        amount,
        memo,
        security_id: line.securityId,
        quantity: parseQuantity(line.quantity, true),
      };
    }
    return { type: 'account', account_id: id, amount, memo };
  }
  return { type: 'external', amount, category_id: id || null, memo };
}

function isBlank(line: LineDraft): boolean {
  return !line.target && !line.amount.trim() && !line.memo.trim();
}

/** Split lines as API splits, ignoring completely empty lines. */
export function lineSplits(lines: readonly LineDraft[], money: MoneyFormat): SplitIn[] {
  return lines.filter((line) => !isBlank(line)).map((line) => lineSplit(line, money));
}

/** The account and external totals of the lines that can be parsed. */
export function lineTotals(lines: readonly LineDraft[], money: MoneyFormat): [number, number] {
  let accounts = 0;
  let external = 0;
  for (const line of lines) {
    try {
      const split = lineSplit(line, money);
      if (split.type === 'account') accounts += split.amount;
      else external += split.amount;
    } catch {
      // Lines that cannot be parsed yet do not count.
    }
  }
  return [accounts, external];
}

/** The splits of an expense, income or transfer draft. */
export function simpleSplits(draft: TransactionDraft, money: MoneyFormat): SplitIn[] {
  const amount = positiveAmount(draft.amount, money);
  const account = requiredId(draft.accountId, 'an account');
  if (draft.kind === 'transfer') {
    const target = requiredId(draft.toAccountId, 'the destination account');
    if (target === account) throw new InputError('choose two different accounts');
    return [
      { type: 'account', account_id: account, amount: -amount },
      { type: 'account', account_id: target, amount },
    ];
  }
  const signed = draft.kind === 'expense' ? -amount : amount;
  return [
    { type: 'account', account_id: account, amount: signed },
    { type: 'external', amount: signed, category_id: draft.categoryId || null },
  ];
}

export function draftSplits(draft: TransactionDraft, money: MoneyFormat): SplitIn[] {
  if (draft.kind !== 'split') return simpleSplits(draft, money);
  const splits = lineSplits(draft.lines, money);
  const accounts = splits.filter((s) => s.type === 'account').reduce((sum, s) => sum + s.amount, 0);
  const external = splits.filter((s) => s.type === 'external').reduce((sum, s) => sum + s.amount, 0);
  if (accounts !== external) {
    throw new InputError(
      `the account lines (${money.amount(accounts)}) and the income/expense lines (${money.amount(external)}) must match`,
    );
  }
  return splits;
}

/** Minimum number of lines shown when switching to the split editor. */
export const SPLIT_EDITOR_LINES = 3;

function splitLines(splits: readonly SplitIn[], money: MoneyFormat): LineDraft[] {
  return splits.map((s) =>
    s.type === 'account'
      ? {
          target: accountTarget(s.account_id),
          amount: money.plain(s.amount),
          memo: s.memo ?? '',
          securityId: s.security_id ?? null,
          quantity: s.quantity == null ? '' : String(s.quantity),
        }
      : {
          target: categoryTarget(s.category_id),
          amount: money.plain(s.amount),
          memo: s.memo ?? '',
          securityId: null,
          quantity: '',
        },
  );
}

/** Convert a simple draft into split lines, for switching to the split editor. */
export function simpleLines(draft: TransactionDraft, money: MoneyFormat): LineDraft[] {
  let lines: LineDraft[];
  try {
    lines = splitLines(simpleSplits(draft, money), money);
  } catch {
    lines = [emptyLine(draft.accountId ? accountTarget(draft.accountId) : '')];
  }
  while (lines.length < SPLIT_EDITOR_LINES) lines.push(emptyLine());
  return lines;
}

/**
 * The draft that edits an existing transaction. Simple shapes open in the
 * matching simple kind; everything else, including purchases and sales of
 * shares, opens in the split editor.
 */
export function draftFromTransaction(transaction: Transaction, money: MoneyFormat): TransactionDraft {
  const draft = emptyDraft(transaction.date);
  draft.description = transaction.description ?? '';
  draft.notes = transaction.notes ?? '';
  const accounts = transaction.splits.filter((s) => s.type === 'account');
  const external = transaction.splits.filter((s) => s.type === 'external');
  const simple =
    !transaction.splits.some((s) => s.memo) && !accounts.some((s) => s.security_id != null);
  if (simple && accounts.length === 1 && external.length === 1) {
    const [account, flow] = [accounts[0]!, external[0]!];
    draft.kind = flow.amount < 0 ? 'expense' : 'income';
    draft.amount = money.plain(Math.abs(flow.amount));
    draft.accountId = account.account_id;
    draft.categoryId = flow.category_id ?? NONE_ID;
    return draft;
  }
  if (
    simple &&
    !external.length &&
    accounts.length === 2 &&
    accounts[0]!.amount === -accounts[1]!.amount
  ) {
    const [source, target] = [...accounts].sort((a, b) => a.amount - b.amount) as [
      (typeof accounts)[number],
      (typeof accounts)[number],
    ];
    draft.kind = 'transfer';
    draft.amount = money.plain(target.amount);
    draft.accountId = source.account_id;
    draft.toAccountId = target.account_id;
    return draft;
  }
  draft.kind = 'split';
  draft.lines = splitLines(
    transaction.splits.map((s) =>
      s.type === 'account'
        ? { ...s, type: 'account' as const }
        : { ...s, type: 'external' as const },
    ),
    money,
  );
  return draft;
}
