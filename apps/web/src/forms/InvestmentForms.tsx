import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { unwrap } from '../api/client';
import { useApi } from '../api/context';
import {
  useAccounts,
  useApiMutation,
  useCategories,
  useMoney,
  useSecurities,
  useSettings,
} from '../api/queries';
import type { Security, SecurityInfo, SecurityKind, Transaction } from '../api/types';
import { DateField } from '../components/DateField';
import { AmountField, FormDialog, SelectField, TextField } from '../components/forms';
import { todayDay, type Day } from '../lib/dates';
import { SECURITY_KIND_LABELS, transactionTitle } from '../lib/format';
import {
  InputError,
  NONE_ID,
  nonNegativeAmount,
  optionalText,
  parseDate,
  positiveAmount,
  requiredId,
} from '../lib/forms';
import { parsePrice, parseQuantity } from '../lib/money';
import { categoryOptions, NotesField } from './TransactionForm';
import { Modal } from '../components/Modal';
import { Amount } from '../components/ui';
import { useConfirm } from '../components/feedback';

const KIND_OPTIONS = (Object.keys(SECURITY_KIND_LABELS) as SecurityKind[]).map((value) => ({
  value,
  label: SECURITY_KIND_LABELS[value],
}));

const SYMBOL_HELP =
  'The symbol is the one of the price provider: for Yahoo Finance a suffix selects the exchange (VWCE.DE XETRA, SWDA.MI Milan, VUSA.L London, AAPL Nasdaq). Securities bought on gettex can use their XETRA listing.';

export interface SecurityDraft {
  name: string;
  symbol: string;
  isin: string;
  currency: string;
  kind: SecurityKind;
  notes: string;
}

export function securityDraft(security: Security | null, found?: SecurityInfo): SecurityDraft {
  if (security) {
    return {
      name: security.name,
      symbol: security.symbol ?? '',
      isin: security.isin ?? '',
      currency: security.currency,
      kind: security.kind,
      notes: security.notes ?? '',
    };
  }
  const kind = (found?.kind ?? '').toLowerCase();
  return {
    name: found?.name ?? '',
    symbol: found?.symbol ?? '',
    isin: '',
    currency: found?.currency ?? '',
    kind: kind in SECURITY_KIND_LABELS ? (kind as SecurityKind) : kind === 'equity' ? 'stock' : 'etf',
    notes: '',
  };
}

export function SecurityForm({
  security,
  initial,
  onClose,
}: {
  security: Security | null;
  initial?: SecurityDraft;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<SecurityDraft>(initial ?? securityDraft(security));
  const set = (changes: Partial<SecurityDraft>) => setDraft((current) => ({ ...current, ...changes }));
  const save = useApiMutation(async (api) => {
    if (!draft.currency.trim()) throw new InputError('a currency code such as EUR is required');
    const body = {
      name: draft.name,
      currency: draft.currency.trim().toUpperCase(),
      kind: draft.kind,
      symbol: optionalText(draft.symbol),
      isin: optionalText(draft.isin),
      notes: optionalText(draft.notes),
    };
    if (security) {
      return unwrap(
        api.PATCH('/api/v1/securities/{security_id}', { params: { path: { security_id: security.id } }, body }),
      );
    }
    return unwrap(api.POST('/api/v1/securities', { body }));
  });
  return (
    <FormDialog
      open
      onClose={onClose}
      title={security ? `Edit ${security.name}` : 'New security'}
      onSubmit={() => save.mutateAsync(undefined)}
      help={SYMBOL_HELP}
    >
      <TextField label="Name" value={draft.name} onChange={(name) => set({ name })} data-autofocus />
      <div className="form-row">
        <TextField label="Symbol" value={draft.symbol} onChange={(symbol) => set({ symbol })} placeholder="VWCE.DE" />
        <TextField label="ISIN" value={draft.isin} onChange={(isin) => set({ isin })} placeholder="optional" />
      </div>
      <div className="form-row">
        <TextField
          label="Currency"
          value={draft.currency}
          onChange={(currency) => set({ currency })}
          placeholder="EUR"
          maxLength={3}
        />
        <SelectField label="Kind" value={draft.kind} options={KIND_OPTIONS} onChange={(kind) => set({ kind })} />
      </div>
      <NotesField value={draft.notes} onChange={(notes) => set({ notes })} />
    </FormDialog>
  );
}

/** Search the price provider, then open the security form with the chosen listing. */
export function FindSecurity({ onClose, onFound }: { onClose: () => void; onFound: (info: SecurityInfo) => void }) {
  const api = useApi();
  const settings = useSettings().data;
  const [text, setText] = useState('');
  const [query, setQuery] = useState('');
  const provider = settings?.price_provider ?? 'yahoo';
  const results = useQuery({
    queryKey: ['search', provider, query],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/providers/prices/{provider_id}/search', {
          params: { path: { provider_id: provider }, query: { q: query } },
        }),
      ),
    enabled: query.length > 0,
    staleTime: 5 * 60_000,
    retry: false,
    meta: { quiet: true },
  });
  return (
    <Modal open onClose={onClose} title="Find a security online" wide>
      <form
        className="search-form"
        onSubmit={(e) => {
          e.preventDefault();
          setQuery(text.trim());
        }}
      >
        <input
          aria-label="Name, symbol or ISIN"
          placeholder="Name, symbol or ISIN, e.g. VWCE or IE00BK5BQT80"
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoFocus
        />
        <button type="submit" className="button primary" disabled={!text.trim()}>
          Search
        </button>
      </form>
      <div className="form-body">
        {results.isFetching ? <div className="loading">Searching…</div> : null}
        {results.error ? <div className="form-error">{(results.error as Error).message}</div> : null}
        {results.data && !results.data.length ? <div className="empty">Nothing found.</div> : null}
        {results.data?.length ? (
          <ul className="pick-list">
            {results.data.map((info) => (
              <li key={`${info.symbol}-${info.exchange ?? ''}`}>
                <button type="button" onClick={() => onFound(info)}>
                  <span>
                    <strong>{info.symbol}</strong> {info.name}
                  </span>
                  <span className="muted small">
                    {[info.exchange, info.kind, info.currency].filter(Boolean).join(' · ')}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="form-help">The search uses the price provider selected in the settings.</div>
      </div>
    </Modal>
  );
}

export function PriceForm({ security, onClose }: { security: Security; onClose: () => void }) {
  const today = todayDay();
  const [date, setDate] = useState(today);
  const [price, setPrice] = useState('');
  const save = useApiMutation((api) =>
    unwrap(
      api.PUT('/api/v1/securities/{security_id}/prices/{date}', {
        params: { path: { security_id: security.id, date: parseDate(date, today) } },
        body: { price: parsePrice(price), source: 'manual' },
      }),
    ),
  );
  return (
    <FormDialog
      open
      onClose={onClose}
      title={`Price of ${security.name}`}
      onSubmit={() => save.mutateAsync(undefined)}
      help="One price per day: a new price replaces the one of that day."
    >
      <div className="form-row">
        <DateField label="Date" value={date} onChange={setDate} today={today} />
        <TextField
          label={`Price (${security.currency})`}
          value={price}
          onChange={setPrice}
          inputMode="decimal"
          data-autofocus
        />
      </div>
    </FormDialog>
  );
}

/** A purchase or sale of shares, as the buy and sell endpoints record it. */
export interface Trade {
  selling: boolean;
  date: Day;
  accountId: number;
  securityId: number;
  /** Positive number of shares. */
  quantity: string;
  /** Cost of a purchase or proceeds of a sale. */
  amount: number;
  /** Account paying or receiving the money; `null` for the investment account's cash. */
  otherId: number | null;
  fee: number;
  feeCategoryId: number | null;
  tax: number;
  taxCategoryId: number | null;
  gainCategoryId: number | null;
}

/** The trade a transaction records, or `null` when its splits are not those of a buy or sell. */
export function tradeOf(transaction: Transaction): Trade | null {
  const shares = transaction.splits.filter((s) => s.type === 'account' && s.security_id != null);
  const cash = transaction.splits.filter((s) => s.type === 'account' && s.security_id == null);
  const external = transaction.splits.filter((s) => s.type === 'external');
  const [share] = shares;
  if (shares.length !== 1 || share?.type !== 'account' || share.security_id == null || !share.quantity) return null;
  let memos = new Map(external.map((s) => [s.memo ?? '', s]));
  if (memos.size !== external.length || cash.length > 1) return null;
  const selling = share.quantity.startsWith('-');
  const allowed = selling ? ['Realized gain', 'Fee', 'Tax'] : ['Fee'];
  // A sale's lone line with another memo (e.g. from an import) is its realized gain or loss.
  const [lone] = external;
  if (selling && external.length === 1 && lone && !allowed.includes(lone.memo ?? '')) {
    memos = new Map([['Realized gain', lone]]);
  }
  if ([...memos.keys()].some((memo) => !allowed.includes(memo))) return null;
  const fee = 0 - (memos.get('Fee')?.amount ?? 0);
  const tax = 0 - (memos.get('Tax')?.amount ?? 0);
  if (fee < 0 || tax < 0) return null;
  const [money] = cash;
  const otherId = money?.type === 'account' && money.account_id !== share.account_id ? money.account_id : null;
  const categoryOf = (memo: string) => {
    const split = memos.get(memo);
    return split?.type === 'external' ? (split.category_id ?? null) : null;
  };
  const amount = selling ? -share.amount + (memos.get('Realized gain')?.amount ?? 0) : share.amount;
  const expected = selling ? amount - fee - tax : -(amount + fee);
  if (amount <= 0 || (money?.amount ?? 0) !== expected || (!selling && !money)) return null;
  return {
    selling,
    date: transaction.date,
    accountId: share.account_id,
    securityId: share.security_id,
    quantity: share.quantity.replace(/^-/, ''),
    amount,
    otherId,
    fee,
    feeCategoryId: categoryOf('Fee'),
    tax,
    taxCategoryId: categoryOf('Tax'),
    gainCategoryId: categoryOf('Realized gain'),
  };
}

/** Buy or sell shares; with `editing`, change a recorded trade in place. */
export function TradeForm({
  selling: sellingProp,
  onClose,
  accountId,
  securityId,
  editing,
}: {
  selling: boolean;
  onClose: () => void;
  accountId?: number | null;
  securityId?: number | null;
  editing?: { transaction: Transaction; trade: Trade };
}) {
  const api = useApi();
  const money = useMoney();
  const confirm = useConfirm();
  const today = todayDay();
  const trade = editing?.trade;
  const selling = trade ? trade.selling : sellingProp;
  const accounts = (useAccounts(false).data ?? []).filter((a) => !a.is_closed);
  const investment = accounts.filter((a) => a.type === 'investment');
  const securities = useSecurities().data ?? [];
  const categories = useCategories().data ?? [];
  const amountText = (value: number | undefined) => (value ? money.plain(value) : '');
  const [date, setDate] = useState<string>(trade?.date ?? today);
  const [account, setAccount] = useState<number | null>(trade?.accountId ?? accountId ?? investment[0]?.id ?? null);
  const [security, setSecurity] = useState<number | null>(trade?.securityId ?? securityId ?? null);
  const [quantity, setQuantity] = useState(trade?.quantity ?? '');
  const [amount, setAmount] = useState(amountText(trade?.amount));
  const [other, setOther] = useState<number>(trade?.otherId ?? NONE_ID);
  const [fee, setFee] = useState(amountText(trade?.fee));
  const [tax, setTax] = useState(amountText(trade?.tax));
  const [category, setCategory] = useState<number>(
    (selling ? trade?.gainCategoryId : trade?.feeCategoryId) ?? NONE_ID,
  );
  const [description, setDescription] = useState(editing?.transaction.description ?? '');
  const [notes, setNotes] = useState(editing?.transaction.notes ?? '');
  const transactionId = editing?.transaction.id;

  let parsed: { quantity: string; date: string } | null = null;
  try {
    parsed = { quantity: parseQuantity(quantity), date: parseDate(date, today) };
  } catch {
    parsed = null;
  }
  const saleCost = useQuery({
    queryKey: ['sale-cost', account, security, parsed?.quantity, parsed?.date, transactionId],
    queryFn: () =>
      unwrap(
        api.GET('/api/v1/investments/{account_id}/sale-cost', {
          params: {
            path: { account_id: account! },
            query: {
              security_id: security!,
              quantity: parsed!.quantity,
              date: parsed!.date,
              ...(transactionId ? { excluding: transactionId } : {}),
            },
          },
        }),
      ),
    enabled: selling && Boolean(account && security && parsed),
    retry: false,
    meta: { quiet: true },
  });

  const save = useApiMutation(async (client) => {
    const common = {
      date: parseDate(date, today),
      account_id: requiredId(account, 'an investment account'),
      security_id: requiredId(security, 'a security'),
      quantity: parseQuantity(quantity),
      fee: nonNegativeAmount(fee, money, 'fee'),
      description: optionalText(description),
      notes: optionalText(notes),
    };
    if (selling) {
      const body = {
        ...common,
        proceeds: positiveAmount(amount, money),
        to_account_id: other || null,
        tax: nonNegativeAmount(tax, money, 'tax'),
        gain_category_id: category || null,
        // The form has no fee and tax categories for a sale: an edit keeps them.
        fee_category_id: trade?.feeCategoryId ?? null,
        tax_category_id: trade?.taxCategoryId ?? null,
      };
      return unwrap(
        transactionId
          ? client.PUT('/api/v1/investments/sell/{transaction_id}', {
              params: { path: { transaction_id: transactionId } },
              body,
            })
          : client.POST('/api/v1/investments/sell', { body }),
      );
    }
    const body = {
      ...common,
      cost: positiveAmount(amount, money),
      from_account_id: other || null,
      fee_category_id: category || null,
    };
    return unwrap(
      transactionId
        ? client.PUT('/api/v1/investments/buy/{transaction_id}', {
            params: { path: { transaction_id: transactionId } },
            body,
          })
        : client.POST('/api/v1/investments/buy', { body }),
    );
  });

  const remove = useApiMutation((client, id: number) =>
    unwrap(client.DELETE('/api/v1/transactions/{transaction_id}', { params: { path: { transaction_id: id } } })),
  );
  const deleteButton = editing ? (
    <button
      type="button"
      className="button danger-text"
      onClick={async () => {
        if (await confirm({ title: `Delete ?${transactionTitle(editing.transaction)}??` })) {
          await remove.mutateAsync(editing.transaction.id);
          onClose();
        }
      }}
    >
      Delete
    </button>
  ) : null;

  let gain: number | null = null;
  if (selling && saleCost.data) {
    try {
      gain = positiveAmount(amount, money) - saleCost.data.cost;
    } catch {
      gain = null;
    }
  }

  const otherAccounts = [
    { value: NONE_ID, label: 'Cash of the investment account' },
    ...accounts.filter((a) => a.id !== account).map((a) => ({ value: a.id, label: a.name })),
  ];

  return (
    <FormDialog
      open
      onClose={onClose}
      title={editing ? (selling ? 'Edit sale' : 'Edit purchase') : selling ? 'Sell shares' : 'Buy shares'}
      saveLabel={editing ? undefined : selling ? 'Sell' : 'Buy'}
      onSubmit={() => save.mutateAsync(undefined)}
      secondary={deleteButton}
      help={
        selling
          ? 'Proceeds are the gross amount of the sale; the fee and tax are paid from them. The realized gain (proceeds minus the cost of the shares) goes to the gain category.'
          : 'The cost is the price paid for the shares, without the fee.'
      }
    >
      <div className="form-row">
        <DateField label="Date" value={date} onChange={setDate} today={today} />
        <SelectField
          label="Investment account"
          value={account}
          options={investment.map((a) => ({ value: a.id, label: a.name }))}
          onChange={setAccount}
          placeholder={investment.length ? undefined : 'Create an investment account first'}
        />
      </div>
      <SelectField
        label="Security"
        value={security}
        options={securities.map((s) => ({ value: s.id, label: `${s.name}${s.symbol ? ` (${s.symbol})` : ''}` }))}
        onChange={setSecurity}
      />
      <div className="form-row">
        <TextField label="Quantity" value={quantity} onChange={setQuantity} inputMode="decimal" placeholder="1.5" />
        <AmountField label={selling ? 'Proceeds' : 'Cost'} value={amount} onChange={setAmount} />
      </div>
      <SelectField
        label={selling ? 'Money goes to' : 'Paid from'}
        value={other}
        options={otherAccounts}
        onChange={setOther}
      />
      <div className="form-row">
        <AmountField label="Fee" value={fee} onChange={setFee} placeholder="0" />
        {selling ? <AmountField label="Tax" value={tax} onChange={setTax} placeholder="0" /> : null}
      </div>
      <SelectField
        label={selling ? 'Gain category' : 'Fee category'}
        value={category}
        options={categoryOptions(categories)}
        onChange={setCategory}
      />
      <TextField label="Description" value={description} onChange={setDescription} placeholder="optional" />
      <NotesField value={notes} onChange={setNotes} />
      {selling && saleCost.data ? (
        <div className="form-help">
          Cost basis of these shares: {money.amount(saleCost.data.cost)}
          {gain !== null ? (
            <>
              {' '}
              · realized gain <Amount value={gain} money={money} plus />
            </>
          ) : null}
        </div>
      ) : null}
      {selling && saleCost.error ? <div className="form-help negative">{(saleCost.error as Error).message}</div> : null}
    </FormDialog>
  );
}
