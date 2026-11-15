import { useState } from 'react';
import { useAccounts, useCategories, useMoney } from '../api/queries';
import type { Transaction } from '../api/types';
import { shortDate } from '../lib/dates';
import { byId, categoryLabel, transactionAccounts, transactionTitle } from '../lib/format';
import { TextField } from './forms';

const PAGE_SIZE = 25;

/** Search before paging; the source order, amounts and running balances stay intact. */
export function useTransactionList<T>(
  items: readonly T[],
  scope: string,
  transactionOf: (item: T) => Transaction,
) {
  const accounts = byId(useAccounts(true).data);
  const categories = byId(useCategories().data);
  const money = useMoney();
  const [state, setState] = useState({ scope, search: '', page: 0 });
  const current = state.scope === scope ? state : { scope, search: '', page: 0 };
  const terms = current.search.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const matches = terms.length ? items.filter((item) => {
    const transaction = transactionOf(item);
    const text = [
      transactionTitle(transaction), transaction.notes, transaction.kind,
      transaction.date, shortDate(transaction.date),
      transactionAccounts(transaction, accounts), money.amount(transaction.net_amount),
      ...transaction.splits.map((split) => [
        money.amount(split.amount),
        split.type === 'external' ? categoryLabel(split.category_id, categories) : '',
      ].join(' ')),
    ].join(' ').toLocaleLowerCase();
    return terms.every((term) => text.includes(term));
  }) : items;
  const pages = Math.max(1, Math.ceil(matches.length / PAGE_SIZE));
  const page = Math.min(current.page, pages - 1);
  if (state.scope !== scope || state.page !== page) setState({ ...current, page });
  return {
    items: matches.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    search: current.search,
    setSearch: (search: string) => setState({ scope, search, page: 0 }),
    page,
    pages,
    count: matches.length,
    total: items.length,
    setPage: (next: number) => setState({ ...current, page: Math.max(0, Math.min(next, pages - 1)) }),
  };
}

export function TransactionListControls({
  list,
}: {
  list: Omit<ReturnType<typeof useTransactionList>, 'items'>;
}) {
  return (
    <div className="transaction-controls">
      <TextField label="Search transactions" type="search" value={list.search} onChange={list.setSearch} />
      <nav className="transaction-paging" aria-label="Transaction pages">
        <span className="muted small" role="status">
          {list.count === 0 ? 0 : list.page * PAGE_SIZE + 1}
          {' - '}{Math.min((list.page + 1) * PAGE_SIZE, list.count)} of {list.count}
          {list.count !== list.total ? ` (${list.total} total)` : ''}
        </span>
        <button type="button" className="button small" disabled={list.page === 0} onClick={() => list.setPage(list.page - 1)}>
          Previous
        </button>
        <span className="small">Page {list.page + 1} of {list.pages}</span>
        <button type="button" className="button small" disabled={list.page + 1 >= list.pages} onClick={() => list.setPage(list.page + 1)}>
          Next
        </button>
      </nav>
    </div>
  );
}
