import { useState } from 'react';
import { unwrap } from '../api/client';
import { useApiMutation, useMoney } from '../api/queries';
import type { Account, AccountType } from '../api/types';
import { DateField } from '../components/DateField';
import { AmountField, FormDialog, SelectField, TextField } from '../components/forms';
import { todayDay } from '../lib/dates';
import { ACCOUNT_TYPE_LABELS } from '../lib/format';
import { optionalAmount, optionalDate, optionalText } from '../lib/forms';
import { NotesField } from './TransactionForm';

const TYPE_OPTIONS = (Object.keys(ACCOUNT_TYPE_LABELS) as AccountType[]).map((value) => ({
  value,
  label: ACCOUNT_TYPE_LABELS[value],
}));

export function AccountForm({ account, onClose }: { account: Account | null; onClose: () => void }) {
  const money = useMoney();
  const today = todayDay();
  const [name, setName] = useState(account?.name ?? '');
  const [type, setType] = useState<AccountType>(account?.type ?? 'checking');
  const [opening, setOpening] = useState(account ? money.plain(account.opening_balance) : '');
  const [openingDate, setOpeningDate] = useState(account?.opening_date ?? '');
  const [goal, setGoal] = useState(account?.goal != null ? money.plain(account.goal) : '');
  const [notes, setNotes] = useState(account?.notes ?? '');

  const save = useApiMutation(async (api) => {
    const openingBalance = optionalAmount(opening, money) ?? 0;
    const date = optionalDate(openingDate, today);
    const common = {
      name,
      type,
      goal: optionalAmount(goal, money),
      notes: optionalText(notes),
    };
    if (!account) {
      return unwrap(
        api.POST('/api/v1/accounts', { body: { ...common, opening_balance: openingBalance, opening_date: date } }),
      );
    }
    // Opening values are only sent when they changed, so that other properties
    // of a closed account can still be edited.
    const body: Record<string, unknown> = { ...common };
    if (openingBalance !== account.opening_balance) body.opening_balance = openingBalance;
    if (date !== account.opening_date) body.opening_date = date;
    return unwrap(
      api.PATCH('/api/v1/accounts/{account_id}', { params: { path: { account_id: account.id } }, body }),
    );
  });

  return (
    <FormDialog
      open
      onClose={onClose}
      title={account ? `Edit ${account.name}` : 'New account'}
      onSubmit={() => save.mutateAsync(undefined)}
      help="Liabilities (cards, loans, mortgages) have negative balances while you owe money: enter a mortgage of 150,000 as -150000."
    >
      <TextField label="Name" value={name} onChange={setName} data-autofocus />
      <SelectField label="Type" value={type} options={TYPE_OPTIONS} onChange={setType} />
      <div className="form-row">
        <AmountField label="Opening balance" value={opening} onChange={setOpening} />
        <DateField label="Opening date" value={openingDate} onChange={setOpeningDate} today={today} placeholder="optional" />
      </div>
      <AmountField label="Goal" value={goal} onChange={setGoal} placeholder="optional target balance" />
      <NotesField value={notes} onChange={setNotes} />
    </FormDialog>
  );
}

export function CloseAccountForm({ account, onClose }: { account: Account; onClose: () => void }) {
  const today = todayDay();
  const [on, setOn] = useState(today);
  const close = useApiMutation((api) =>
    unwrap(
      api.POST('/api/v1/accounts/{account_id}/close', {
        params: { path: { account_id: account.id } },
        body: { on: optionalDate(on, today) },
      }),
    ),
  );
  return (
    <FormDialog
      open
      onClose={onClose}
      title={`Close ${account.name}`}
      saveLabel="Close account"
      onSubmit={() => close.mutateAsync(undefined)}
      help="The balance must be zero. A closed account keeps its history."
    >
      <DateField label="Closing date" value={on} onChange={setOn} today={today} autoFocus />
    </FormDialog>
  );
}
