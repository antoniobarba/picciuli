import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import type { Account, DebtPlan, Schedule } from '../api/types';
import { EditorsProvider } from '../app/editors';
import { AccountForm } from '../forms/AccountForm';
import { DebtOccurrenceForm } from '../forms/DebtForms';
import { TransactionForm } from '../forms/TransactionForm';
import { renderWithApi } from '../test/render';
import { Debts } from './Debts';

function account(id: number, name: string, type: Account['type'], extra: Partial<Account> = {}): Account {
  return {
    id,
    name,
    type,
    account_class: type === 'checking' ? 'asset' : 'liability',
    opening_balance: 0,
    opening_date: null,
    notes: null,
    position: id,
    closed_on: null,
    is_closed: false,
    debt_terms: null,
    ...extra,
  };
}

const terms = {
  payment_percent: null,
  due_day: 15,
  statement_day: null,
  credit_limit: null,
  payment_account_id: 1,
  interest_category_id: 5,
  propose_interest: false,
  propose_minimum: false,
  charges: [],
};
const checking = account(1, 'Checking', 'checking');
const visa = account(2, 'Visa', 'credit_card', {
  debt_terms: {
    ...terms,
    annual_rate: '19.9',
    payment: 2500,
    payment_percent: '3',
    statement_day: 1,
    credit_limit: 200000,
    propose_interest: true,
    propose_minimum: true,
  },
});
const insurance = { amount: 709, category_id: 6, label: 'Insurance' };
const mortgage = account(3, 'Mortgage', 'mortgage', {
  debt_terms: { ...terms, annual_rate: '3', payment: 80000, charges: [insurance] },
});

function plan(strategy: DebtPlan['strategy'], interest: number, order: number[]): DebtPlan {
  return {
    strategy,
    rollover: 'full',
    rollover_percent: null,
    extra: 0,
    monthly_budget: 83000,
    debts: order.map((id, index) => ({
      account_id: id,
      order: index + 1,
      balance: 100000,
      payoff: `${2027 + index}-06-01`,
      interest: 0,
      paid: 0,
      charges: 0,
    })),
    months: [{ month: '2026-12-01', payment: 83000, interest: 1000, balance: 50000, balances: [0, 50000] }],
    payoff: '2040-01-01',
    total_interest: interest,
    total_paid: 1000000 + interest,
    total_charges: 0,
  };
}

const routes = {
  'GET /api/v1/settings': { currency: '€', minor_digits: 2, currency_code: 'EUR' },
  'GET /api/v1/accounts': [checking, visa, mortgage],
  'GET /api/v1/categories': [
    { id: 5, name: 'Interest', symbol: 'INT', parent_id: null, position: 1 },
    { id: 6, name: 'Insurance', symbol: 'INS', parent_id: null, position: 2 },
  ],
  'GET /api/v1/securities': [],
  'GET /api/v1/schedules': [],
  'GET /api/v1/schedules/occurrences': [],
  'GET /api/v1/debts': [
    {
      account: visa,
      balance: -150000,
      owed: 150000,
      minimum_payment: 4500,
      next_due: '2026-12-15',
      payoff: '2030-04-01',
      interest_to_payoff: 61000,
      charges_to_payoff: 0,
    },
    {
      account: mortgage,
      balance: -15000000,
      owed: 15000000,
      minimum_payment: 80000,
      next_due: '2026-12-15',
      payoff: null,
      interest_to_payoff: null,
      charges_to_payoff: null,
    },
  ],
  'POST /api/v1/debts/plan': { snowball: plan('snowball', 50000, [2, 3]), avalanche: plan('avalanche', 40000, [2, 3]) },
  'GET /api/v1/debts/3/payment-split': {
    account_id: 3,
    date: '2026-11-05',
    amount: 80000,
    owed: 15000000,
    interest: 37500,
    principal: 41791,
    charges: [insurance],
  },
};

describe('Debts screen', () => {
  it('shows every debt and compares the two strategies', async () => {
    const user = userEvent.setup();
    const { requests } = renderWithApi(
      <MemoryRouter>
        <EditorsProvider>
          <Debts />
        </EditorsProvider>
      </MemoryRouter>,
      routes,
    );
    const card = await screen.findByRole('region', { name: 'Visa' });
    expect(card).toHaveTextContent('-€1,500.00');
    expect(card).toHaveTextContent('19.9% a year');
    expect(card).toHaveTextContent('Apr 2030');
    expect(card).toHaveTextContent('75%');
    expect(within(screen.getByRole('region', { name: 'Mortgage' })).getByText('—')).toBeInTheDocument();
    expect(await screen.findByText('Avalanche saves €100.00 of interest.')).toBeInTheDocument();
    expect(screen.getByText(/so you pay €845\.00 a month/)).toBeInTheDocument();

    await user.type(screen.getByLabelText('Extra amount'), '100');
    await user.click(screen.getByLabelText(/Free it up/));
    await waitFor(() =>
      expect(requests.filter((r) => r.path === '/api/v1/debts/plan').at(-1)?.body).toMatchObject({
        extra: 10000,
        rollover: 'none',
        rollover_percent: null,
        lump_sums: [],
      }),
    );
  });
});

describe('AccountForm', () => {
  it('creates a credit card from what you owe, with its terms and a new interest category', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    const { requests } = renderWithApi(<AccountForm account={null} onClose={onClose} />, routes);
    await user.type(screen.getByLabelText('Name'), 'Amex');
    await user.selectOptions(screen.getByLabelText('Type'), 'Credit card');
    await user.type(screen.getByLabelText('How much do you owe?'), '1500');
    await user.click(screen.getByLabelText('Track the interest rate and the payments'));
    await user.type(screen.getByLabelText('Interest rate (% a year)'), '19.9');
    await user.type(screen.getByLabelText('Due day'), '15');
    await user.type(screen.getByLabelText('Statement day'), '1');
    await user.type(screen.getByLabelText('Minimum payment (%)'), '3');
    await user.type(screen.getByLabelText('At least'), '25');
    expect(screen.getByLabelText('New category name')).toHaveValue('Amex interest');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(requests.find((r) => r.method === 'POST')?.body).toEqual({
      name: 'Amex',
      type: 'credit_card',
      notes: null,
      opening_balance: -150000,
      opening_date: null,
      debt_terms: {
        annual_rate: '19.9',
        payment: 2500,
        payment_percent: '3',
        due_day: 15,
        statement_day: 1,
        credit_limit: null,
        payment_account_id: null,
        interest_category_id: null,
        new_interest_category: 'Amex interest',
        propose_interest: true,
        propose_minimum: true,
        charges: [],
      },
    });
  });

  it('creates a loan with a fixed charge in every payment', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    const { requests } = renderWithApi(<AccountForm account={null} onClose={onClose} />, routes);
    await user.type(screen.getByLabelText('Name'), 'Car loan');
    await user.selectOptions(screen.getByLabelText('Type'), 'Loan');
    await user.type(screen.getByLabelText('How much do you owe?'), '10000');
    await user.click(screen.getByLabelText('Track the interest rate and the payments'));
    await user.type(screen.getByLabelText('Interest rate (% a year)'), '8.99');
    await user.type(screen.getByLabelText('Monthly payment'), '133.71');
    await user.click(screen.getByRole('button', { name: '+ Fixed charge' }));
    await user.type(screen.getByLabelText('Charge'), 'Insurance');
    await user.type(screen.getByLabelText('Charge amount'), '7.09');
    await screen.findAllByRole('option', { name: 'Insurance' });
    await user.selectOptions(screen.getByLabelText('Charge category'), 'Insurance');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(requests.find((r) => r.method === 'POST')?.body).toMatchObject({
      type: 'loan',
      debt_terms: { payment: 13371, charges: [insurance] },
    });
  });
});

describe('DebtOccurrenceForm', () => {
  it('records the predicted minimum payment from the usual account', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    const minimum: Schedule = {
      id: 9,
      description: 'Visa minimum payment',
      notes: null,
      splits: [],
      frequency: 'monthly',
      every: 1,
      day_of_month: 15,
      next_date: '2026-11-15',
      end: null,
      remaining: null,
      mode: 'confirm',
      paused: false,
      last_error: null,
      kind: 'transfer',
      net_amount: 0,
      is_finished: false,
      debt: { kind: 'card_min_payment', account_id: 2, interest_category_id: null },
    };
    const { requests } = renderWithApi(<DebtOccurrenceForm schedule={minimum} date="2026-11-15" onClose={onClose} />, {
      ...routes,
      'GET /api/v1/schedules/occurrences': [
        {
          schedule_id: 9,
          date: '2026-11-15',
          amount: 4500,
          splits: [
            { type: 'account', account_id: 1, amount: -4500 },
            { type: 'account', account_id: 2, amount: 4500 },
          ],
        },
      ],
    });
    await waitFor(() => expect(screen.getByLabelText('Amount')).toHaveValue('45.00'));
    await waitFor(() => expect(screen.getByLabelText('Paid from')).toHaveValue('1'));
    await user.click(screen.getByRole('button', { name: 'Record' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(requests.find((r) => r.method === 'POST')).toEqual({
      method: 'POST',
      path: '/api/v1/schedules/9/post',
      body: { date: '2026-11-15', from_account_id: 1 },
    });
  });
});

describe('TransactionForm', () => {
  it('splits a transfer into a loan into principal, interest and fixed charges', async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    const { requests } = renderWithApi(<TransactionForm open onClose={onClose} day="2026-11-05" />, routes);
    await user.click(await screen.findByRole('tab', { name: 'Transfer' }));
    await screen.findAllByRole('option', { name: 'Mortgage' });
    await user.selectOptions(screen.getByLabelText('To'), 'Mortgage');
    await user.type(screen.getByLabelText('Amount'), '800');
    await user.click(await screen.findByRole('button', { name: 'Split into principal and interest' }));
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(requests.find((r) => r.method === 'POST')?.body).toMatchObject({
      date: '2026-11-05',
      splits: [
        { type: 'account', account_id: 1, amount: -80000, memo: null },
        { type: 'account', account_id: 3, amount: 41791, memo: null },
        { type: 'external', amount: -37500, category_id: 5, memo: 'Interest' },
        { type: 'external', amount: -709, category_id: 6, memo: 'Insurance' },
      ],
    });
  });
});
