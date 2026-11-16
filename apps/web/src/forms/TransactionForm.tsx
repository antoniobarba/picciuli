import { useMemo, useState } from 'react';
import { unwrap } from '../api/client';
import { useAccounts, useApiMutation, useCategories, useLoanSplit, useMoney, useSecurities } from '../api/queries';
import type { Account, Category, Schedule, Transaction } from '../api/types';
import { DateField } from '../components/DateField';
import { AmountField, FormDialog, SelectField, TextField, type Option } from '../components/forms';
import { useConfirm } from '../components/feedback';
import { todayDay, type Day } from '../lib/dates';
import { isLoan } from '../lib/debts';
import { byId, categoryTree, movesShares, transactionTitle } from '../lib/format';
import {
  accountTarget,
  categoryTarget,
  draftFromTransaction,
  draftSplits,
  emptyDraft,
  emptyLine,
  ENTRY_KIND_LABELS,
  lineTotals,
  NONE_ID,
  optionalText,
  parseDate,
  simpleLines,
  type EntryKind,
  type LineDraft,
  type TransactionDraft,
} from '../lib/forms';
import { quantityText } from '../lib/money';
import { templateTransaction } from '../lib/schedules';

/** An occurrence of a recurring transaction, to record (possibly changed) or skip. */
export interface OccurrenceToConfirm {
  schedule: Schedule;
  date: Day;
}

export interface TransactionFormProps {
  open: boolean;
  onClose: () => void;
  day: Day;
  transaction?: Transaction | null;
  accountId?: number | null;
  /** Record this occurrence of a recurring transaction instead of a new transaction. */
  occurrence?: OccurrenceToConfirm | null;
  /** Offered for existing transactions: repeat this transaction on a schedule. */
  onMakeRecurring?: (transaction: Transaction) => void;
}

function accountOptions(accounts: readonly Account[], keep: ReadonlySet<number>): Option<number>[] {
  return accounts
    .filter((account) => !account.is_closed || keep.has(account.id))
    .map((account) => ({ value: account.id, label: account.is_closed ? `${account.name} (closed)` : account.name }));
}

export function categoryOptions(categories: readonly Category[]): Option<number>[] {
  const names = new Map(categories.map((category) => [category.id, category.name]));
  return [
    { value: NONE_ID, label: 'Uncategorized' },
    ...categoryTree(categories).map((category) => ({
      value: category.id,
      label:
        category.parent_id === null
          ? category.name
          : `${names.get(category.parent_id) ?? ''} › ${category.name}`,
    })),
  ];
}

/** The account a simple draft uses: the chosen one, or the first open account. */
export function useSelectedAccount(draft: TransactionDraft): number | null {
  const accounts = useAccounts(true).data ?? [];
  const defaultAccount = accounts.find((account) => !account.is_closed)?.id ?? null;
  return draft.accountId ?? (draft.kind !== 'split' ? defaultAccount : null);
}

export interface TransactionFieldsProps {
  draft: TransactionDraft;
  update: (changes: Partial<TransactionDraft>) => void;
  /** Accounts used by the edited splits stay selectable even when closed. */
  usedAccounts?: ReadonlySet<number>;
  dateLabel?: string;
}

/** Kind tabs, date, amount, accounts, categories or split lines, description and notes. */
export function TransactionFields({ draft, update, usedAccounts, dateLabel = 'Date' }: TransactionFieldsProps) {
  const money = useMoney();
  const accounts = useAccounts(true).data ?? [];
  const categories = useCategories().data ?? [];
  const today = todayDay();
  const selectedAccount = useSelectedAccount(draft);
  const accountChoices = accountOptions(accounts, usedAccounts ?? new Set());
  const categoryChoices = categoryOptions(categories);

  const switchKind = (kind: EntryKind) => {
    if (kind === draft.kind) return;
    if (kind === 'split') {
      update({ kind, lines: simpleLines({ ...draft, accountId: selectedAccount }, money) });
    } else {
      update({ kind });
    }
  };

  return (
    <>
      <div className="segmented" role="tablist" aria-label="Kind">
        {(Object.keys(ENTRY_KIND_LABELS) as EntryKind[]).map((kind) => (
          <button
            key={kind}
            type="button"
            role="tab"
            aria-selected={draft.kind === kind}
            className={draft.kind === kind ? 'active' : ''}
            onClick={() => switchKind(kind)}
          >
            {ENTRY_KIND_LABELS[kind]}
          </button>
        ))}
      </div>
      <div className="form-row">
        <DateField label={dateLabel} value={draft.date} onChange={(date) => update({ date })} today={today} />
        {draft.kind !== 'split' ? (
          <AmountField label="Amount" value={draft.amount} onChange={(amount) => update({ amount })} data-autofocus />
        ) : null}
      </div>
      {draft.kind === 'expense' || draft.kind === 'income' ? (
        <div className="form-row">
          <SelectField
            label="Account"
            value={selectedAccount}
            options={accountChoices}
            onChange={(value) => update({ accountId: value })}
          />
          <SelectField
            label="Category"
            value={draft.categoryId ?? NONE_ID}
            options={categoryChoices}
            onChange={(value) => update({ categoryId: value })}
          />
        </div>
      ) : null}
      {draft.kind === 'transfer' ? (
        <div className="form-row">
          <SelectField
            label="From"
            value={selectedAccount}
            options={accountChoices}
            onChange={(value) => update({ accountId: value })}
          />
          <SelectField
            label="To"
            value={draft.toAccountId}
            options={accountChoices}
            onChange={(value) => update({ toAccountId: value })}
          />
        </div>
      ) : null}
      {draft.kind === 'split' ? (
        <SplitEditor
          lines={draft.lines}
          onChange={(lines) => update({ lines })}
          accounts={accountChoices}
          categories={categoryChoices}
        />
      ) : null}
      <TextField
        label="Description"
        value={draft.description}
        onChange={(description) => update({ description })}
        placeholder="optional"
      />
      <NotesField value={draft.notes} onChange={(notes) => update({ notes })} />
    </>
  );
}

export function transactionHelp(kind: EntryKind): string {
  if (kind === 'split') {
    return 'Account lines are balance changes (+ money in, − money out); the other lines are income (+) or expenses (−). The two totals must match.';
  }
  if (kind === 'transfer') return 'Money moving between two of your accounts, e.g. paying a credit card bill or saving.';
  return 'Type the amount as a positive number.';
}

export function TransactionForm({
  open,
  onClose,
  day,
  transaction,
  accountId,
  occurrence,
  onMakeRecurring,
}: TransactionFormProps) {
  const money = useMoney();
  const confirm = useConfirm();
  const today = todayDay();

  const [draft, setDraft] = useState<TransactionDraft>(() => {
    if (occurrence) return draftFromTransaction(templateTransaction(occurrence.schedule, occurrence.date), money);
    if (transaction) return draftFromTransaction(transaction, money);
    return emptyDraft(day, accountId ?? null);
  });
  const update = (changes: Partial<TransactionDraft>) => setDraft((current) => ({ ...current, ...changes }));
  const selectedAccount = useSelectedAccount(draft);

  const used = useMemo(() => {
    const ids = new Set<number>();
    for (const split of transaction?.splits ?? []) if (split.type === 'account') ids.add(split.account_id);
    return ids;
  }, [transaction]);

  const save = useApiMutation(async (api, current: TransactionDraft) => {
    const body = {
      date: parseDate(current.date, today),
      splits: draftSplits(current, money),
      description: optionalText(current.description),
      notes: optionalText(current.notes),
    };
    if (occurrence) {
      return unwrap(
        api.POST('/api/v1/schedules/{schedule_id}/post', {
          params: { path: { schedule_id: occurrence.schedule.id } },
          body,
        }),
      );
    }
    if (transaction) {
      return unwrap(
        api.PATCH('/api/v1/transactions/{transaction_id}', {
          params: { path: { transaction_id: transaction.id } },
          body,
        }),
      );
    }
    return unwrap(api.POST('/api/v1/transactions', { body }));
  });

  const remove = useApiMutation((api, id: number) =>
    unwrap(api.DELETE('/api/v1/transactions/{transaction_id}', { params: { path: { transaction_id: id } } })),
  );
  const skip = useApiMutation((api, id: number) =>
    unwrap(api.POST('/api/v1/schedules/{schedule_id}/skip', { params: { path: { schedule_id: id } } })),
  );

  const submit = () => save.mutateAsync({ ...draft, accountId: selectedAccount });

  let secondary = null;
  if (occurrence) {
    secondary = (
      <button
        type="button"
        className="button"
        onClick={async () => {
          await skip.mutateAsync(occurrence.schedule.id);
          onClose();
        }}
      >
        Skip this one
      </button>
    );
  } else if (transaction) {
    secondary = (
      <>
        <button
          type="button"
          className="button danger-text"
          onClick={async () => {
            if (await confirm({ title: `Delete “${transactionTitle(transaction)}”?` })) {
              await remove.mutateAsync(transaction.id);
              onClose();
            }
          }}
        >
          Delete
        </button>
        {onMakeRecurring && transaction.schedule_id == null && !movesShares(transaction) ? (
          <button
            type="button"
            className="button"
            onClick={() => {
              onClose();
              onMakeRecurring(transaction);
            }}
          >
            Make recurring
          </button>
        ) : null}
      </>
    );
  }

  const title = occurrence
    ? `Confirm “${occurrence.schedule.description || 'recurring transaction'}”`
    : transaction
      ? 'Edit transaction'
      : 'New transaction';

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      title={title}
      onSubmit={submit}
      saveLabel={occurrence ? 'Record' : 'Save'}
      wide={draft.kind === 'split'}
      secondary={secondary}
      help={
        occurrence
          ? 'Change the amount or the date if this time is different; the recurring transaction stays the same.'
          : transactionHelp(draft.kind)
      }
    >
      <TransactionFields draft={draft} update={update} usedAccounts={used} />
      {!occurrence && draft.kind === 'transfer' ? (
        <LoanSplitSuggestion
          draft={draft}
          fromAccountId={selectedAccount}
          transactionId={transaction?.id ?? null}
          onApply={(lines) => update({ kind: 'split', lines })}
        />
      ) : null}
    </FormDialog>
  );
}

/** For a transfer into a loan with terms: offer to split it into principal and interest. */
function LoanSplitSuggestion({
  draft,
  fromAccountId,
  transactionId,
  onApply,
}: {
  draft: TransactionDraft;
  fromAccountId: number | null;
  transactionId: number | null;
  onApply: (lines: LineDraft[]) => void;
}) {
  const money = useMoney();
  const today = todayDay();
  const accounts = useAccounts(true).data ?? [];
  const loan = accounts.find((a) => a.id === draft.toAccountId && isLoan(a.type) && a.debt_terms) ?? null;
  let date: Day | null = null;
  let amount: number | null = null;
  try {
    date = parseDate(draft.date, today);
    amount = draft.amount.trim() ? money.parse(draft.amount) : null;
  } catch {
    // Nothing to suggest until the date and the amount are valid.
  }
  const split = useLoanSplit(loan?.id ?? null, date, amount, transactionId).data;
  if (!loan || !split || !split.interest || fromAccountId === null) return null;
  const apply = () =>
    onApply([
      { ...emptyLine(accountTarget(fromAccountId)), amount: money.plain(-split.amount) },
      { ...emptyLine(accountTarget(loan.id)), amount: money.plain(split.principal) },
      {
        ...emptyLine(categoryTarget(loan.debt_terms?.interest_category_id)),
        amount: money.plain(-split.interest),
        memo: 'Interest',
      },
    ]);
  return (
    <div className="loan-split suggestion" role="note">
      <span>
        {money.amount(split.interest)} of this payment is interest and {money.amount(split.principal)} reduces the
        debt.
      </span>
      <button type="button" className="button small" onClick={apply}>
        Split into principal and interest
      </button>
    </div>
  );
}

export function NotesField({ value, onChange, label = 'Notes' }: { value: string; onChange: (value: string) => void; label?: string }) {
  return (
    <div className="field">
      <label>
        {label}
        <textarea rows={2} value={value} onChange={(e) => onChange(e.target.value)} placeholder="optional" />
      </label>
    </div>
  );
}

function SplitEditor({
  lines,
  onChange,
  accounts,
  categories,
}: {
  lines: LineDraft[];
  onChange: (lines: LineDraft[]) => void;
  accounts: Option<number>[];
  categories: Option<number>[];
}) {
  const money = useMoney();
  const securities = byId(useSecurities().data);
  const [accountTotal, externalTotal] = lineTotals(lines, money);
  const difference = accountTotal - externalTotal;

  const setLine = (index: number, changes: Partial<LineDraft>) =>
    onChange(lines.map((line, i) => (i === index ? { ...line, ...changes } : line)));

  return (
    <div className="split-editor">
      {lines.map((line, index) => (
        <div className="split-line" key={index}>
          <label className="sr-only" htmlFor={`split-target-${index}`}>
            Line {index + 1} account or category
          </label>
          <select
            id={`split-target-${index}`}
            value={line.target}
            onChange={(e) => setLine(index, { target: e.target.value })}
            disabled={line.securityId !== null}
          >
            <option value="">Account or category…</option>
            <optgroup label="Accounts">
              {accounts.map((option) => (
                <option key={option.value} value={accountTarget(option.value)}>
                  {option.label}
                </option>
              ))}
            </optgroup>
            <optgroup label="Income and expenses">
              {categories.map((option) => (
                <option key={option.value} value={categoryTarget(option.value)}>
                  {option.label}
                </option>
              ))}
            </optgroup>
          </select>
          <input
            aria-label={`Line ${index + 1} amount`}
            className="amount-input"
            placeholder="±0.00"
            value={line.amount}
            onChange={(e) => setLine(index, { amount: e.target.value })}
          />
          <input
            aria-label={`Line ${index + 1} memo`}
            placeholder="memo"
            value={line.memo}
            onChange={(e) => setLine(index, { memo: e.target.value })}
          />
          <button
            type="button"
            className="icon-button"
            aria-label={`Remove line ${index + 1}`}
            disabled={line.securityId !== null}
            onClick={() => onChange(lines.filter((_, i) => i !== index))}
          >
            ✕
          </button>
          {line.securityId !== null ? (
            <div className="split-shares">
              {quantityText(line.quantity)} shares of {securities.get(line.securityId)?.name ?? `#${line.securityId}`}
            </div>
          ) : null}
        </div>
      ))}
      <div className="split-footer">
        <button type="button" className="button small" onClick={() => onChange([...lines, emptyLine()])}>
          + Add line
        </button>
        <span className={`split-totals ${difference === 0 ? 'positive' : 'negative'}`}>
          Accounts {money.amount(accountTotal)} · Income/expenses {money.amount(externalTotal)}
          {difference === 0 ? ' ✓' : ` · differ by ${money.amount(Math.abs(difference))}`}
        </span>
      </div>
    </div>
  );
}
