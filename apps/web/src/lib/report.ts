/**
 * Cash-flow reports: the money flowing in and out of some accounts over a
 * stretch of days, by category and by the accounts it is transferred to.
 */

import type { Split, Transaction } from '../api/types';

/**
 * Where a flow goes: `category:<id>` for a category, `account:<id>` for a
 * transfer with an account outside the reported ones.
 */
export type Bucket = `category:${number}` | `account:${number}`;

export const categoryBucket = (id: number): Bucket => `category:${id}`;
export const accountBucket = (id: number): Bucket => `account:${id}`;

export function parseBucket(bucket: Bucket): { kind: 'category' | 'account'; id: number } {
  const [kind, id] = bucket.split(':');
  return { kind: kind as 'category' | 'account', id: Number(id) };
}

export interface ReportSplit {
  /** Unique within a report: the transaction id and the split's position. */
  key: string;
  transaction: Transaction;
  split: Split;
  bucket: Bucket;
  /** Seen from the reported accounts: positive flows into them, negative out of them. */
  amount: number;
}

export interface BucketTotal {
  bucket: Bucket;
  total: number;
}

export interface PieSlice extends BucketTotal {
  /** Share of the chart, from 0 to 1. */
  fraction: number;
  /** SVG path of the slice in a circle of radius 1 centred on the origin. */
  path: string;
}

/**
 * The flows of `transactions` into one of `buckets`, in transaction order.
 *
 * Without `accountIds` (or with none) the whole portfolio is reported: only
 * external splits count, as transfers between accounts cancel out. With
 * `accountIds`, only transactions touching those accounts count, and only
 * for the part the reported accounts take in them: money flowing out of the
 * transaction's accounts (and in from income) is shared among where it goes
 * in proportion, so an expense paid half from a reported account and half
 * from another counts for half. Splits on any other account count as
 * transfers, with their sign flipped since money leaving the reported
 * accounts goes into the other one. Moves between the reported accounts
 * cancel out, and the flows add up to the change in the reported balances.
 */
export function reportSplits(
  transactions: readonly Transaction[],
  buckets: ReadonlySet<Bucket>,
  accountIds?: ReadonlySet<number>,
): ReportSplit[] {
  const some = accountIds !== undefined && accountIds.size > 0;
  return transactions.flatMap((transaction) => {
    if (some && !transaction.splits.some((s) => s.type === 'account' && accountIds.has(s.account_id))) return [];
    const shares = some ? reportedShares(transaction, accountIds) : undefined;
    return transaction.splits.flatMap((split, index): ReportSplit[] => {
      let bucket: Bucket;
      let amount: number;
      if (split.type === 'external') {
        if (split.category_id == null) return [];
        bucket = categoryBucket(split.category_id);
        amount = shares ? scaled(split.amount, shares.external) : split.amount;
      } else {
        if (!shares || accountIds!.has(split.account_id) || split.amount === 0) return [];
        bucket = accountBucket(split.account_id);
        amount = scaled(-split.amount, split.amount > 0 ? shares.outflow : shares.inflow);
      }
      if (amount === 0 && split.amount !== 0) return [];
      return buckets.has(bucket) ? [{ key: `${transaction.id}:${index}`, transaction, split, bucket, amount }] : [];
    });
  });
}

const scaled = (amount: number, share: number) => Math.round(amount * share) || 0;

/**
 * The share of each flow of `transaction` taken by the reported accounts.
 *
 * Every account split and the external splits taken together are either
 * sources (money leaving them: debited accounts, income) or sinks (money
 * reaching them: credited accounts, expenses). Each source feeds every sink in
 * proportion to its size, so the reported accounts take `outflow` of each
 * sink, that is how much of the money they send out, and `inflow` of each
 * source. The external splits count by the share of their net amount.
 */
function reportedShares(
  transaction: Transaction,
  accountIds: ReadonlySet<number>,
): { outflow: number; inflow: number; external: number } {
  let sent = 0;
  let received = 0;
  let size = 0;
  let external = 0;
  for (const split of transaction.splits) {
    if (split.type === 'external') {
      external += split.amount;
      continue;
    }
    if (split.amount > 0) size += split.amount;
    if (accountIds.has(split.account_id)) {
      if (split.amount < 0) sent -= split.amount;
      else received += split.amount;
    }
  }
  // An expense is a sink, an income a source, both as big as their net amount.
  if (external < 0) size -= external;
  if (!size) return { outflow: 1, inflow: 1, external: 1 };
  const outflow = sent / size;
  const inflow = received / size;
  return { outflow, inflow, external: external < 0 ? outflow : external > 0 ? inflow : 1 };
}

/** The total of each bucket, in the order of `buckets`, including buckets with no splits. */
export function bucketTotals(splits: readonly ReportSplit[], buckets: readonly Bucket[]): BucketTotal[] {
  const totals = new Map(buckets.map((bucket) => [bucket, 0]));
  for (const { bucket, amount } of splits) {
    const total = totals.get(bucket);
    if (total !== undefined) totals.set(bucket, total + amount);
  }
  return buckets.map((bucket) => ({ bucket, total: totals.get(bucket)! }));
}

const round = (value: number) => Number(value.toFixed(6));

function point(angle: number): string {
  // Clockwise from twelve o'clock.
  return `${round(Math.sin(angle))} ${round(-Math.cos(angle))}`;
}

/**
 * Slices sized by the size of each total, whatever its sign (expenses are
 * negative); buckets totalling zero have no slice.
 */
export function pieSlices(totals: readonly BucketTotal[]): PieSlice[] {
  const sized = totals.filter((t) => t.total !== 0);
  const sum = sized.reduce((acc, t) => acc + Math.abs(t.total), 0);
  let start = 0;
  return sized.map((t) => {
    const fraction = Math.abs(t.total) / sum;
    const end = start + fraction * 2 * Math.PI;
    const path =
      sized.length === 1
        ? 'M 0 -1 A 1 1 0 1 1 0 1 A 1 1 0 1 1 0 -1 Z'
        : `M 0 0 L ${point(start)} A 1 1 0 ${fraction > 0.5 ? 1 : 0} 1 ${point(end)} Z`;
    start = end;
    return { ...t, fraction, path };
  });
}
