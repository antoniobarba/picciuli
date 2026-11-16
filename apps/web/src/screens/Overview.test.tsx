import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';
import { EditorsProvider } from '../app/editors';
import { longDate } from '../lib/dates';
import { renderWithApi } from '../test/render';
import { Overview } from './Overview';

const account = (id: number, name: string) => ({
  id,
  name,
  type: 'checking',
  account_class: 'asset',
  opening_balance: 0,
  opening_date: null,
  goal: null,
  notes: null,
  position: id,
  closed_on: null,
  is_closed: false,
});
const accounts = [account(1, 'Checking'), account(2, 'Savings')];
const routes = {
  'GET /api/v1/settings': { currency: '€', minor_digits: 2, currency_code: 'EUR' },
  'GET /api/v1/accounts': accounts,
  'GET /api/v1/categories': [],
  'GET /api/v1/transactions': [],
  'GET /api/v1/periods': [],
  'GET /api/v1/securities': [],
};

function renderOverview(overrides: Record<string, unknown> = {}) {
  return renderWithApi(
    <MemoryRouter initialEntries={['/?day=2026-03-10']}>
      <EditorsProvider>
        <Routes>
          <Route index element={<Overview />} />
        </Routes>
      </EditorsProvider>
    </MemoryRouter>,
    { ...routes, ...overrides },
  );
}

describe('Overview', () => {
  it('starts a new transaction on a double-clicked day, while a click only selects it', async () => {
    const user = userEvent.setup();
    renderOverview();
    const day = await screen.findByRole('button', { name: longDate('2026-03-12') });

    await user.click(day);
    expect(day).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('dialog', { name: 'New transaction' })).not.toBeInTheDocument();

    await user.dblClick(day);
    await screen.findByRole('dialog', { name: 'New transaction' });
    expect(screen.getByLabelText('Date')).toHaveValue('2026-03-12');
  });

  it('folds subcategories under their category in the period panel', async () => {
    const user = userEvent.setup();
    const period = { id: 1, name: 'March', start: '2026-03-01', end: '2026-03-31' };
    const category = (id: number, name: string, parent_id: number | null) => ({
      id,
      name,
      symbol: name.slice(0, 2),
      parent_id,
      position: id,
    });
    const total = (c: ReturnType<typeof category>, value: number) => ({ category: c, amount: value, total: value });
    renderOverview({
      'GET /api/v1/periods': [period],
      'GET /api/v1/periods/1/summary': {
        period,
        categories: [
          total(category(1, 'Food', null), -3000),
          total(category(2, 'Groceries', 1), -2000),
          total(category(3, 'Restaurants', 1), -1000),
          total(category(4, 'Salary', null), 50000),
        ],
        uncategorized: 0,
        income: 50000,
        expenses: -3000,
        net: 47000,
        accounts: [],
      },
      'GET /api/v1/periods/1/budget-report': {
        period,
        lines: [],
        total_budget: 0,
        total_actual: 0,
        total_remaining: 0,
      },
    });

    const food = (await screen.findByText('Food')).closest('tr')!;
    expect(screen.getByText('Salary').closest('tr')).not.toHaveAttribute('aria-expanded');
    expect(food).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Groceries')).not.toBeInTheDocument();

    await user.click(food);
    expect(food).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Groceries')).toBeInTheDocument();
    expect(screen.getByText('Restaurants')).toBeInTheDocument();

    await user.click(food);
    expect(screen.queryByText('Groceries')).not.toBeInTheDocument();
  });
});
