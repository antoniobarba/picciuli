import { useMemo, useState } from 'react';
import { unwrap } from '../api/client';
import { useAccounts, useApiMutation, useCategories, useMoney, useSchedules } from '../api/queries';
import type { Schedule } from '../api/types';
import { useEditors } from '../app/editors';
import { useConfirm, useNotify } from '../components/feedback';
import { errorMessage } from '../components/forms';
import { icons } from '../components/icons';
import { ScheduleAmount } from '../components/RecurringPanel';
import { Empty, Loading, onEnter, PageHeader, RowMenu } from '../components/ui';
import { shortDate, todayDay } from '../lib/dates';
import { byId, transactionAccounts, transactionCategory } from '../lib/format';
import { ruleText, scheduleStatus, templateTransaction } from '../lib/schedules';
import { useHotkeys } from '../lib/useHotkeys';

const STATUS_LABELS = { paused: 'Paused', finished: 'Finished', failed: 'Needs attention' } as const;

export function Recurring() {
  const schedules = useSchedules();
  const accounts = useAccounts(true);
  const categories = useCategories();
  const money = useMoney();
  const editors = useEditors();
  const confirm = useConfirm();
  const notify = useNotify();
  const today = todayDay();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const list = schedules.data ?? [];
  const selected = list.find((s) => s.id === selectedId) ?? null;
  const accountMap = useMemo(() => byId(accounts.data), [accounts.data]);
  const categoryMap = useMemo(() => byId(categories.data), [categories.data]);

  const setPaused = useApiMutation((api, { id, paused }: { id: number; paused: boolean }) =>
    unwrap(api.PATCH('/api/v1/schedules/{schedule_id}', { params: { path: { schedule_id: id } }, body: { paused } })),
  );
  const skip = useApiMutation((api, id: number) =>
    unwrap(api.POST('/api/v1/schedules/{schedule_id}/skip', { params: { path: { schedule_id: id } } })),
  );
  const remove = useApiMutation((api, id: number) =>
    unwrap(api.DELETE('/api/v1/schedules/{schedule_id}', { params: { path: { schedule_id: id } } })),
  );

  const run = async (action: () => Promise<unknown>) => {
    try {
      await action();
    } catch (error) {
      notify(errorMessage(error), { title: 'Cannot do that', kind: 'error' });
    }
  };

  const deleteSchedule = async (schedule: Schedule) => {
    const ok = await confirm({
      title: `Delete “${schedule.description || 'recurring transaction'}”?`,
      message: 'The transactions it already recorded are kept.',
    });
    if (ok) await run(() => remove.mutateAsync(schedule.id));
  };

  const newSchedule = () => {
    if (accounts.data && !accounts.data.some((account) => !account.is_closed)) {
      notify('Create an account first: open Accounts, then New.', { title: 'No accounts', kind: 'warning' });
      return;
    }
    editors.newSchedule();
  };

  useHotkeys({
    n: newSchedule,
    e: () => selected && editors.editSchedule(selected),
    d: () => selected && void deleteSchedule(selected),
  });

  return (
    <div className="page">
      <PageHeader title="Recurring">
        <button type="button" className="button primary" onClick={newSchedule}>
          + New recurring
        </button>
      </PageHeader>
      {schedules.isLoading ? (
        <Loading />
      ) : list.length === 0 ? (
        <Empty>
          <p>
            No recurring transactions yet. Enter your salary, rent, subscriptions, loan payments or monthly savings
            once: Picciuli adds them every time they are due, or reminds you to confirm bills whose amount changes.
          </p>
          <button type="button" className="button primary" onClick={newSchedule}>
            + New recurring transaction
          </button>
        </Empty>
      ) : (
        <div className="card">
          <table className="table rows-clickable">
            <thead>
              <tr>
                <th>Description</th>
                <th className="hide-sm">Repeats</th>
                <th>Next</th>
                <th className="num">Amount</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {list.map((schedule) => {
                const template = templateTransaction(schedule, schedule.next_date ?? today);
                const status = scheduleStatus(schedule);
                const open = () => editors.editSchedule(schedule);
                return (
                  <tr
                    key={schedule.id}
                    tabIndex={0}
                    className={`${schedule.id === selectedId ? 'selected' : ''}${status === 'finished' ? ' closed' : ''}`}
                    onFocus={() => setSelectedId(schedule.id)}
                    onClick={open}
                    onKeyDown={onEnter(open)}
                  >
                    <td>
                      <div className="strong">{schedule.description || `(${schedule.kind})`}</div>
                      <div className="muted small">
                        {schedule.debt && schedule.debt.kind !== 'loan_payment'
                          ? `Proposed by the terms of ${accountMap.get(schedule.debt.account_id)?.name ?? 'the card'}`
                          : `${transactionAccounts(template, accountMap)} · ${transactionCategory(template, categoryMap)}`}
                        {schedule.debt?.kind === 'loan_payment' ? ' · principal and interest' : ''}
                      </div>
                    </td>
                    <td className="hide-sm">
                      {ruleText(schedule)}
                      {schedule.mode === 'confirm' ? <div className="muted small">Confirmed by you</div> : null}
                    </td>
                    <td className="nowrap">
                      {schedule.next_date ? shortDate(schedule.next_date) : '—'}
                      {status ? (
                        <div>
                          <span
                            className={`status-pill ${status}`}
                            title={status === 'failed' ? (schedule.last_error ?? undefined) : undefined}
                          >
                            {STATUS_LABELS[status]}
                          </span>
                        </div>
                      ) : null}
                    </td>
                    <td className="num">
                      <ScheduleAmount schedule={schedule} money={money} />
                    </td>
                    <td className="actions" onClick={(e) => e.stopPropagation()}>
                      <RowMenu
                        actions={[
                          { label: 'Edit', onSelect: open, shortcut: 'e' },
                          !schedule.is_finished && {
                            label: 'Record the next one…',
                            onSelect: () => editors.confirmOccurrence(schedule),
                          },
                          !schedule.is_finished && {
                            label: 'Skip the next one',
                            onSelect: () => void run(() => skip.mutateAsync(schedule.id)),
                          },
                          !schedule.is_finished && {
                            label: schedule.paused ? 'Resume' : 'Pause',
                            onSelect: () =>
                              void run(() => setPaused.mutateAsync({ id: schedule.id, paused: !schedule.paused })),
                          },
                          { label: 'Delete', onSelect: () => void deleteSchedule(schedule), danger: true, shortcut: 'd' },
                        ]}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small card-note">
        {icons.recurring} Recurring transactions are added when you open Picciuli on or after their day, each on its
        own date. Paused ones wait until you resume them.
      </p>
    </div>
  );
}
