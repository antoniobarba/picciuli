import { useMemo, useState } from 'react';
import { unwrap } from '../api/client';
import { useAccounts, useApiMutation, useMoney } from '../api/queries';
import type { Schedule, ScheduleCreate, ScheduleFrequency, ScheduleMode, Transaction } from '../api/types';
import { DateField } from '../components/DateField';
import { useConfirm } from '../components/feedback';
import { FormDialog, SelectField, TextField, type Option } from '../components/forms';
import { todayDay, type Day } from '../lib/dates';
import { isLoan } from '../lib/debts';
import type { TransactionDraft } from '../lib/forms';
import {
  emptyScheduleDraft,
  FREQUENCY_LABELS,
  MODE_LABELS,
  scheduleBody,
  scheduleDraftFromSchedule,
  scheduleDraftFromTransaction,
  type EndKind,
  type ScheduleDraft,
} from '../lib/schedules';
import { TransactionFields, useSelectedAccount } from './TransactionForm';

const FREQUENCY_OPTIONS: Option<ScheduleFrequency>[] = (Object.keys(FREQUENCY_LABELS) as ScheduleFrequency[]).map(
  (value) => ({ value, label: FREQUENCY_LABELS[value] }),
);
const MODE_OPTIONS: Option<ScheduleMode>[] = (Object.keys(MODE_LABELS) as ScheduleMode[]).map((value) => ({
  value,
  label: MODE_LABELS[value],
}));
const END_OPTIONS: Option<EndKind>[] = [
  { value: 'never', label: 'Never' },
  { value: 'date', label: 'On a date' },
  { value: 'count', label: 'After a number of times' },
];

export interface ScheduleFormProps {
  onClose: () => void;
  /** Edit this schedule. */
  schedule?: Schedule | null;
  /** Repeat this transaction. */
  from?: Transaction | null;
  /** First occurrence of a new schedule. */
  day?: Day;
}

/** Create or edit a recurring transaction: what it records, and when. */
export function ScheduleForm({ onClose, schedule, from, day }: ScheduleFormProps) {
  const money = useMoney();
  const confirm = useConfirm();
  const today = todayDay();
  const [draft, setDraft] = useState<ScheduleDraft>(() => {
    if (schedule) return scheduleDraftFromSchedule(schedule, money, today);
    if (from) return scheduleDraftFromTransaction(from, money);
    return emptyScheduleDraft(day ?? today);
  });
  const update = (changes: Partial<ScheduleDraft>) => setDraft((current) => ({ ...current, ...changes }));
  const updateTransaction = (changes: Partial<TransactionDraft>) =>
    setDraft((current) => ({ ...current, transaction: { ...current.transaction, ...changes } }));
  const selectedAccount = useSelectedAccount(draft.transaction);
  const accounts = useAccounts(true).data ?? [];
  const target = draft.transaction.kind === 'transfer' ? draft.transaction.toAccountId : null;
  const loanAccount = accounts.find((a) => a.id === target && isLoan(a.type)) ?? null;
  const [loanChoice, setLoanChoice] = useState<boolean | null>(
    schedule ? schedule.debt?.kind === 'loan_payment' : null,
  );
  // Payments into a loan with terms are split into principal and interest unless unticked.
  const loanPayment = loanAccount !== null && (loanChoice ?? loanAccount.debt_terms != null);

  const used = useMemo(() => {
    const ids = new Set<number>();
    for (const split of schedule?.splits ?? from?.splits ?? []) if (split.type === 'account') ids.add(split.account_id);
    return ids;
  }, [schedule, from]);

  const save = useApiMutation(async (api, current: ScheduleDraft) => {
    const body: ScheduleCreate = scheduleBody(current, money, today);
    const linked = schedule?.debt?.kind === 'loan_payment' ? schedule.debt : null;
    if (loanPayment && loanAccount) {
      // An unchanged link keeps its interest category.
      if (linked?.account_id !== loanAccount.id) {
        body.debt = { kind: 'loan_payment', account_id: loanAccount.id, interest_category_id: null };
      }
    } else if (schedule?.debt) {
      body.debt = null;
    }
    if (schedule) {
      const { start, ...changes } = body;
      return unwrap(
        api.PATCH('/api/v1/schedules/{schedule_id}', {
          params: { path: { schedule_id: schedule.id } },
          body: { ...changes, next_date: start },
        }),
      );
    }
    return unwrap(api.POST('/api/v1/schedules', { body }));
  });
  const remove = useApiMutation((api, id: number) =>
    unwrap(api.DELETE('/api/v1/schedules/{schedule_id}', { params: { path: { schedule_id: id } } })),
  );

  const monthly = draft.frequency === 'monthly' || draft.frequency === 'yearly';
  const submit = () =>
    save.mutateAsync({ ...draft, transaction: { ...draft.transaction, accountId: selectedAccount } });

  const deleteButton = schedule ? (
    <button
      type="button"
      className="button danger-text"
      onClick={async () => {
        const ok = await confirm({
          title: `Delete “${schedule.description || 'recurring transaction'}”?`,
          message: 'The transactions it already recorded are kept.',
        });
        if (ok) {
          await remove.mutateAsync(schedule.id);
          onClose();
        }
      }}
    >
      Delete
    </button>
  ) : null;

  return (
    <FormDialog
      open
      onClose={onClose}
      title={schedule ? 'Edit recurring transaction' : 'New recurring transaction'}
      onSubmit={submit}
      wide
      secondary={deleteButton}
      help="Recurring transactions are added when you open Picciuli on or after their day. Choose “Remind me” for bills whose amount changes: you confirm each one and can adjust it."
    >
      <TransactionFields
        draft={draft.transaction}
        update={updateTransaction}
        usedAccounts={used}
        dateLabel={schedule ? 'Next date' : 'First date'}
      />
      {loanAccount ? (
        <label className="switch">
          <input type="checkbox" checked={loanPayment} onChange={(e) => setLoanChoice(e.target.checked)} />
          Loan payment: split it into principal and interest each time
        </label>
      ) : null}
      <fieldset className="schedule-rule">
        <legend>Repeat</legend>
        <div className="form-row">
          <TextField
            label="Every"
            value={draft.every}
            onChange={(every) => update({ every })}
            inputMode="numeric"
          />
          <SelectField
            label="Unit"
            value={draft.frequency}
            options={FREQUENCY_OPTIONS}
            onChange={(frequency) => update({ frequency })}
          />
        </div>
        {monthly ? (
          <label className="switch">
            <input type="checkbox" checked={draft.lastDay} onChange={(e) => update({ lastDay: e.target.checked })} />
            On the last day of the month
          </label>
        ) : null}
        <div className="form-row">
          <SelectField
            label="Ends"
            value={draft.endKind}
            options={END_OPTIONS}
            onChange={(endKind) => update({ endKind })}
          />
          {draft.endKind === 'date' ? (
            <DateField label="End date" value={draft.end} onChange={(end) => update({ end })} today={today} />
          ) : draft.endKind === 'count' ? (
            <TextField
              label={schedule ? 'Times left' : 'Times'}
              value={draft.count}
              onChange={(count) => update({ count })}
              inputMode="numeric"
            />
          ) : null}
        </div>
        <SelectField label="When it is due" value={draft.mode} options={MODE_OPTIONS} onChange={(mode) => update({ mode })} />
      </fieldset>
    </FormDialog>
  );
}
