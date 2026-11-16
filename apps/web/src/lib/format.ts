/** Labels shared by every screen. */

import type {
  Account,
  AccountType,
  Category,
  CostMethod,
  Period,
  SecurityKind,
  Transaction,
} from '../api/types';
import { shortDate } from './dates';

export const ACCOUNT_TYPE_LABELS: Record<AccountType, string> = {
  checking: 'Checking',
  savings: 'Savings',
  cash: 'Cash',
  investment: 'Investment',
  other_asset: 'Other asset',
  credit_card: 'Credit card',
  loan: 'Loan',
  mortgage: 'Mortgage',
  other_liability: 'Other liability',
};

export const SECURITY_KIND_LABELS: Record<SecurityKind, string> = {
  stock: 'Stock',
  etf: 'ETF',
  fund: 'Fund',
  bond: 'Bond',
  crypto: 'Crypto',
  other: 'Other',
};

export const COST_METHOD_LABELS: Record<CostMethod, string> = {
  average: 'Weighted average cost',
  fifo: 'First in, first out (FIFO)',
};

export type ById<T> = ReadonlyMap<number, T>;

export function byId<T extends { id: number }>(items: readonly T[] | undefined): Map<number, T> {
  return new Map((items ?? []).map((item) => [item.id, item]));
}

/** `01 Feb 2025 – open` */
export function periodRange(period: Pick<Period, 'start' | 'end'>): string {
  return `${shortDate(period.start)} – ${period.end ? shortDate(period.end) : 'open'}`;
}

/** `Parent › Child`, the category name, or `Uncategorized`. */
export function categoryLabel(categoryId: number | null | undefined, categories: ById<Category>): string {
  if (categoryId == null) return 'Uncategorized';
  const category = categories.get(categoryId);
  if (!category) return `#${categoryId}`;
  const parent = category.parent_id != null ? categories.get(category.parent_id) : undefined;
  return parent ? `${parent.name} › ${category.name}` : category.name;
}

/** Categories in tree order: each top-level category followed by its children. */
export function categoryTree(categories: readonly Category[]): Category[] {
  const byPosition = (a: Category, b: Category) => a.position - b.position || a.id - b.id;
  const top = categories.filter((c) => c.parent_id === null).sort(byPosition);
  return top.flatMap((parent) => [
    parent,
    ...categories.filter((c) => c.parent_id === parent.id).sort(byPosition),
  ]);
}

export function accountName(accountId: number, accounts: ById<Account>): string {
  return accounts.get(accountId)?.name ?? `#${accountId}`;
}

function accountSplits(transaction: Transaction) {
  return transaction.splits.filter((s) => s.type === 'account');
}

function externalSplits(transaction: Transaction) {
  return transaction.splits.filter((s) => s.type === 'external');
}

/** `Checking → Savings` for transfers, otherwise the accounts touched. */
export function transactionAccounts(transaction: Transaction, accounts: ById<Account>): string {
  const splits = accountSplits(transaction);
  const outgoing = splits.filter((s) => s.amount < 0);
  const incoming = splits.filter((s) => s.amount > 0);
  const names = (list: typeof splits) => list.map((s) => accountName(s.account_id, accounts)).join(', ');
  if (transaction.kind === 'transfer' && outgoing.length && incoming.length) {
    return `${names(outgoing)} → ${names(incoming)}`;
  }
  return names(splits);
}

export function transactionCategory(transaction: Transaction, categories: ById<Category>): string {
  const external = externalSplits(transaction);
  if (!external.length) return 'Transfer';
  const labels = new Set(external.map((s) => categoryLabel(s.category_id, categories)));
  if (labels.size === 1) return [...labels][0]!;
  return `Split (${external.length})`;
}

export function transactionTitle(transaction: Transaction): string {
  return transaction.description || `(${transaction.kind})`;
}

/** The amount moved between accounts by a transfer. */
export function transferAmount(transaction: Transaction): number {
  return accountSplits(transaction)
    .filter((s) => s.amount > 0)
    .reduce((sum, s) => sum + s.amount, 0);
}

/** How much a transaction changes one account. */
export function accountChange(transaction: Transaction, accountId: number): number {
  return accountSplits(transaction)
    .filter((s) => s.account_id === accountId)
    .reduce((sum, s) => sum + s.amount, 0);
}

/** Whether any split moves shares (purchases and sales). */
export function movesShares(transaction: Transaction): boolean {
  return accountSplits(transaction).some((s) => s.security_id != null);
}
