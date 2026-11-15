import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { renderWithApi } from '../test/render';
import { describeImport, ImportForm } from './ImportForm';
import { PeriodForm } from './PeriodForm';
import { TransactionForm } from './TransactionForm';

const settings = {
  currency: '€',
  minor_digits: 2,
  currency_code: 'EUR',
  cost_method: 'average',
  price_provider: 'yahoo',
  rate_provider: 'yahoo',
};
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
const routes = {
  'GET /api/v1/settings': settings,
  'GET /api/v1/accounts': [account(1, 'Checking'), account(2, 'Savings')],
  'GET /api/v1/categories': [
    { id: 3, name: 'Food', symbol: 'F', parent_id: null, position: 1 },
    { id: 4, name: 'Groceries', symbol: 'G', parent_id: 3, position: 1 },
  ],
  'GET /api/v1/securities': [],
};

describe('PeriodForm', () => {
  it('saves even when nobody listens for the new period', async () => {
    const onClose = vi.fn();
    const { requests } = renderWithApi(<PeriodForm open onClose={onClose} />, routes);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Name'), 'Holiday');
    await user.clear(screen.getByLabelText('Start'));
    await user.type(screen.getByLabelText('Start'), '1/8/2026');
    await user.type(screen.getByLabelText('End'), '+14');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(requests.find((r) => r.method === 'POST')).toEqual({
      method: 'POST',
      path: '/api/v1/periods',
      body: { start: '2026-08-01', end: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/), name: 'Holiday' },
    });
  });
});

describe('TransactionForm', () => {
  it('records a balanced split and blocks an unbalanced one', async () => {
    const onClose = vi.fn();
    const { requests } = renderWithApi(
      <TransactionForm open onClose={onClose} day="2026-11-15" accountId={1} />,
      routes,
    );
    const user = userEvent.setup();
    await screen.findByRole('option', { name: 'Food › Groceries' });
    await user.type(screen.getByLabelText('Amount'), '30');
    await user.click(screen.getByRole('tab', { name: 'Split' }));
    expect(screen.getByLabelText('Line 1 amount')).toHaveValue('-30.00');

    await user.clear(screen.getByLabelText('Line 2 amount'));
    await user.type(screen.getByLabelText('Line 2 amount'), '-20');
    expect(screen.getByText(/differ by €10\.00/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/must match/);
    expect(onClose).not.toHaveBeenCalled();

    await user.selectOptions(screen.getByLabelText('Line 3 account or category'), 'c:4');
    await user.type(screen.getByLabelText('Line 3 amount'), '-10');
    await user.type(screen.getByLabelText('Line 3 memo'), 'fruit');
    expect(screen.getByText(/✓/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const posts = requests.filter((r) => r.method === 'POST');
    expect(posts.at(-1)).toEqual({
      method: 'POST',
      path: '/api/v1/transactions',
      body: {
        date: '2026-11-15',
        description: null,
        notes: null,
        splits: [
          { type: 'account', account_id: 1, amount: -3000, memo: null },
          { type: 'external', amount: -2000, category_id: null, memo: null },
          { type: 'external', amount: -1000, category_id: 4, memo: 'fruit' },
        ],
      },
    });
  });
});

describe('ImportForm', () => {
  const result = {
    replaced: true,
    accounts: 1,
    categories: 2,
    securities: 0,
    prices: 0,
    exchange_rates: 0,
    periods: 0,
    budgets: 0,
    transactions: 5,
    duplicates: 0,
  };

  it('uploads the raw file with the chosen mode', async () => {
    const onClose = vi.fn();
    const file = new File(['SQLite format 3'], 'local.db', { type: 'application/vnd.sqlite3' });
    const { requests } = renderWithApi(<ImportForm file={file} onClose={onClose} />, {
      'POST /api/v1/me/import': result,
    });
    const user = userEvent.setup();
    expect(screen.getByRole('button', { name: 'Merge' })).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Replace my data' }));
    await user.click(screen.getByRole('button', { name: 'Replace everything' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(requests.find((r) => r.method === 'POST')).toEqual({
      method: 'POST',
      path: '/api/v1/me/import',
      query: { mode: 'replace' },
      body: 'SQLite format 3',
    });
    expect(await screen.findByText('Added 5 transactions, 1 account, 2 categories.')).toBeInTheDocument();
  });

  it('describes skipped duplicates', () => {
    expect(describeImport({ ...result, accounts: 0, categories: 0, transactions: 0, duplicates: 1 })).toBe(
      'Nothing new to add. 1 transaction was already there.',
    );
  });
});
