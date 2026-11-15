import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { unwrap } from '../api/client';
import { useApi } from '../api/context';
import { useAccounts, useApiMutation, useLatestPrices, useMoney, useSecurities, useSettings, useValuations } from '../api/queries';
import type { Security, SecurityInfo } from '../api/types';
import { useLivePrices } from '../app/live';
import { DateField } from '../components/DateField';
import { useConfirm, useNotify } from '../components/feedback';
import { errorMessage, FormDialog } from '../components/forms';
import { Amount, Empty, Loading, PageHeader, RowMenu } from '../components/ui';
import { addDays, shortDate, todayDay } from '../lib/dates';
import { parseDate } from '../lib/forms';
import { percentText, priceText, quantityText, roundedPrice } from '../lib/money';
import { useHotkeys } from '../lib/useHotkeys';
import { FindSecurity, PriceForm, SecurityForm, securityDraft, TradeForm, type SecurityDraft } from '../forms/InvestmentForms';

type Dialog =
  | { kind: 'security'; security: Security | null; initial?: SecurityDraft }
  | { kind: 'find' }
  | { kind: 'trade'; selling: boolean; accountId?: number; securityId?: number }
  | { kind: 'price'; security: Security }
  | { kind: 'history'; start: string }
  | null;

export function Investments() {
  const api = useApi();
  const money = useMoney();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const notify = useNotify();
  const live = useLivePrices();
  const settings = useSettings().data;
  const bookCurrency = settings?.currency_code ?? '';
  const valuations = useValuations();
  const accounts = useAccounts(false).data ?? [];
  const securities = useSecurities();
  const latest = useLatestPrices(securities.data);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const investmentValuations = useMemo(
    () => (valuations.data ?? []).filter((v) => v.account.type === 'investment' || v.holdings.length > 0),
    [valuations.data],
  );
  const totals = investmentValuations.reduce(
    (sum, v) => ({ cost: sum.cost + v.cost_basis, value: sum.value + v.market_value, gain: sum.gain + v.unrealized_gain }),
    { cost: 0, value: 0, gain: 0 },
  );
  const selected = securities.data?.find((s) => s.id === selectedId) ?? null;

  const remove = useApiMutation((client, id: number) =>
    unwrap(client.DELETE('/api/v1/securities/{security_id}', { params: { path: { security_id: id } } })),
  );
  const deleteSecurity = async (security: Security) => {
    if (await confirm({ title: `Delete “${security.name}”?`, message: 'A security in use cannot be deleted.' })) {
      try {
        await remove.mutateAsync(security.id);
      } catch (error) {
        notify(errorMessage(error), { title: 'Cannot do that', kind: 'error' });
      }
    }
  };

  /** Default start of the history download: the first transaction of an investment account. */
  const askHistory = async () => {
    let first = addDays(todayDay(), -365);
    try {
      for (const account of accounts.filter((a) => a.type === 'investment')) {
        const found = await unwrap(
          api.GET('/api/v1/transactions', { params: { query: { account_id: account.id, limit: 1 } } }),
        );
        if (found[0] && found[0].date < first) first = found[0].date;
      }
    } catch {
      // Keep the default.
    }
    setDialog({ kind: 'history', start: first });
  };

  const trade = (selling: boolean) => {
    if (!accounts.some((a) => a.type === 'investment')) {
      notify('Create an investment account first (Accounts → New, type Investment).', { kind: 'warning' });
    } else if (!securities.data?.length) {
      notify('Create a security first: New security or Find online.', { kind: 'warning' });
    } else {
      setDialog({ kind: 'trade', selling });
    }
  };

  useHotkeys({
    n: () => setDialog({ kind: 'security', security: null }),
    e: () => selected && setDialog({ kind: 'security', security: selected }),
    d: () => selected && void deleteSecurity(selected),
    f: () => setDialog({ kind: 'find' }),
    b: () => trade(false),
    x: () => trade(true),
    p: () => selected && setDialog({ kind: 'price', security: selected }),
    r: () => void live.refresh(),
    h: () => void askHistory(),
  });

  return (
    <div className="page">
      <PageHeader title="Investments">
        <button type="button" className="button" onClick={() => void live.refresh()} disabled={live.refreshing}>
          {live.refreshing ? 'Refreshing…' : 'Refresh prices'}
        </button>
        <label className="switch">
          <input type="checkbox" checked={live.live} onChange={(e) => live.setLive(e.target.checked)} />
          Live
        </label>
        <button type="button" className="button" onClick={() => trade(true)}>
          Sell
        </button>
        <button type="button" className="button primary" onClick={() => trade(false)}>
          Buy
        </button>
      </PageHeader>
      {live.lastUpdate ? (
        <p className="muted small">Prices refreshed at {live.lastUpdate.toLocaleTimeString()}. Quotes are usually delayed by about 15 minutes.</p>
      ) : null}

      <section className="card">
        <div className="card-header">
          <h2>Holdings</h2>
        </div>
        {valuations.isLoading ? (
          <Loading />
        ) : investmentValuations.length === 0 ? (
          <Empty>No investment accounts yet. Create one in Accounts (type Investment), add a security, then Buy.</Empty>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Security</th>
                <th className="num">Quantity</th>
                <th className="num hide-md">Price</th>
                <th className="num hide-sm">Price{bookCurrency ? ` (${bookCurrency})` : ''}</th>
                <th className="num hide-md">Cost</th>
                <th className="num">Value</th>
                <th className="num">Gain</th>
              </tr>
            </thead>
            {investmentValuations.map((valuation) => (
              <tbody key={valuation.account.id}>
                <tr className="group-row" onClick={() => navigate(`/accounts/${valuation.account.id}`)}>
                  <th colSpan={7}>
                    {valuation.account.name}
                    {!valuation.is_complete ? <span className="muted small"> · some prices are missing</span> : null}
                  </th>
                </tr>
                {valuation.holdings.map((holding) => (
                  <tr key={holding.security.id}>
                    <td>
                      {holding.security.name}
                      <span className="muted small"> {holding.security.symbol ?? ''}</span>
                    </td>
                    <td className="num">{quantityText(holding.quantity)}</td>
                    <td className="num hide-md">
                      {holding.price ? priceText(holding.price, holding.security.currency) : '?'}
                      {holding.price_date ? <span className="muted small block">{shortDate(holding.price_date)}</span> : null}
                    </td>
                    <td className="num hide-sm">
                      {holding.converted_price ? priceText(roundedPrice(holding.converted_price), '') : '?'}
                    </td>
                    <td className="num hide-md">{money.amount(holding.cost_basis)}</td>
                    <td className="num">{holding.market_value !== null ? <Amount value={holding.market_value} money={money} /> : '?'}</td>
                    <td className="num">
                      {holding.unrealized_gain !== null ? (
                        <>
                          <Amount value={holding.unrealized_gain} money={money} plus />
                          <span className="muted small block">{percentText(holding.unrealized_gain, holding.cost_basis)}</span>
                        </>
                      ) : (
                        '?'
                      )}
                    </td>
                  </tr>
                ))}
                {valuation.cash ? (
                  <tr>
                    <td colSpan={2}>
                      <em>Cash</em>
                    </td>
                    <td className="hide-md" />
                    <td className="hide-sm" />
                    <td className="hide-md" />
                    <td className="num">
                      <Amount value={valuation.cash} money={money} />
                    </td>
                    <td />
                  </tr>
                ) : null}
              </tbody>
            ))}
            <tfoot>
              <tr>
                <th colSpan={2}>Total</th>
                <td className="hide-md" />
                <td className="hide-sm" />
                <td className="num hide-md bold">{money.amount(totals.cost)}</td>
                <td className="num">
                  <Amount value={totals.value} money={money} bold />
                </td>
                <td className="num">
                  <Amount value={totals.gain} money={money} plus bold />
                </td>
              </tr>
            </tfoot>
          </table>
        )}
      </section>

      <section className="card">
        <div className="card-header">
          <h2>Securities</h2>
          <div className="toolbar">
            <button type="button" className="button small" onClick={() => void askHistory()}>
              Download history
            </button>
            <button type="button" className="button small" onClick={() => setDialog({ kind: 'find' })}>
              Find online
            </button>
            <button type="button" className="button small" onClick={() => setDialog({ kind: 'security', security: null })}>
              + New
            </button>
          </div>
        </div>
        {securities.isLoading ? (
          <Loading />
        ) : !securities.data?.length ? (
          <Empty>No securities yet. Use Find online to search by name, symbol or ISIN.</Empty>
        ) : (
          <table className="table rows-clickable">
            <thead>
              <tr>
                <th>Name</th>
                <th>Symbol</th>
                <th className="hide-md">ISIN</th>
                <th className="hide-sm">Currency</th>
                <th className="num">Latest price</th>
                <th className="num hide-sm">Price{bookCurrency ? ` (${bookCurrency})` : ''}</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {securities.data.map((security) => {
                const info = latest.get(security.id);
                const edit = () => setDialog({ kind: 'security', security });
                return (
                  <tr
                    key={security.id}
                    tabIndex={0}
                    className={security.id === selectedId ? 'selected' : ''}
                    onFocus={() => setSelectedId(security.id)}
                    onClick={edit}
                    onKeyDown={(e) => e.key === 'Enter' && edit()}
                  >
                    <td>{security.name}</td>
                    <td className="muted">{security.symbol ?? ''}</td>
                    <td className="hide-md muted">{security.isin ?? ''}</td>
                    <td className="hide-sm">{security.currency}</td>
                    <td className="num">
                      {info?.price ? priceText(info.price.price, security.currency) : <span className="muted">none</span>}
                      {info?.price ? <span className="muted small block">{shortDate(info.price.date)}</span> : null}
                    </td>
                    <td className="num hide-sm">
                      {info?.price_in_book_currency
                        ? priceText(roundedPrice(info.price_in_book_currency), '')
                        : info?.price
                          ? '?'
                          : ''}
                    </td>
                    <td className="actions" onClick={(e) => e.stopPropagation()}>
                      <RowMenu
                        actions={[
                          { label: 'Edit', onSelect: edit, shortcut: 'e' },
                          { label: 'Enter a price', onSelect: () => setDialog({ kind: 'price', security }), shortcut: 'p' },
                          { label: 'Buy', onSelect: () => setDialog({ kind: 'trade', selling: false, securityId: security.id }) },
                          { label: 'Sell', onSelect: () => setDialog({ kind: 'trade', selling: true, securityId: security.id }) },
                          { label: 'Delete', onSelect: () => void deleteSecurity(security), danger: true, shortcut: 'd' },
                        ]}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="muted small card-note">
          “?” means the exchange rate is not known yet: refresh the prices. Securities quoted in the book currency show the same price in both columns.
        </p>
      </section>

      {dialog?.kind === 'security' ? (
        <SecurityForm security={dialog.security} initial={dialog.initial} onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.kind === 'find' ? (
        <FindSecurity
          onClose={() => setDialog(null)}
          onFound={(info: SecurityInfo) => setDialog({ kind: 'security', security: null, initial: securityDraft(null, info) })}
        />
      ) : null}
      {dialog?.kind === 'trade' ? (
        <TradeForm
          selling={dialog.selling}
          accountId={dialog.accountId}
          securityId={dialog.securityId}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === 'price' ? <PriceForm security={dialog.security} onClose={() => setDialog(null)} /> : null}
      {dialog?.kind === 'history' ? (
        <HistoryForm start={dialog.start} onClose={() => setDialog(null)} onStart={(day) => live.refresh({ historyStart: day })} />
      ) : null}
    </div>
  );
}

function HistoryForm({
  start,
  onClose,
  onStart,
}: {
  start: string;
  onClose: () => void;
  onStart: (day: string) => Promise<void>;
}) {
  const today = todayDay();
  const [day, setDay] = useState(start);
  return (
    <FormDialog
      open
      onClose={onClose}
      title="Download price history"
      saveLabel="Download"
      onSubmit={() => onStart(parseDate(day, today))}
      help="Downloads the daily closing prices and exchange rates since this day, so that past balances use real market values."
    >
      <DateField label="Since" value={day} onChange={setDay} today={today} autoFocus />
    </FormDialog>
  );
}
