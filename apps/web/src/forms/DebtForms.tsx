import { useState } from 'react';
import { unwrap } from '../api/client';
import { useAccounts, useApiMutation, useCategories, useLoanSplit, useMoney, useOccurrences } from '../api/queries';
import type { Account, LoanPaymentSplit, Schedule } from '../api/types';
import { DateField } from '../components/DateField';
import { AmountField, FormDialog, SelectField, type Option } from '../components/forms';
import { Amount } from '../components/ui';
import { shiftMonth } from '../lib/calendar';
import { todayDay, type Day } from '../lib/dates';
import { isLiability, isLoan } from '../lib/debts';
import { NONE_ID, optionalAmount, parseDate, positiveAmount, requiredId } from '../lib/forms';
import type { MoneyFormat } from '../lib/money';
import { categoryOptions } from './TransactionForm';

function tryDate(text: string, today: Day): Day | null {
  try {
    return parseDate(text, today);
  } catch {
    return null;
  }
}

function tryAmount(text: string, parse: (text: string) => number | null): number | null {
  try {
    return parse(text);
  } catch {
    return null;
  }
}

function payerOptions(accounts: readonly Account[], exclude: number | null): Option<number>[] {
  return accounts
    .filter((a) => !a.is_closed && a.id !== exclude && !isLiability(a.type))
    .map((a) => ({ value: a.id, label: a.name }));
}

/** Interest · each fixed charge · Principal (· Owed before) of a loan payment. */
function LoanSplitLine({ split, money, owed = false }: { split: LoanPaymentSplit; money: MoneyFormat; owed?: boolean }) {
  return (
    <p className="loan-split" aria-live="polite">
      Interest <Amount value={-split.interest} money={money} />
      {split.charges.map((charge, index) => (
        <span key={index}>
          {' '}
          · {charge.label ?? 'Charge'} <Amount value={-charge.amount} money={money} />
        </span>
      ))}{' '}
      · Principal <Amount value={split.principal} money={money} />
      {owed ? (
        <>
          {' '}
          · Owed before <Amount value={-split.owed} money={money} muted />
        </>
      ) : null}
    </p>
  );
}

/** Pay into a loan: the payment is split into principal, interest and fixed charges from the amount owed. */
export function LoanPaymentForm({ loan, onClose }: { loan?: Account | null; onClose: () => void }) {
  const money = useMoney();
  const today = todayDay();
  const accounts = useAccounts(false).data ?? [];
  const categories = useCategories().data ?? [];
  const loans = accounts.filter((a) => isLoan(a.type));
  const [loanId, setLoanId] = useState<number | null>(loan?.id ?? null);
  const selected = accounts.find((a) => a.id === loanId) ?? loan ?? null;
  const terms = selected?.debt_terms ?? null;
  const [fromId, setFromId] = useState<number | null>(terms?.payment_account_id ?? null);
  const [date, setDate] = useState(today);
  const [amount, setAmount] = useState(terms?.payment != null ? money.plain(terms.payment) : '');
  const [categoryId, setCategoryId] = useState<number | null>(null);
  const [repeat, setRepeat] = useState(false);
  const category = categoryId ?? terms?.interest_category_id ?? NONE_ID;
  const payer = fromId ?? terms?.payment_account_id ?? null;

  const day = tryDate(date, today);
  const value = tryAmount(amount, (text) => optionalAmount(text, money));
  const split = useLoanSplit(selected?.id ?? null, day, value).data;

  const pickLoan = (id: number) => {
    setLoanId(id);
    const next = accounts.find((a) => a.id === id)?.debt_terms;
    if (next?.payment != null && !amount.trim()) setAmount(money.plain(next.payment));
  };

  const save = useApiMutation(async (api) => {
    const loanAccount = requiredId(selected?.id, 'the loan');
    const from = requiredId(payer, 'the account the money comes from');
    const paid = positiveAmount(amount, money);
    const when = parseDate(date, today);
    const interest = category === NONE_ID ? null : category;
    const transaction = await unwrap(
      api.POST('/api/v1/debts/{account_id}/payments', {
        params: { path: { account_id: loanAccount } },
        body: {
          date: when,
          amount: paid,
          from_account_id: from,
          interest_category_id: interest,
          description: `${selected?.name ?? 'Loan'} payment`,
        },
      }),
    );
    if (repeat) {
      await unwrap(
        api.POST('/api/v1/schedules', {
          body: {
            start: shiftMonth(when, 1),
            splits: [
              { type: 'account', account_id: from, amount: -paid },
              { type: 'account', account_id: loanAccount, amount: paid },
            ],
            frequency: 'monthly',
            every: 1,
            mode: 'auto',
            description: `${selected?.name ?? 'Loan'} payment`,
            debt: { kind: 'loan_payment', account_id: loanAccount, interest_category_id: interest },
          },
        }),
      );
    }
    return transaction;
  });

  return (
    <FormDialog
      open
      onClose={onClose}
      title="Loan payment"
      onSubmit={() => save.mutateAsync(undefined)}
      help="Picciuli works out the interest of the month on what you owe and takes the loan's fixed charges; the rest of the payment reduces the debt."
    >
      <div className="form-row">
        <SelectField
          label="Loan"
          value={selected?.id ?? null}
          options={loans.map((a) => ({ value: a.id, label: a.name }))}
          onChange={pickLoan}
        />
        <SelectField
          label="Paid from"
          value={payer}
          options={payerOptions(accounts, selected?.id ?? null)}
          onChange={setFromId}
        />
      </div>
      <div className="form-row">
        <DateField label="Date" value={date} onChange={setDate} today={today} />
        <AmountField label="Amount" value={amount} onChange={setAmount} inputMode="decimal" data-autofocus />
      </div>
      <SelectField
        label="Interest category"
        value={category}
        options={categoryOptions(categories)}
        onChange={setCategoryId}
      />
      {split ? <LoanSplitLine split={split} money={money} owed /> : null}
      <label className="switch">
        <input type="checkbox" checked={repeat} onChange={(e) => setRepeat(e.target.checked)} />
        Repeat every month from next month
      </label>
    </FormDialog>
  );
}

const OCCURRENCE_TITLES = {
  card_interest: 'Interest charge',
  card_min_payment: 'Minimum payment',
  loan_payment: 'Loan payment',
} as const;

/**
 * Confirm an occurrence of a schedule tied to a debt: a credit card interest
 * charge or minimum payment, or a loan payment. The amount is predicted from
 * the transactions recorded so far and can be changed.
 */
export function DebtOccurrenceForm({ schedule, date, onClose }: { schedule: Schedule; date: Day; onClose: () => void }) {
  const money = useMoney();
  const today = todayDay();
  const debt = schedule.debt!;
  const accounts = useAccounts(false).data ?? [];
  const account = accounts.find((a) => a.id === debt.account_id);
  const prediction = useOccurrences(date, date).data?.find((o) => o.schedule_id === schedule.id);
  const templatePayer = schedule.splits.find((s) => s.type === 'account' && s.account_id !== debt.account_id);
  const pays = debt.kind !== 'card_interest';
  const [day, setDay] = useState(date);
  const [amount, setAmount] = useState<string | null>(null);
  const [fromId, setFromId] = useState<number | null>(null);
  const predictedPayer =
    prediction?.splits?.find((s) => s.type === 'account' && s.account_id !== debt.account_id) ?? templatePayer;
  const payer =
    fromId ?? (predictedPayer?.type === 'account' ? predictedPayer.account_id : null) ?? account?.debt_terms?.payment_account_id ?? null;
  const shown = amount ?? (prediction?.amount != null ? money.plain(prediction.amount) : '');
  const loan = debt.kind === 'loan_payment';
  const split = useLoanSplit(
    loan ? debt.account_id : null,
    tryDate(day, today),
    loan ? tryAmount(shown, (text) => optionalAmount(text, money)) : null,
  ).data;

  const post = useApiMutation((api) => {
    const body: Record<string, unknown> = { date: parseDate(day, today) };
    if (amount !== null) body.amount = positiveAmount(amount, money);
    if (pays) body.from_account_id = requiredId(payer, 'the account the money comes from');
    return unwrap(
      api.POST('/api/v1/schedules/{schedule_id}/post', { params: { path: { schedule_id: schedule.id } }, body }),
    );
  });
  const skip = useApiMutation((api) =>
    unwrap(api.POST('/api/v1/schedules/{schedule_id}/skip', { params: { path: { schedule_id: schedule.id } } })),
  );

  return (
    <FormDialog
      open
      onClose={onClose}
      title={`${OCCURRENCE_TITLES[debt.kind]} – ${account?.name ?? schedule.description ?? ''}`}
      onSubmit={() => post.mutateAsync(undefined)}
      saveLabel="Record"
      secondary={
        <button
          type="button"
          className="button"
          onClick={async () => {
            await skip.mutateAsync(undefined);
            onClose();
          }}
        >
          Skip this one
        </button>
      }
      help={
        debt.kind === 'card_interest'
          ? 'Predicted from the average balance you owed during the statement cycle. Check it against your statement.'
          : debt.kind === 'card_min_payment'
            ? 'Predicted from the statement balance, less what you already paid into the card since then.'
            : 'The interest of the month is worked out on what you owe and the fixed charges are taken; the rest reduces the debt.'
      }
    >
      <div className="form-row">
        <DateField label="Date" value={day} onChange={setDay} today={today} />
        <AmountField label="Amount" value={shown} onChange={setAmount} inputMode="decimal" data-autofocus />
      </div>
      {pays ? (
        <SelectField
          label="Paid from"
          value={payer}
          options={payerOptions(accounts, debt.account_id)}
          onChange={setFromId}
        />
      ) : null}
      {loan && split ? <LoanSplitLine split={split} money={money} /> : null}
    </FormDialog>
  );
}
