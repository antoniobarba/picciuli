import { useMemo } from 'react';
import { Link, useParams } from 'react-router';
import { unwrap } from '../api/client';
import { useAccounts, useApiMutation, useCategories, useMoney, useRegister, useValuations } from '../api/queries';
import type { Transaction } from '../api/types';
import { useEditors } from '../app/editors';
import { useConfirm, useNotify } from '../components/feedback';
import { errorMessage } from '../components/forms';
import { Amount, Empty, Loading, PageHeader, RowMenu } from '../components/ui';
import { shortDate, todayDay } from '../lib/dates';
import { ACCOUNT_TYPE_LABELS, byId, categoryLabel, transactionTitle, type ById } from '../lib/format';
import type { Account, Category } from '../api/types';
import { quantityText } from '../lib/money';
import { useHotkeys } from '../lib/useHotkeys';

/** What the other side of a transaction is, seen from one account. */
function details(
  transaction: Transaction,
  accountId: number,
  accounts: ById<Account>,
  categories: ById<Category>,
): string {
  const others = transaction.splits.flatMap((split) => {
    if (split.type === 'account') {
      if (split.account_id === accountId) {
        return split.quantity ? [`${quantityText(split.quantity)} shares`] : [];
      }
      return [accounts.get(split.account_id)?.name ?? `#${split.account_id}`];
    }
    return [categoryLabel(split.category_id, categories)];
  });
  return [...new Set(others)].join(', ');
}

export function Register() {
  const { accountId } = useParams();
  const id = Number(accountId);
  const money = useMoney();
  const editors = useEditors();
  const confirm = useConfirm();
  const notify = useNotify();
  const register = useRegister(id);
  const accounts = byId(useAccounts(true).data);
  const categories = byId(useCategories().data);
  const valuation = useValuations().data?.find((v) => v.account.id === id);
  const entries = useMemo(() => [...(register.data?.entries ?? [])].reverse(), [register.data]);
  const account = register.data?.account;

  const remove = useApiMutation((api, transactionId: number) =>
    unwrap(
      api.DELETE('/api/v1/transactions/{transaction_id}', { params: { path: { transaction_id: transactionId } } }),
    ),
  );
  const deleteTransaction = async (transaction: Transaction) => {
    if (await confirm({ title: `Delete “${transactionTitle(transaction)}”?` })) {
      try {
        await remove.mutateAsync(transaction.id);
      } catch (error) {
        notify(errorMessage(error), { title: 'Cannot do that', kind: 'error' });
      }
    }
  };
  const newTransaction = () => {
    if (account?.is_closed) notify('Reopen the account to add transactions.', { kind: 'warning' });
    else editors.newTransaction({ day: todayDay(), accountId: id });
  };

  useHotkeys({ n: newTransaction });

  if (register.isLoading) return <Loading />;
  if (!account) return <Empty>This account does not exist.</Empty>;

  return (
    <div className="page">
      <PageHeader
        title={
          <>
            <Link to="/accounts" className="back-link" aria-label="Back to accounts">
              ‹
            </Link>
            {account.name}
            <small className="muted"> {ACCOUNT_TYPE_LABELS[account.type]}{account.is_closed ? ' · closed' : ''}</small>
          </>
        }
      >
        <button type="button" className="button primary" onClick={newTransaction} disabled={account.is_closed}>
          + New transaction
        </button>
      </PageHeader>
      <div className="totals card">
        <span>
          Starting <Amount value={register.data!.starting_balance} money={money} />
        </span>
        <span>
          Balance <Amount value={register.data!.ending_balance} money={money} bold />
        </span>
        {valuation && account.type === 'investment' ? (
          <span>
            Market value <Amount value={valuation.market_value} money={money} bold />
          </span>
        ) : null}
      </div>
      {entries.length === 0 ? (
        <Empty>No transactions yet.</Empty>
      ) : (
        <div className="card">
          <table className="table rows-clickable">
            <thead>
              <tr>
                <th>Date</th>
                <th>Description</th>
                <th className="hide-sm">Details</th>
                <th className="num">Amount</th>
                <th className="num hide-sm">Balance</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr
                  key={entry.transaction.id}
                  tabIndex={0}
                  onClick={() => editors.editTransaction(entry.transaction)}
                  onKeyDown={(e) => e.key === 'Enter' && editors.editTransaction(entry.transaction)}
                >
                  <td className="nowrap">{shortDate(entry.transaction.date)}</td>
                  <td>
                    {transactionTitle(entry.transaction)}
                    <span className="show-sm muted small">
                      {details(entry.transaction, id, accounts, categories)}
                    </span>
                  </td>
                  <td className="hide-sm muted">{details(entry.transaction, id, accounts, categories)}</td>
                  <td className="num">
                    <Amount value={entry.amount} money={money} plus />
                    <span className="show-sm muted small">{money.amount(entry.balance)}</span>
                  </td>
                  <td className="num hide-sm">
                    <Amount value={entry.balance} money={money} />
                  </td>
                  <td className="actions" onClick={(e) => e.stopPropagation()}>
                    <RowMenu
                      actions={[
                        { label: 'Edit', onSelect: () => editors.editTransaction(entry.transaction) },
                        { label: 'Delete', onSelect: () => void deleteTransaction(entry.transaction), danger: true },
                      ]}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
