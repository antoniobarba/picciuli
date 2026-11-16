import { useMemo, useState } from 'react';
import { unwrap } from '../api/client';
import { useAccounts, useApiMutation, useBalances, useGoalReport, useMoney } from '../api/queries';
import type { Goal, GoalPriority } from '../api/types';
import { DateField } from '../components/DateField';
import { AmountField, FormDialog, SelectField, TextField, type Option } from '../components/forms';
import { todayDay } from '../lib/dates';
import { nonNegativeAmount, optionalDate, positiveAmount, requiredId } from '../lib/forms';
import { canHoldGoals, PRIORITY_LABELS } from '../lib/goals';

const PRIORITY_OPTIONS = (Object.keys(PRIORITY_LABELS) as GoalPriority[]).map((value) => ({
  value,
  label: PRIORITY_LABELS[value],
}));

/** Create or edit a savings goal; `accountId` preselects the account of a new goal. */
export function GoalForm({ goal, accountId, onClose }: { goal: Goal | null; accountId?: number; onClose: () => void }) {
  const money = useMoney();
  const today = todayDay();
  const accounts = useAccounts(true).data;
  const balances = useBalances(today).data;
  const report = useGoalReport(today).data;
  const [name, setName] = useState(goal?.name ?? '');
  const [account, setAccount] = useState<number | null>(goal?.account_id ?? accountId ?? null);
  const [target, setTarget] = useState(goal ? money.plain(goal.target_amount) : '');
  const [saved, setSaved] = useState(goal ? money.plain(goal.saved_amount) : '');
  const [date, setDate] = useState(goal?.target_date ?? '');
  const [priority, setPriority] = useState<GoalPriority>(goal?.priority ?? 'normal');

  // Open cash-like accounts, plus the current account of the goal even if closed.
  const options = useMemo<Option<number>[]>(
    () =>
      (accounts ?? [])
        .filter((a) => canHoldGoals(a.type) && (!a.is_closed || a.id === goal?.account_id))
        .map((a) => ({ value: a.id, label: a.is_closed ? `${a.name} (closed)` : a.name })),
    [accounts, goal?.account_id],
  );

  // What the account's goals would claim beyond its balance after saving.
  let shortfall = 0;
  if (account !== null && balances && report) {
    try {
      const typed = nonNegativeAmount(saved, money, 'saved amount');
      const others = (report.accounts.find((a) => a.account.id === account)?.goals ?? [])
        .filter((p) => p.goal.id !== goal?.id)
        .reduce((total, p) => total + p.goal.saved_amount, 0);
      const balance = balances.find((b) => b.account.id === account)?.balance ?? 0;
      shortfall = Math.max(others + typed - Math.max(balance, 0), 0);
    } catch {
      // The amount is not valid yet: saving will report it.
    }
  }

  const save = useApiMutation(async (api) => {
    const body = {
      account_id: requiredId(account, 'an account'),
      name,
      target_amount: positiveAmount(target, money),
      saved_amount: nonNegativeAmount(saved, money, 'saved amount'),
      target_date: optionalDate(date, today),
      priority,
    };
    if (!goal) return unwrap(api.POST('/api/v1/goals', { body }));
    return unwrap(api.PATCH('/api/v1/goals/{goal_id}', { params: { path: { goal_id: goal.id } }, body }));
  });

  return (
    <FormDialog
      open
      onClose={onClose}
      title={goal ? `Edit ${goal.name}` : 'New savings goal'}
      onSubmit={() => save.mutateAsync(undefined)}
      help="The saved amount is money you set aside by hand: it does not move money, and deposits or withdrawals do not change it."
    >
      <div className="form-row">
        <TextField label="Name" value={name} onChange={setName} placeholder="e.g. Holiday" data-autofocus />
        <SelectField label="Account" value={account} options={options} onChange={setAccount} />
      </div>
      <div className="form-row">
        <AmountField label="Target" value={target} onChange={setTarget} inputMode="decimal" />
        <AmountField label="Saved so far" value={saved} onChange={setSaved} inputMode="decimal" />
      </div>
      <div className="form-row">
        <DateField label="Target date" value={date} onChange={setDate} today={today} placeholder="optional" />
        <SelectField label="Priority" value={priority} options={PRIORITY_OPTIONS} onChange={setPriority} />
      </div>
      {shortfall > 0 ? (
        <p className="form-warning" role="note">
          The goals of this account would claim {money.amount(shortfall)} more than its balance today.
        </p>
      ) : null}
    </FormDialog>
  );
}
