import { useMemo, useState } from 'react';
import { unwrap } from '../api/client';
import { useAccounts, useApiMutation, useCategories, useMoney } from '../api/queries';
import type { Account, AccountType, DebtTermsIn } from '../api/types';
import { DateField } from '../components/DateField';
import { useConfirm } from '../components/feedback';
import { AmountField, FormDialog, SelectField, TextField, type Option } from '../components/forms';
import { todayDay } from '../lib/dates';
import {
  balanceFromOwed,
  emptyTermsDraft,
  interestCategoryName,
  isCard,
  isLiability,
  NEW_CATEGORY,
  owedText,
  termsBody,
  termsDraftFromAccount,
  type TermsDraft,
} from '../lib/debts';
import { ACCOUNT_TYPE_LABELS } from '../lib/format';
import { NONE_ID, optionalAmount, optionalDate, optionalText } from '../lib/forms';
import type { MoneyFormat } from '../lib/money';
import { categoryOptions, NotesField } from './TransactionForm';

const TYPE_OPTIONS = (Object.keys(ACCOUNT_TYPE_LABELS) as AccountType[]).map((value) => ({
  value,
  label: ACCOUNT_TYPE_LABELS[value],
}));

export function AccountForm({ account, onClose }: { account: Account | null; onClose: () => void }) {
  const money = useMoney();
  const confirm = useConfirm();
  const today = todayDay();
  const [name, setName] = useState(account?.name ?? '');
  const [type, setType] = useState<AccountType>(account?.type ?? 'checking');
  const liability = isLiability(type);
  const [opening, setOpening] = useState(() => {
    if (!account) return '';
    return isLiability(account.type) ? owedText(account.opening_balance, money) : money.plain(account.opening_balance);
  });
  const [openingDate, setOpeningDate] = useState(account?.opening_date ?? '');
  const [goal, setGoal] = useState(account?.goal != null ? money.plain(account.goal) : '');
  const [notes, setNotes] = useState(account?.notes ?? '');
  const [terms, setTerms] = useState<TermsDraft>(() =>
    account ? termsDraftFromAccount(account, money) : emptyTermsDraft(),
  );
  const updateTerms = (changes: Partial<TermsDraft>) => setTerms((current) => ({ ...current, ...changes }));

  const changeType = (next: AccountType) => {
    // The typed amount keeps its meaning: what you have, or what you owe.
    if (isLiability(next) !== liability && opening.trim()) {
      try {
        setOpening(money.plain(-money.parse(opening)));
      } catch {
        // Leave text that is not a number for the user to fix.
      }
    }
    setType(next);
  };

  const save = useApiMutation(async (api) => {
    const typed = optionalAmount(opening, money) ?? 0;
    const openingBalance = liability ? balanceFromOwed(typed) : typed;
    const date = optionalDate(openingDate, today);
    const debtTerms: DebtTermsIn | null = termsBody(
      { ...terms, newCategory: terms.newCategory.trim() || interestCategoryName(name) },
      type,
      money,
    );
    const common: Record<string, unknown> = {
      name,
      type,
      goal: liability ? (account?.goal ?? null) : optionalAmount(goal, money),
      notes: optionalText(notes),
    };
    if (!account) {
      return unwrap(
        api.POST('/api/v1/accounts', {
          body: {
            name,
            type,
            goal: common.goal as number | null,
            notes: common.notes as string | null,
            opening_balance: openingBalance,
            opening_date: date,
            ...(debtTerms ? { debt_terms: debtTerms } : {}),
          },
        }),
      );
    }
    if (account.debt_terms && !liability) {
      const ok = await confirm({
        title: `Make “${account.name}” an asset?`,
        message: 'Its interest rate, payments and proposed card charges will be removed.',
        confirmLabel: 'Change type',
      });
      if (!ok) throw new Error('The account was not changed.');
    }
    // Opening values are only sent when they changed, so that other properties
    // of a closed account can still be edited.
    const body: Record<string, unknown> = { ...common };
    if (openingBalance !== account.opening_balance) body.opening_balance = openingBalance;
    if (date !== account.opening_date) body.opening_date = date;
    if (liability && (debtTerms || account.debt_terms)) body.debt_terms = debtTerms;
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
      wide={liability && terms.enabled}
      help={
        liability
          ? 'Enter what you owe as a positive amount. With the interest rate and the payments, Picciuli splits loan payments into principal and interest, forecasts the payoff and plans it on the Debts screen.'
          : undefined
      }
    >
      <div className="form-row">
        <TextField label="Name" value={name} onChange={setName} data-autofocus />
        <SelectField label="Type" value={type} options={TYPE_OPTIONS} onChange={changeType} />
      </div>
      <div className="form-row">
        <AmountField
          label={liability ? 'How much do you owe?' : 'Opening balance'}
          value={opening}
          onChange={setOpening}
          hint={liability ? 'At the opening date, as a positive amount.' : undefined}
        />
        <DateField label="Opening date" value={openingDate} onChange={setOpeningDate} today={today} placeholder="optional" />
      </div>
      {liability ? (
        <DebtTermsFields
          type={type}
          accountId={account?.id ?? null}
          accountName={name}
          draft={terms}
          update={updateTerms}
          money={money}
        />
      ) : (
        <AmountField label="Goal" value={goal} onChange={setGoal} placeholder="optional target balance" />
      )}
      {account?.debt_terms && !liability ? (
        <p className="form-warning" role="note">
          An asset has no debt terms: saving removes the interest rate and payments of this account.
        </p>
      ) : null}
      <NotesField value={notes} onChange={setNotes} />
    </FormDialog>
  );
}

function DebtTermsFields({
  type,
  accountId,
  accountName,
  draft,
  update,
  money,
}: {
  type: AccountType;
  accountId: number | null;
  accountName: string;
  draft: TermsDraft;
  update: (changes: Partial<TermsDraft>) => void;
  money: MoneyFormat;
}) {
  const accountList = useAccounts(false).data;
  const categoryList = useCategories().data;
  const card = isCard(type);
  const suggested = interestCategoryName(accountName);
  const payers = useMemo<Option<number>[]>(
    () => [
      { value: NONE_ID, label: 'None' },
      ...(accountList ?? [])
        .filter((a) => a.id !== accountId && !isLiability(a.type))
        .map((a) => ({ value: a.id, label: a.name })),
    ],
    [accountList, accountId],
  );
  const categoryChoices = useMemo<Option<number>[]>(
    () => [
      { value: NEW_CATEGORY, label: 'New category…' },
      ...categoryOptions(categoryList ?? []),
    ],
    [categoryList],
  );

  return (
    <fieldset className="debt-terms">
      <legend>Interest and payments</legend>
      <label className="switch">
        <input type="checkbox" checked={draft.enabled} onChange={(e) => update({ enabled: e.target.checked })} />
        Track the interest rate and the payments
      </label>
      {draft.enabled ? (
        <>
          <div className="form-row">
            <TextField
              label="Interest rate (% a year)"
              value={draft.rate}
              onChange={(rate) => update({ rate })}
              inputMode="decimal"
              placeholder="e.g. 19.9"
            />
            <TextField
              label="Due day"
              value={draft.dueDay}
              onChange={(dueDay) => update({ dueDay })}
              inputMode="numeric"
              placeholder="1–31"
            />
            {card ? (
              <TextField
                label="Statement day"
                value={draft.statementDay}
                onChange={(statementDay) => update({ statementDay })}
                inputMode="numeric"
                placeholder="1–31"
              />
            ) : null}
          </div>
          {card ? (
            <div className="form-row">
              <TextField
                label="Minimum payment (%)"
                value={draft.percent}
                onChange={(percent) => update({ percent })}
                inputMode="decimal"
                placeholder="e.g. 3"
              />
              <AmountField
                label="At least"
                value={draft.payment}
                onChange={(payment) => update({ payment })}
                placeholder="e.g. 25.00"
              />
              <AmountField
                label="Credit limit"
                value={draft.creditLimit}
                onChange={(creditLimit) => update({ creditLimit })}
                placeholder="optional"
              />
            </div>
          ) : (
            <AmountField
              label="Monthly payment"
              value={draft.payment}
              onChange={(payment) => update({ payment })}
              placeholder={money.plain(0)}
            />
          )}
          <div className="form-row">
            <SelectField
              label="Paid from"
              value={draft.paymentAccountId}
              options={payers}
              onChange={(paymentAccountId) => update({ paymentAccountId })}
            />
            <SelectField
              label="Interest category"
              value={draft.interestCategoryId}
              options={categoryChoices}
              onChange={(interestCategoryId) => update({ interestCategoryId })}
              hint={
                draft.interestCategoryId === NEW_CATEGORY
                  ? 'Its own category, or pick one shared by all your debts.'
                  : undefined
              }
            />
          </div>
          {draft.interestCategoryId === NEW_CATEGORY ? (
            <TextField
              label="New category name"
              value={draft.newCategory || suggested}
              onChange={(value) => update({ newCategory: value })}
            />
          ) : null}
          {card ? (
            <>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={draft.proposeInterest}
                  onChange={(e) => update({ proposeInterest: e.target.checked })}
                />
                Propose the interest charge on every statement day, for me to confirm
              </label>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={draft.proposeMinimum}
                  onChange={(e) => update({ proposeMinimum: e.target.checked })}
                />
                Propose the minimum payment on every due day, for me to confirm
              </label>
            </>
          ) : null}
        </>
      ) : null}
    </fieldset>
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
