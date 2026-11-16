import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { EditorsProvider } from '../app/editors';
import { renderWithApi } from '../test/render';
import { Reports } from './Reports';

const account = (id: number, name: string, type: string, account_class = 'asset') => ({
  id,
  name,
  type,
  account_class,
  opening_balance: 0,
  opening_date: null,
  notes: null,
  position: id,
  closed_on: null,
  is_closed: false,
});
const point = (start: string, extra: Record<string, unknown>) => ({
  start,
  end: start,
  period_id: null,
  partial: false,
  income: 0,
  expenses: 0,
  flows: [],
  balances: [],
  assets: 0,
  liabilities: 0,
  net_worth: 0,
  ...extra,
});
const routes = {
  'GET /api/v1/settings': { currency: '€', minor_digits: 2, currency_code: 'EUR' },
  'GET /api/v1/accounts': [
    account(1, 'Checking', 'checking'),
    account(2, 'Savings', 'savings'),
    account(3, 'Loan', 'loan', 'liability'),
  ],
  'GET /api/v1/categories': [
    { id: 1, name: 'Food', parent_id: null, symbol: 'FOO', position: 1 },
    { id: 2, name: 'Fun', parent_id: null, symbol: 'FUN', position: 2 },
    { id: 3, name: 'Salary', parent_id: null, symbol: 'SAL', position: 3 },
  ],
  'GET /api/v1/periods': [{ id: 7, name: 'March', start: '2026-03-01', end: '2026-03-31' }],
  'GET /api/v1/reports/history': [
    point('2026-01-01', {
      income: 200000,
      expenses: -50000,
      flows: [
        { category_id: 1, amount: -40000 },
        { category_id: 2, amount: -10000 },
        { category_id: 3, amount: 200000 },
      ],
      balances: [
        { account_id: 1, balance: 100000, value: 100000 },
        { account_id: 2, balance: 50000, value: 50000 },
        { account_id: 3, balance: -90000, value: -90000 },
      ],
      assets: 150000,
      liabilities: -90000,
      net_worth: 60000,
    }),
    point('2026-02-01', {
      partial: true,
      income: 200000,
      expenses: -30000,
      flows: [{ category_id: 1, amount: -30000 }],
      balances: [
        { account_id: 1, balance: 220000, value: 220000 },
        { account_id: 2, balance: 70000, value: 70000 },
        { account_id: 3, balance: -80000, value: -80000 },
      ],
      assets: 290000,
      liabilities: -80000,
      net_worth: 210000,
    }),
  ],
};

const render = (url = '/reports?view=history', overrides: Record<string, unknown> = {}) =>
  renderWithApi(
    <MemoryRouter initialEntries={[url]}>
      <EditorsProvider>
        <Reports />
      </EditorsProvider>
    </MemoryRouter>,
    { ...routes, ...overrides },
  );

const figure = (card: string, label: string) =>
  within(screen.getByRole('region', { name: card })).getByText(label).nextElementSibling;

describe('history', () => {
  it('sums up net worth, cash flow, debts and savings over the months', async () => {
    const { requests } = render();

    expect(await screen.findByText('Jan 2026 – Feb 2026')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'History' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('The last month counts up to today.')).toBeInTheDocument();
    expect(figure('Net worth', 'Now')).toHaveTextContent('€2,100.00');
    expect(figure('Net worth', 'Change')).toHaveTextContent('+€1,500.00');
    expect(figure('Income and expenses', 'Expenses')).toHaveTextContent('-€800.00');
    expect(figure('Income and expenses', 'Left over')).toHaveTextContent('+€3,200.00');
    expect(figure('Debts', 'Owed now')).toHaveTextContent('€800.00');
    expect(figure('Debts', 'Paid off')).toHaveTextContent('€100.00');
    // Checking is not savings.
    expect(figure('Savings', 'Now')).toHaveTextContent('€700.00');
    expect(requests).toContainEqual(
      expect.objectContaining({
        path: '/api/v1/reports/history',
        query: expect.objectContaining({ by: 'month', count: '12', offset: '0' }),
      }),
    );
  });

  it('ranks the categories by spending and lets you pick which to chart', async () => {
    const user = userEvent.setup();
    render();

    const list = await screen.findByRole('list', { name: 'Categories' });
    const items = within(list).getAllByRole('listitem');
    expect(items.map((item) => item.textContent)).toEqual(['Food€700.00', 'Fun€100.00', 'Salary-€2,000.00']);
    const fun = within(list).getByRole('checkbox', { name: 'Fun' });
    expect(fun).toBeChecked();
    await user.click(fun);
    expect(fun).not.toBeChecked();
    expect(within(list).getByRole('checkbox', { name: 'Food' })).toBeChecked();
  });

  it('steps back by the span and groups by periods', async () => {
    const user = userEvent.setup();
    const { requests } = render();

    await user.click(await screen.findByRole('button', { name: 'Earlier months' }));
    expect(requests).toContainEqual(
      expect.objectContaining({ query: expect.objectContaining({ by: 'month', offset: '12' }) }),
    );
    await user.click(screen.getByRole('button', { name: 'Later months' }));
    expect(screen.getByRole('button', { name: 'Later months' })).toBeDisabled();

    await user.selectOptions(screen.getByRole('combobox', { name: 'Span' }), '24');
    await user.click(screen.getByRole('tab', { name: 'Periods' }));
    expect(requests).toContainEqual(
      expect.objectContaining({ query: expect.objectContaining({ by: 'period', count: '24', offset: '0' }) }),
    );
    // Only one period: nothing earlier.
    expect(await screen.findByRole('button', { name: 'Earlier periods' })).toBeDisabled();
  });

  it('switches between the cash-flow report and the history', async () => {
    const user = userEvent.setup();
    render('/reports');

    expect(await screen.findByRole('region', { name: 'Report filters' })).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'History' }));
    expect(await screen.findByRole('region', { name: 'Net worth' })).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Cash flow' }));
    expect(await screen.findByRole('region', { name: 'Report filters' })).toBeInTheDocument();
  });
});
