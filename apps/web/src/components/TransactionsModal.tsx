import { useMemo } from 'react';
import {
  useAccounts,
  useBudgetReport,
  useCategories,
  useMoney,
  usePeriodsOn,
  useTransactions,
  type TransactionFilter,
} from '../api/queries';
import type { BudgetLine, Category, Period, Transaction } from '../api/types';
import { useEditors } from '../app/editors';
import { choosePeriod } from '../lib/calendar';
import { shortDate, todayDay } from '../lib/dates';
import {
  byId,
  periodRange,
  transactionAccounts,
  transactionCategory,
  transactionTitle,
  transferAmount,
} from '../lib/format';
import { Modal } from './Modal';
import { Amount, Empty, Loading } from './ui';
import { TransactionListControls, useTransactionList } from './TransactionListControls';

export interface Remaining {
  label: string;
  /** `null` when no budget applies. */
  value: number | null;
}

/** Sum of the external splits of a transaction in some categories. */
export function amountIn(transaction: Transaction, categoryIds: ReadonlySet<number>): number {
  return transaction.splits
    .filter((s) => s.type === 'external' && s.category_id != null && categoryIds.has(s.category_id))
    .reduce((sum, s) => sum + s.amount, 0);
}

/** A category with its subcategories: a top-level category covers them, as its budget does. */
function categorySet(category: Category, categories: readonly Category[] | undefined): Set<number> {
  const ids = new Set([category.id]);
  if (category.parent_id === null) {
    for (const c of categories ?? []) if (c.parent_id === category.id) ids.add(c.id);
  }
  return ids;
}

/**
 * The transactions of an item (category, period or budget), their total and
 * what is left of its budget. A transaction opens in the editor.
 */
export function TransactionsModal({
  title,
  description,
  filter,
  amountOf,
  remaining,
  onClose,
}: {
  title: string;
  description?: string;
  filter: TransactionFilter;
  /** How much of a transaction belongs to the item; the net amount by default. */
  amountOf?: (transaction: Transaction) => number;
  remaining: Remaining;
  onClose: () => void;
}) {
  const money = useMoney();
  const editors = useEditors();
  const accounts = useAccounts(true);
  const categories = useCategories();
  const transactions = useTransactions({ ...filter, newest_first: true });
  const accountMap = useMemo(() => byId(accounts.data), [accounts.data]);
  const categoryMap = useMemo(() => byId(categories.data), [categories.data]);
  const list = transactions.data ?? [];
  const paged = useTransactionList(list, JSON.stringify(filter), (transaction) => transaction);
  const valueOf = (transaction: Transaction) => (amountOf ? amountOf(transaction) : transaction.net_amount);
  const total = list.reduce((sum, transaction) => sum + valueOf(transaction), 0);

  return (
    <Modal open onClose={onClose} title={title} description={description} wide>
      <TransactionListControls list={paged} />
      <div className="item-transactions">
        {transactions.isLoading ? (
          <Loading />
        ) : paged.items.length === 0 ? (
          <Empty>{list.length === 0 ? 'No transactions.' : 'No matching transactions.'}</Empty>
        ) : (
          <ul className="transaction-list" aria-label="Transactions">
            {paged.items.map((transaction) => (
              <li key={transaction.id}>
                <button
                  type="button"
                  className="transaction-row"
                  onClick={() => {
                    onClose();
                    editors.editTransaction(transaction);
                  }}
                >
                  <span className="transaction-main">
                    <span className="transaction-title">{transactionTitle(transaction)}</span>
                    <span className="transaction-sub">
                      {shortDate(transaction.date)} · {transactionAccounts(transaction, accountMap)} ·{' '}
                      {transactionCategory(transaction, categoryMap)}
                    </span>
                  </span>
                  {transaction.kind === 'transfer' ? (
                    <Amount value={transferAmount(transaction)} money={money} muted />
                  ) : (
                    <Amount value={valueOf(transaction)} money={money} />
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="totals">
        <span>
          {list.length} transaction{list.length === 1 ? '' : 's'}
        </span>
        <span>
          Total <Amount value={total} money={money} bold />
        </span>
        <span>
          {remaining.label}{' '}
          {remaining.value === null ? <strong>—</strong> : <Amount value={remaining.value} money={money} bold />}
        </span>
      </div>
    </Modal>
  );
}

/**
 * Every transaction of a category, including its subcategories for a
 * top-level one, with what is left of its budget in the period covering today.
 */
export function CategoryTransactions({ category, onClose }: { category: Category; onClose: () => void }) {
  const categories = useCategories();
  const ids = useMemo(() => categorySet(category, categories.data), [category, categories.data]);
  const period = choosePeriod(usePeriodsOn(todayDay()).data ?? [], null);
  const report = useBudgetReport(period?.id ?? null).data;
  const line = report?.period.id === period?.id ? report?.lines.find((l) => l.category.id === category.id) : undefined;
  const parent = category.parent_id === null;
  return (
    <TransactionsModal
      title={category.name}
      description={parent ? 'Transactions of the category and its subcategories.' : 'Transactions of the category.'}
      filter={{ category_id: category.id, include_subcategories: parent }}
      amountOf={(transaction) => amountIn(transaction, ids)}
      remaining={{ label: period ? `Remaining in ${period.name}` : 'Remaining', value: line ? line.remaining : null }}
      onClose={onClose}
    />
  );
}

/** The transactions dated within a period, with what is left of all its budgets. */
export function PeriodTransactions({ period, onClose }: { period: Period; onClose: () => void }) {
  const report = useBudgetReport(period.id).data;
  const current = report?.period.id === period.id ? report : undefined;
  return (
    <TransactionsModal
      title={period.name}
      description={periodRange(period)}
      filter={{ start: period.start, ...(period.end ? { end: period.end } : {}) }}
      remaining={{ label: 'Budget remaining', value: current?.lines.length ? current.total_remaining : null }}
      onClose={onClose}
    />
  );
}

/** The transactions of a budget's category (and subcategories) within its period. */
export function BudgetTransactions({ line, period, onClose }: { line: BudgetLine; period: Period; onClose: () => void }) {
  const money = useMoney();
  const categories = useCategories();
  const ids = useMemo(() => categorySet(line.category, categories.data), [line.category, categories.data]);
  const parent = line.category.parent_id === null;
  return (
    <TransactionsModal
      title={`${line.category.name} · ${period.name}`}
      description={`Budget ${money.amount(line.budget.amount)} · ${periodRange(period)}`}
      filter={{
        category_id: line.category.id,
        include_subcategories: parent,
        start: period.start,
        ...(period.end ? { end: period.end } : {}),
      }}
      amountOf={(transaction) => amountIn(transaction, ids)}
      remaining={{ label: 'Remaining', value: line.remaining }}
      onClose={onClose}
    />
  );
}
