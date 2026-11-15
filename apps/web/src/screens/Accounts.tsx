import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { unwrap } from '../api/client';
import { useAccounts, useApiMutation, useBalances, useMoney, useNetWorth, useOptimisticMove, useValuations } from '../api/queries';
import type { Account } from '../api/types';
import { useConfirm, useNotify } from '../components/feedback';
import { errorMessage } from '../components/forms';
import { DragHandle, useSortable } from '../components/SortableList';
import { Amount, Empty, Loading, PageHeader, ProgressBar, RowMenu } from '../components/ui';
import { shortDate } from '../lib/dates';
import { ACCOUNT_TYPE_LABELS } from '../lib/format';
import { useHotkeys } from '../lib/useHotkeys';
import { AccountForm, CloseAccountForm } from '../forms/AccountForm';

type Dialog = { kind: 'edit'; account: Account | null } | { kind: 'close'; account: Account } | null;

export function Accounts() {
  const money = useMoney();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const notify = useNotify();
  const accounts = useAccounts(true);
  const balances = useBalances().data;
  const valuations = useValuations().data;
  const worth = useNetWorth().data;
  const [dialog, setDialog] = useState<Dialog>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const balance = useMemo(() => new Map((balances ?? []).map((b) => [b.account.id, b.balance])), [balances]);
  const market = useMemo(() => new Map((valuations ?? []).map((v) => [v.account.id, v])), [valuations]);
  const list = useMemo(
    () => [...(accounts.data ?? [])].sort((a, b) => a.position - b.position || a.id - b.id),
    [accounts.data],
  );
  const selected = list.find((a) => a.id === selectedId) ?? null;

  const run = async (action: () => Promise<unknown>) => {
    try {
      await action();
    } catch (error) {
      notify(errorMessage(error), { title: 'Cannot do that', kind: 'error' });
    }
  };

  const remove = useApiMutation((api, id: number) =>
    unwrap(api.DELETE('/api/v1/accounts/{account_id}', { params: { path: { account_id: id } } })),
  );
  const reopen = useApiMutation((api, id: number) =>
    unwrap(api.POST('/api/v1/accounts/{account_id}/reopen', { params: { path: { account_id: id } } })),
  );
  const move = useOptimisticMove<Account>(['accounts', true], (api, { id, position }) =>
    unwrap(
      api.POST('/api/v1/accounts/{account_id}/move', { params: { path: { account_id: id } }, body: { position } }),
    ),
  );

  const deleteAccount = async (account: Account) => {
    if (await confirm({ title: `Delete “${account.name}”?`, message: 'Only accounts without transactions can be deleted.' })) {
      await run(() => remove.mutateAsync(account.id));
    }
  };
  const closeOrReopen = async (account: Account) => {
    if (account.is_closed) {
      if (await confirm({ title: `Reopen “${account.name}”?`, confirmLabel: 'Reopen', danger: false })) {
        await run(() => reopen.mutateAsync(account.id));
      }
    } else {
      setDialog({ kind: 'close', account });
    }
  };
  const moveAccount = (account: Account, index: number) => {
    const target = list[index];
    if (target && target.id !== account.id) {
      void run(() => move.mutateAsync({ id: account.id, position: index + 1 }));
    }
  };
  const sortable = useSortable<Account>({
    getId: (account) => account.id,
    siblingsOf: () => list,
    label: (account) => account.name,
    onMove: moveAccount,
  });
  const step = (account: Account, by: number) => moveAccount(account, list.indexOf(account) + by);

  useHotkeys({
    n: () => setDialog({ kind: 'edit', account: null }),
    e: () => selected && setDialog({ kind: 'edit', account: selected }),
    d: () => selected && void deleteAccount(selected),
    c: () => selected && void closeOrReopen(selected),
    'shift+ArrowUp': () => selected && step(selected, -1),
    'shift+ArrowDown': () => selected && step(selected, 1),
  });

  return (
    <div className="page">
      <PageHeader title="Accounts">
        <button type="button" className="button primary" onClick={() => setDialog({ kind: 'edit', account: null })}>
          + New account
        </button>
      </PageHeader>
      {accounts.isLoading ? (
        <Loading />
      ) : list.length === 0 ? (
        <Empty>No accounts yet. Create your checking account, your cash, your cards…</Empty>
      ) : (
        <div className="card">
          <table className="table rows-clickable">
            <thead>
              <tr>
                <th className="handle-cell" aria-label="Reorder" />
                <th>Name</th>
                <th className="hide-sm">Type</th>
                <th className="num">Balance</th>
                <th className="num hide-sm">Market value</th>
                <th className="num hide-md">Goal</th>
                <th className="hide-md">Progress</th>
                <th className="hide-sm">State</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {list.map((account) => {
                const value = balance.get(account.id) ?? 0;
                const valuation = market.get(account.id);
                const marketValue = account.type === 'investment' ? valuation?.market_value : undefined;
                const progress = account.goal ? (marketValue ?? value) / account.goal : null;
                return (
                  <tr
                    key={account.id}
                    ref={sortable.rowRef(account.id)}
                    className={`${account.is_closed ? 'closed' : ''}${account.id === selectedId ? ' selected' : ''} ${sortable.rowClass(account)}`}
                    tabIndex={0}
                    onFocus={() => setSelectedId(account.id)}
                    onClick={() => navigate(`/accounts/${account.id}`)}
                    onKeyDown={(e) => e.key === 'Enter' && navigate(`/accounts/${account.id}`)}
                  >
                    <td className="handle-cell">
                      <DragHandle {...sortable.handleProps(account)} />
                    </td>
                    <td>
                      <span className="strong">{account.name}</span>
                      <span className="show-sm muted small">{ACCOUNT_TYPE_LABELS[account.type]}</span>
                    </td>
                    <td className="hide-sm">{ACCOUNT_TYPE_LABELS[account.type]}</td>
                    <td className="num">
                      <Amount value={value} money={money} />
                      {marketValue !== undefined ? (
                        <span className="show-sm small">
                          <Amount value={marketValue} money={money} />
                        </span>
                      ) : null}
                    </td>
                    <td className="num hide-sm">
                      {marketValue !== undefined ? <Amount value={marketValue} money={money} /> : ''}
                    </td>
                    <td className="num hide-md">{account.goal != null ? money.amount(account.goal) : ''}</td>
                    <td className="hide-md">
                      {progress !== null ? (
                        <span className="progress-cell">
                          <ProgressBar fraction={progress} />
                          <span className="muted small">{Math.round(progress * 100)}%</span>
                        </span>
                      ) : null}
                    </td>
                    <td className="hide-sm muted">
                      {account.closed_on ? `closed ${shortDate(account.closed_on)}` : 'open'}
                    </td>
                    <td className="actions" onClick={(e) => e.stopPropagation()}>
                      <RowMenu
                        actions={[
                          { label: 'Open register', onSelect: () => navigate(`/accounts/${account.id}`) },
                          { label: 'Edit', onSelect: () => setDialog({ kind: 'edit', account }), shortcut: 'e' },
                          {
                            label: account.is_closed ? 'Reopen' : 'Close',
                            onSelect: () => void closeOrReopen(account),
                            shortcut: 'c',
                          },
                          { label: 'Delete', onSelect: () => void deleteAccount(account), danger: true, shortcut: 'd' },
                        ]}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {sortable.status}
          {worth ? (
            <div className="totals">
              <span>
                Assets <Amount value={worth.assets} money={money} />
              </span>
              <span>
                Liabilities <Amount value={worth.liabilities} money={money} />
              </span>
              <span>
                Net worth <Amount value={worth.net_worth} money={money} bold />
              </span>
            </div>
          ) : null}
        </div>
      )}
      {dialog?.kind === 'edit' ? <AccountForm account={dialog.account} onClose={() => setDialog(null)} /> : null}
      {dialog?.kind === 'close' ? <CloseAccountForm account={dialog.account} onClose={() => setDialog(null)} /> : null}
    </div>
  );
}
