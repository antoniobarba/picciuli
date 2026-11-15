import { useState, type FormEvent } from 'react';
import { unwrap } from '../api/client';
import { useApi } from '../api/context';
import { useApiMutation, useMe, usePriceProviders, useRateProviders, useSettings } from '../api/queries';
import type { CostMethod, Settings as BookSettings } from '../api/types';
import { useAuth } from '../auth/AuthProvider';
import { displayName } from '../auth/oidc';
import { useConfirm, useNotify } from '../components/feedback';
import { errorMessage, SelectField, TextField } from '../components/forms';
import { Loading, PageHeader } from '../components/ui';
import { COST_METHOD_LABELS } from '../lib/format';
import { InputError } from '../lib/forms';
import { MoneyFormat } from '../lib/money';

const COST_OPTIONS = (Object.keys(COST_METHOD_LABELS) as CostMethod[]).map((value) => ({
  value,
  label: COST_METHOD_LABELS[value],
}));

export function Settings() {
  const settings = useSettings();
  return (
    <div className="page narrow">
      <PageHeader title="Settings" />
      {settings.data ? <BookSettingsForm key={JSON.stringify(settings.data)} settings={settings.data} /> : <Loading />}
      <AccountSection />
    </div>
  );
}

function BookSettingsForm({ settings }: { settings: BookSettings }) {
  const notify = useNotify();
  const prices = usePriceProviders().data ?? [];
  const rates = useRateProviders().data ?? [];
  const [currency, setCurrency] = useState(settings.currency);
  const [digits, setDigits] = useState(String(settings.minor_digits));
  const [code, setCode] = useState(settings.currency_code ?? '');
  const [method, setMethod] = useState<CostMethod>(settings.cost_method);
  const [priceProvider, setPriceProvider] = useState(settings.price_provider);
  const [rateProvider, setRateProvider] = useState(settings.rate_provider);
  const [error, setError] = useState<string | null>(null);

  const withMissing = (list: { id: string; name: string }[], current: string) => {
    const options = list.map((p) => ({ value: p.id, label: p.name }));
    if (!options.some((o) => o.value === current)) options.push({ value: current, label: `${current} (not installed)` });
    return options;
  };

  const save = useApiMutation((api) => {
    const minor = Number(digits.trim());
    if (!/^\d+$/.test(digits.trim())) throw new InputError('decimal digits must be a whole number');
    return unwrap(
      api.PATCH('/api/v1/settings', {
        body: {
          currency: currency.trim(),
          minor_digits: minor,
          currency_code: code.trim() ? code.trim().toUpperCase() : null,
          cost_method: method,
          price_provider: priceProvider,
          rate_provider: rateProvider,
        },
      }),
    );
  });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await save.mutateAsync(undefined);
      notify('Settings saved', { kind: 'success' });
    } catch (failure) {
      setError(errorMessage(failure));
    }
  };

  const example = new MoneyFormat(currency.trim() || '$', Number(digits) || 0).amount(-123456789);

  return (
    <form className="card form settings-form" onSubmit={submit} noValidate>
      <div className="card-header">
        <h2>Book</h2>
      </div>
      <div className="form-body">
        <div className="form-row">
          <TextField label="Currency symbol" value={currency} onChange={setCurrency} hint={`e.g. ${example}`} />
          <TextField label="Decimal digits" value={digits} onChange={setDigits} inputMode="numeric" />
        </div>
        <div className="form-row">
          <TextField
            label="Currency code"
            value={code}
            onChange={setCode}
            placeholder="ISO code, e.g. EUR"
            maxLength={3}
            hint="Converts securities quoted in other currencies."
          />
          <SelectField label="Cost of sales" value={method} options={COST_OPTIONS} onChange={setMethod} />
        </div>
        <div className="form-row">
          <SelectField
            label="Price provider"
            value={priceProvider}
            options={withMissing(prices, priceProvider)}
            onChange={setPriceProvider}
            hint={prices.find((p) => p.id === priceProvider)?.description}
          />
          <SelectField
            label="Exchange rates"
            value={rateProvider}
            options={withMissing(rates, rateProvider)}
            onChange={setRateProvider}
            hint={rates.find((p) => p.id === rateProvider)?.description}
          />
        </div>
        <div className="form-help">
          Decimal digits only change how stored amounts are read: they are never rescaled. Changing the currency code
          deletes stored exchange rates. The cost method applies to sales recorded afterwards.
        </div>
      </div>
      {error ? (
        <div className="form-error" role="alert">
          {error}
        </div>
      ) : null}
      <div className="form-actions">
        <button type="submit" className="button primary" disabled={save.isPending}>
          {save.isPending ? 'Saving…' : 'Save settings'}
        </button>
      </div>
    </form>
  );
}

function AccountSection() {
  const api = useApi();
  const auth = useAuth();
  const me = useMe().data;
  const confirm = useConfirm();
  const notify = useNotify();
  const [busy, setBusy] = useState(false);

  const exportData = async () => {
    setBusy(true);
    try {
      const { data, response } = await api.GET('/api/v1/me/export', { parseAs: 'blob' });
      if (!response.ok || !data) throw new Error(`Export failed (${response.status})`);
      const url = URL.createObjectURL(data);
      const link = document.createElement('a');
      link.href = url;
      link.download = `picciuli-${new Date().toISOString().slice(0, 10)}.db`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (error) {
      notify(errorMessage(error), { title: 'Cannot export', kind: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const erase = useApiMutation((client) => unwrap(client.DELETE('/api/v1/me')));
  const eraseData = async () => {
    const ok = await confirm({
      title: 'Delete all your data?',
      message:
        'Every account, transaction, budget and price of your book is erased for good. Export a copy first if unsure. Your login is kept.',
      confirmLabel: 'Delete everything',
    });
    if (!ok) return;
    try {
      await erase.mutateAsync(undefined);
      notify('Your data was deleted.', { kind: 'success' });
    } catch (error) {
      notify(errorMessage(error), { title: 'Cannot delete', kind: 'error' });
    }
  };

  return (
    <section className="card">
      <div className="card-header">
        <h2>Your account</h2>
      </div>
      <dl className="facts">
        <dt>Signed in as</dt>
        <dd>
          {displayName(auth.user)}
          {auth.user?.profile.email && auth.user.profile.email !== displayName(auth.user) ? (
            <span className="muted"> · {auth.user.profile.email}</span>
          ) : null}
        </dd>
        {me ? (
          <>
            <dt>Data file</dt>
            <dd className="muted small mono">{me.id}</dd>
          </>
        ) : null}
      </dl>
      <div className="form-actions wrap">
        <button type="button" className="button" onClick={() => void exportData()} disabled={busy}>
          {busy ? 'Exporting…' : 'Export my data (SQLite)'}
        </button>
        <button type="button" className="button danger" onClick={() => void eraseData()}>
          Delete all my data
        </button>
        <button type="button" className="button" onClick={() => void auth.signOut()}>
          Sign out
        </button>
      </div>
      <p className="muted small card-note">
        The export opens with the Picciuli library and console interface: <code>picciuli-tui picciuli.db</code>.
      </p>
    </section>
  );
}
