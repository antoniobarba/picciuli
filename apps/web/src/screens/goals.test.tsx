import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import type { Account, GoalProgress, GoalReport } from '../api/types';
import { renderWithApi } from '../test/render';
import { Goals } from './Goals';

function account(id: number, name: string, type: Account['type']): Account {
  return {
    id,
    name,
    type,
    account_class: 'asset',
    opening_balance: 0,
    opening_date: null,
    notes: null,
    position: id,
    closed_on: null,
    is_closed: false,
    debt_terms: null,
  };
}

const savings = account(1, 'Savings', 'savings');
const broker = account(2, 'Broker', 'investment');

function progress(id: number, name: string, extra: Partial<GoalProgress>, goal: Partial<GoalProgress['goal']> = {}): GoalProgress {
  return {
    goal: {
      id,
      account_id: 1,
      name,
      target_amount: 120000,
      saved_amount: 30000,
      target_date: null,
      priority: 'normal',
      ...goal,
    },
    remaining: 90000,
    status: 'undated',
    months_left: null,
    monthly_amount: null,
    ...extra,
  };
}

const report: GoalReport = {
  today: '2026-11-16',
  accounts: [
    {
      account: savings,
      balance: 40000,
      assigned: 50000,
      unassigned: 0,
      shortfall: 10000,
      goals: [
        progress(
          1,
          'Holiday',
          { status: 'scheduled', months_left: 3, monthly_amount: 30000 },
          { target_date: '2027-01-31', priority: 'high' },
        ),
        progress(2, 'Car', { status: 'overdue', remaining: 100000 }, { saved_amount: 20000, target_date: '2026-01-01' }),
      ],
    },
  ],
};

const routes = {
  'GET /api/v1/settings': { currency: '€', minor_digits: 2, currency_code: 'EUR' },
  'GET /api/v1/accounts': [savings, broker],
  'GET /api/v1/accounts/balances': [{ account: savings, balance: 40000 }],
  'GET /api/v1/goals/report': report,
};

function renderGoals(overrides: Record<string, unknown> = {}) {
  return renderWithApi(
    <MemoryRouter>
      <Goals />
    </MemoryRouter>,
    { ...routes, ...overrides },
  );
}

describe('Goals screen', () => {
  it('shows each goal with its monthly amount and warns about over-assigned money', async () => {
    renderGoals();
    const holiday = await screen.findByRole('region', { name: 'Holiday' });
    expect(holiday).toHaveTextContent('€300.00 of €1,200.00');
    expect(holiday).toHaveTextContent('25%');
    expect(holiday).toHaveTextContent('High');
    expect(holiday).toHaveTextContent('31 Jan 2027');
    expect(holiday).toHaveTextContent('€300.00 a month · 3 months');
    expect(screen.getByRole('region', { name: 'Car' })).toHaveTextContent('Overdue: €1,000.00 still missing');
    expect(screen.getByText(/These goals claim €100\.00 more than the account holds\./)).toHaveClass('goal-warning');
  });

  it('creates a goal and warns before assigning more than the balance', async () => {
    const user = userEvent.setup();
    const { requests } = renderGoals();
    await screen.findByRole('region', { name: 'Holiday' });
    await user.click(screen.getAllByRole('button', { name: '+ New goal' })[0]!);
    const dialog = await screen.findByRole('dialog');
    const accountOptions = within(within(dialog).getByLabelText('Account')).getAllByRole('option');
    expect(accountOptions.map((o) => o.textContent)).toEqual(['Choose…', 'Savings']);
    await user.type(within(dialog).getByLabelText('Name'), 'Emergency');
    await user.selectOptions(within(dialog).getByLabelText('Account'), 'Savings');
    await user.type(within(dialog).getByLabelText('Target'), '5000');
    await user.type(within(dialog).getByLabelText('Saved so far'), '10');
    expect(within(dialog).getByRole('note')).toHaveTextContent('would claim €110.00 more than its balance today');
    await user.type(within(dialog).getByLabelText('Target date'), '2027-06-30');
    await user.selectOptions(within(dialog).getByLabelText('Priority'), 'Low');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(requests.find((r) => r.method === 'POST')).toMatchObject({
        path: '/api/v1/goals',
        body: {
          account_id: 1,
          name: 'Emergency',
          target_amount: 500000,
          saved_amount: 1000,
          target_date: '2027-06-30',
          priority: 'low',
        },
      }),
    );
  });

  it('explains how to start without goals', async () => {
    renderGoals({ 'GET /api/v1/goals/report': { today: '2026-11-16', accounts: [] } });
    expect(await screen.findByText(/One account can hold several goals/)).toBeInTheDocument();
  });

  it('offers to retry when the goals cannot be loaded', async () => {
    const missing = Object.fromEntries(Object.entries(routes).filter(([key]) => key !== 'GET /api/v1/goals/report'));
    renderWithApi(
      <MemoryRouter>
        <Goals />
      </MemoryRouter>,
      missing,
    );
    expect(await screen.findByText('The goals could not be loaded.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});
