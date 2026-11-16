import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
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

function ReportsProbe() {
  const location = useLocation();
  return <p>Reports at {location.search}</p>;
}

function renderOverview(overrides: Record<string, unknown> = {}) {
  return renderWithApi(
    <MemoryRouter initialEntries={['/?day=2026-03-10']}>
      <EditorsProvider>
        <Routes>
          <Route index element={<Overview />} />
          <Route path="reports" element={<ReportsProbe />} />
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

  it('links each category row to its report for the period on the whole portfolio', async () => {
    const user = userEvent.setup();
    const period = { id: 1, name: 'March', start: '2026-03-01', end: '2026-03-31' };
    const category = (id: number, name: string, parent_id: number | null) => ({
      id,
      name,
      symbol: name.slice(0, 2),
      parent_id,
      position: id,
    });
    const food = category(1, 'Food', null);
    const groceries = category(2, 'Groceries', 1);
    const fun = category(3, 'Fun', null);
    renderOverview({
      'GET /api/v1/categories': [food, groceries, fun],
      'GET /api/v1/periods': [period],
      'GET /api/v1/periods/1/summary': {
        period,
        categories: [
          { category: food, amount: 0, total: -2000 },
          { category: groceries, amount: -2000, total: -2000 },
        ],
        uncategorized: -500,
        income: 0,
        expenses: -2500,
        net: -2500,
        accounts: [],
      },
      'GET /api/v1/periods/1/budget-report': { period, lines: [], total_budget: 0, total_actual: 0, total_remaining: 0 },
    });

    const row = (await screen.findByText('Food')).closest('tr')!;
    expect(screen.getByRole('link', { name: 'Report on Uncategorized' })).toHaveAttribute(
      'href',
      '/reports?period=1&uncategorized=1',
    );
    await user.click(row);
    expect(screen.getByRole('link', { name: 'Report on Groceries' })).toHaveAttribute(
      'href',
      '/reports?period=1&categories=2',
    );

    await user.click(screen.getByRole('link', { name: 'Report on Food' }));
    expect(await screen.findByText('Reports at ?period=1&categories=1')).toBeInTheDocument();
  });

  it('totals the budgets, then the spending of whole categories no budget covers', async () => {
    const period = { id: 1, name: 'March', start: '2026-03-01', end: '2026-03-31' };
    const category = (id: number, name: string, parent_id: number | null) => ({
      id,
      name,
      symbol: name.slice(0, 2),
      parent_id,
      position: id,
    });
    const home = category(1, 'Home', null);
    const utilities = category(2, 'Utilities', 1);
    const food = category(3, 'Food', null);
    const groceries = category(4, 'Groceries', 3);
    const restaurants = category(5, 'Restaurants', 3);
    const refunds = category(6, 'Refunds', 3);
    const salary = category(7, 'Salary', null);
    const flow = (c: ReturnType<typeof category>, amount: number, total = amount) => ({ category: c, amount, total });
    const line = (c: ReturnType<typeof category>, amount: number, actual: number) => ({
      budget: { id: c.id, period_id: 1, category_id: c.id, amount },
      category: c,
      actual,
      remaining: amount + actual,
    });
    renderOverview({
      'GET /api/v1/periods': [period],
      'GET /api/v1/periods/1/summary': {
        period,
        categories: [
          flow(home, -10000, -15000),
          flow(utilities, -5000),
          flow(food, -1000, -33000),
          flow(groceries, -30000),
          flow(restaurants, -4000),
          flow(refunds, 2000),
          flow(salary, 500000),
        ],
        uncategorized: -700,
        income: 502000,
        expenses: -50700,
        net: 451300,
        accounts: [],
      },
      'GET /api/v1/periods/1/budget-report': {
        period,
        lines: [line(home, 20000, -15000), line(groceries, 25000, -30000)],
        total_budget: 45000,
        total_actual: -45000,
        total_remaining: 0,
      },
    });

    // Home's budget covers Utilities; Groceries' does not cover the rest of Food.
    const budgets = (await screen.findByText('Budgets')).closest('tr')!;
    expect(budgets).toHaveTextContent('Budgets-€450.00€450.00€0.00');
    expect(screen.getByText('Unbudgeted').closest('tr')).toHaveTextContent('Unbudgeted-€57.00');
  });
});
