import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useAccounts, useDebtPlans, useDebts, useMoney, useOccurrences, useSchedules } from '../api/queries';
import type { Account, DebtPlan, DebtPlanIn, DebtStatus, Rollover } from '../api/types';
import { useEditors } from '../app/editors';
import { DateField } from '../components/DateField';
import { AmountField } from '../components/forms';
import { Amount, Empty, Loading, PageHeader, ProgressBar } from '../components/ui';
import { AccountForm } from '../forms/AccountForm';
import { LoanPaymentForm } from '../forms/DebtForms';
import { addDays, shortDate, todayDay, type Day } from '../lib/dates';
import { durationLabel, isCard, isLoan, payoffLabel, ROLLOVER_CHOICES } from '../lib/debts';
import { ACCOUNT_TYPE_LABELS, byId } from '../lib/format';
import { InputError, parseDate, positiveAmount } from '../lib/forms';
import type { MoneyFormat } from '../lib/money';
import { useHotkeys } from '../lib/useHotkeys';

/** Days ahead in which proposed card charges and payments are shown. */
const CARD_DAYS = 45;
/** Wait after the last change of the extra payment before planning again. */
const DEBOUNCE_MS = 300;

type Dialog = { kind: 'terms'; account: Account } | { kind: 'payment'; account: Account | null } | null;

interface LumpDraft {
  date: string;
  amount: string;
}

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/** Valid lump sums of the drafts; incomplete rows are left out. */
function lumpSums(drafts: readonly LumpDraft[], money: MoneyFormat, today: Day): DebtPlanIn['lump_sums'] {
  const result: NonNullable<DebtPlanIn['lump_sums']> = [];
  for (const draft of drafts) {
    try {
      result.push({ date: parseDate(draft.date, today), amount: positiveAmount(draft.amount, money) });
    } catch (error) {
      if (!(error instanceof InputError)) throw error;
    }
  }
  return result;
}

export function Debts() {
  const money = useMoney();
  const today = todayDay();
  const debts = useDebts(today);
  const [dialog, setDialog] = useState<Dialog>(null);
  const list = debts.data ?? [];

  useHotkeys({ p: () => setDialog({ kind: 'payment', account: null }) });

  return (
    <div className="page">
      <PageHeader title="Debts">
        <button type="button" className="button primary" onClick={() => setDialog({ kind: 'payment', account: null })}>
          + Loan payment
        </button>
      </PageHeader>
      {debts.isLoading ? (
        <Loading />
      ) : list.length === 0 ? (
        <Empty>
          <p>
            Add the interest rate and the payments of your cards, loans and mortgage: edit them on the Accounts
            screen and tick “Track the interest rate and the payments”. Picciuli will then forecast when each debt
            is paid off and plan how to get there faster.
          </p>
          <Link to="/accounts" className="button primary">
            Go to Accounts
          </Link>
        </Empty>
      ) : (
        <>
          <div className="debt-grid">
            {list.map((debt) => (
              <DebtCard
                key={debt.account.id}
                debt={debt}
                money={money}
                today={today}
                onEdit={() => setDialog({ kind: 'terms', account: debt.account })}
                onPay={() => setDialog({ kind: 'payment', account: debt.account })}
              />
            ))}
          </div>
          <Planner debts={list} money={money} today={today} />
        </>
      )}
      {dialog?.kind === 'terms' ? <AccountForm account={dialog.account} onClose={() => setDialog(null)} /> : null}
      {dialog?.kind === 'payment' ? <LoanPaymentForm loan={dialog.account} onClose={() => setDialog(null)} /> : null}
    </div>
  );
}

function DebtCard({
  debt,
  money,
  today,
  onEdit,
  onPay,
}: {
  debt: DebtStatus;
  money: MoneyFormat;
  today: Day;
  onEdit: () => void;
  onPay: () => void;
}) {
  const editors = useEditors();
  const { account } = debt;
  const terms = account.debt_terms!;
  const card = isCard(account.type);
  const schedules = useSchedules().data ?? [];
  const occurrences = useOccurrences(addDays(today, -CARD_DAYS), addDays(today, CARD_DAYS)).data ?? [];
  const mine = new Map(schedules.filter((s) => s.debt?.account_id === account.id).map((s) => [s.id, s]));
  const proposed = occurrences
    .filter((o) => mine.has(o.schedule_id) && mine.get(o.schedule_id)!.debt?.kind !== 'loan_payment')
    .filter((o) => o.date >= (mine.get(o.schedule_id)!.next_date ?? o.date))
    .slice(0, 2);
  const utilization = card && terms.credit_limit ? debt.owed / terms.credit_limit : null;

  return (
    <section className="card debt-card" aria-label={account.name}>
      <div className="card-header">
        <h2>
          {account.name} <small>{ACCOUNT_TYPE_LABELS[account.type]}</small>
        </h2>
        <span className="debt-owed">
          <Amount value={-debt.owed} money={money} bold />
        </span>
      </div>
      <dl className="facts debt-facts">
        <dt>Interest</dt>
        <dd>{terms.annual_rate}% a year</dd>
        <dt>{card ? 'Minimum payment' : 'Monthly payment'}</dt>
        <dd>{debt.minimum_payment != null ? money.amount(debt.minimum_payment) : '—'}</dd>
        {debt.next_due ? (
          <>
            <dt>Next due</dt>
            <dd>{shortDate(debt.next_due)}</dd>
          </>
        ) : null}
        <dt>Paid off</dt>
        <dd title="At the minimum payment, with interest">
          {debt.owed === 0 ? 'Nothing owed' : payoffLabel(debt.payoff)}
          {debt.interest_to_payoff ? (
            <span className="muted small"> · {money.amount(debt.interest_to_payoff)} interest</span>
          ) : null}
          {debt.charges_to_payoff ? (
            <span className="muted small"> · {money.amount(debt.charges_to_payoff)} fixed charges</span>
          ) : null}
        </dd>
        {utilization !== null ? (
          <>
            <dt>Credit used</dt>
            <dd className="progress-cell">
              <ProgressBar fraction={utilization} over={utilization > 0.9} />
              <span className="muted small">{Math.round(utilization * 100)}%</span>
            </dd>
          </>
        ) : null}
      </dl>
      {proposed.length ? (
        <ul className="recurring-list">
          {proposed.map((occurrence) => {
            const schedule = mine.get(occurrence.schedule_id)!;
            const due = occurrence.date <= today;
            return (
              <li key={`${occurrence.schedule_id}-${occurrence.date}`} className={due ? 'due' : undefined}>
                <span className="recurring-date">{shortDate(occurrence.date)}</span>
                <span className="recurring-title">
                  {schedule.debt?.kind === 'card_interest' ? 'Interest charge' : 'Minimum payment'}
                  <small className="muted"> · {due ? 'due' : 'predicted'}</small>
                </span>
                <Amount
                  value={schedule.debt?.kind === 'card_interest' ? -(occurrence.amount ?? 0) : (occurrence.amount ?? 0)}
                  money={money}
                  muted={schedule.debt?.kind !== 'card_interest'}
                />
                <span className="recurring-actions">
                  {due && occurrence.date === schedule.next_date ? (
                    <button
                      type="button"
                      className="button small primary"
                      onClick={() => editors.confirmOccurrence(schedule, occurrence.date)}
                    >
                      Confirm
                    </button>
                  ) : null}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
      <div className="debt-actions">
        <button type="button" className="button small" onClick={onEdit}>
          Edit terms
        </button>
        {isLoan(account.type) ? (
          <button type="button" className="button small" onClick={onPay}>
            Pay
          </button>
        ) : null}
        <Link to={`/accounts/${account.id}`} className="button small">
          Register
        </Link>
      </div>
    </section>
  );
}

function Planner({ debts, money, today }: { debts: readonly DebtStatus[]; money: MoneyFormat; today: Day }) {
  const accounts = byId(useAccounts(true).data);
  const [extraText, setExtraText] = useState('');
  const [rollover, setRollover] = useState<Rollover>('full');
  const [percentText, setPercentText] = useState('50');
  const [lumps, setLumps] = useState<LumpDraft[]>([]);
  const budget = debts.reduce((sum, d) => sum + (d.owed ? (d.minimum_payment ?? 0) : 0), 0);
  const step = 10 ** money.digits;
  const sliderMax = Math.max(budget * 2, 500 * step);

  let extra = 0;
  let extraError: string | null = null;
  try {
    const typed = extraText.trim() ? money.parse(extraText) : 0;
    if (typed < 0) throw new InputError('the extra payment cannot be negative');
    extra = typed;
  } catch (error) {
    extraError = error instanceof Error ? error.message : String(error);
  }
  const percent = Number(percentText.replace(',', '.'));
  const latest = JSON.stringify({
    extra,
    rollover,
    rollover_percent: rollover === 'partial' && percent >= 0 && percent <= 100 ? String(percent) : null,
    lump_sums: lumpSums(lumps, money, today),
    today,
  } satisfies DebtPlanIn);
  const settled = useDebounced(latest, DEBOUNCE_MS);
  const body = useMemo(() => JSON.parse(settled) as DebtPlanIn, [settled]);
  const plans = useDebtPlans(body, debts.some((d) => d.owed > 0)).data;

  return (
    <section className="card planner" aria-label="Payoff planner">
      <div className="card-header">
        <h2>
          Payoff plan <small>snowball or avalanche</small>
        </h2>
      </div>
      <div className="planner-controls">
        <div className="field">
          <label htmlFor="extra-slider">Extra every month</label>
          <div className="extra-control">
            <input
              id="extra-slider"
              type="range"
              min={0}
              max={sliderMax}
              step={step}
              value={Math.min(extra, sliderMax)}
              onChange={(e) => setExtraText(money.plain(Number(e.target.value)))}
            />
            <input
              aria-label="Extra amount"
              className="amount-input"
              inputMode="decimal"
              value={extraText}
              placeholder={money.plain(0)}
              onChange={(e) => setExtraText(e.target.value)}
            />
          </div>
          <div className="hint">
            {extraError ?? (
              <>
                On top of the minimum payments ({money.amount(budget)} a month), so you pay{' '}
                {money.amount(budget + extra)} a month.
              </>
            )}
          </div>
        </div>
        <fieldset className="rollover-options">
          <legend>When a debt is paid off, its payment…</legend>
          {ROLLOVER_CHOICES.map((choice) => (
            <label key={choice.value} className={`rollover-option${rollover === choice.value ? ' active' : ''}`}>
              <input
                type="radio"
                name="rollover"
                value={choice.value}
                checked={rollover === choice.value}
                onChange={() => setRollover(choice.value)}
              />
              <span>
                <strong>{choice.label}</strong>
                <span className="small positive">+ {choice.pros}</span>
                <span className="small negative">− {choice.cons}</span>
              </span>
            </label>
          ))}
          {rollover === 'partial' ? (
            <label className="inline-field">
              Share rolled into the next debt
              <input
                className="amount-input"
                inputMode="decimal"
                value={percentText}
                onChange={(e) => setPercentText(e.target.value)}
                aria-label="Share rolled into the next debt (%)"
              />
              %
            </label>
          ) : null}
        </fieldset>
        <div className="lump-sums">
          <div className="lump-sums-header">
            <strong>One-off payments</strong>
            <button
              type="button"
              className="button small"
              onClick={() => setLumps([...lumps, { date: addDays(today, 30), amount: '' }])}
            >
              + Add
            </button>
          </div>
          {lumps.map((lump, index) => (
            <div className="form-row lump-sum" key={index}>
              <DateField
                label={`Payment ${index + 1} date`}
                value={lump.date}
                onChange={(date) => setLumps(lumps.map((l, i) => (i === index ? { ...l, date } : l)))}
                today={today}
              />
              <AmountField
                label={`Payment ${index + 1} amount`}
                value={lump.amount}
                onChange={(amount) => setLumps(lumps.map((l, i) => (i === index ? { ...l, amount } : l)))}
              />
              <button
                type="button"
                className="icon-button"
                aria-label={`Remove payment ${index + 1}`}
                onClick={() => setLumps(lumps.filter((_, i) => i !== index))}
              >
                ✕
              </button>
            </div>
          ))}
          {!lumps.length ? <p className="muted small">A bonus, a tax refund… Add it to see what it changes.</p> : null}
        </div>
      </div>
      {plans ? <PlanComparison snowball={plans.snowball} avalanche={plans.avalanche} money={money} accounts={accounts} /> : null}
    </section>
  );
}

const STRATEGY_TITLES = {
  snowball: ['Snowball', 'Smallest debt first: quick wins keep you going.'],
  avalanche: ['Avalanche', 'Highest interest first: the least interest overall.'],
} as const;

function PlanComparison({
  snowball,
  avalanche,
  money,
  accounts,
}: {
  snowball: DebtPlan;
  avalanche: DebtPlan;
  money: MoneyFormat;
  accounts: ReadonlyMap<number, Account>;
}) {
  const saving = snowball.total_interest - avalanche.total_interest;
  return (
    <div className="plan-results">
      <div className="plan-compare">
        {[snowball, avalanche].map((plan) => {
          const [title, subtitle] = STRATEGY_TITLES[plan.strategy];
          return (
            <section key={plan.strategy} className="plan" aria-label={title}>
              <h3>{title}</h3>
              <p className="muted small">{subtitle}</p>
              <dl className="facts">
                <dt>Debt-free</dt>
                <dd className="strong">{plan.payoff ? payoffLabel(plan.payoff) : 'Not within 100 years'}</dd>
                {plan.payoff ? (
                  <>
                    <dt>In</dt>
                    <dd>{durationLabel(plan.months.length)}</dd>
                  </>
                ) : null}
                <dt>Interest</dt>
                <dd>{money.amount(plan.total_interest)}</dd>
                {plan.total_charges ? (
                  <>
                    <dt>Fixed charges</dt>
                    <dd>{money.amount(plan.total_charges)}</dd>
                  </>
                ) : null}
                <dt>Total paid</dt>
                <dd>{money.amount(plan.total_paid)}</dd>
              </dl>
              <ol className="payoff-order">
                {plan.debts.map((debt) => (
                  <li key={debt.account_id}>
                    <span>{accounts.get(debt.account_id)?.name ?? `#${debt.account_id}`}</span>
                    <span className="muted small">{payoffLabel(debt.payoff)}</span>
                  </li>
                ))}
              </ol>
            </section>
          );
        })}
      </div>
      <p className="plan-summary">
        {saving > 0
          ? `Avalanche saves ${money.amount(saving)} of interest.`
          : saving < 0
            ? `Snowball saves ${money.amount(-saving)} of interest.`
            : 'Both strategies cost the same interest.'}
      </p>
      <BalanceChart plans={[avalanche, snowball]} />
    </div>
  );
}

const CHART_WIDTH = 600;
const CHART_HEIGHT = 140;

/** Total owed month by month, one line per strategy. */
function BalanceChart({ plans }: { plans: readonly DebtPlan[] }) {
  const lines = useMemo(() => {
    const longest = Math.max(1, ...plans.map((p) => p.months.length));
    const start = Math.max(1, ...plans.map((p) => p.debts.reduce((sum, d) => sum + d.balance, 0)));
    return plans.map((plan) => {
      const points = [start, ...plan.months.map((m) => m.balance)].map((balance, index) => {
        const x = (index / longest) * CHART_WIDTH;
        const y = CHART_HEIGHT - (Math.min(balance, start) / start) * CHART_HEIGHT;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      });
      return { strategy: plan.strategy, points: points.join(' ') };
    });
  }, [plans]);
  return (
    <figure className="debt-chart">
      <svg
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Total owed over time"
      >
        {lines.map((line) => (
          <polyline key={line.strategy} className={`chart-line ${line.strategy}`} points={line.points} />
        ))}
      </svg>
      <figcaption className="muted small">
        <span className="legend snowball">Snowball</span> <span className="legend avalanche">Avalanche</span> · total
        owed over time
      </figcaption>
    </figure>
  );
}
