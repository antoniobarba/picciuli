import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { describe, expect, it } from 'vitest';
import { EditorsProvider } from '../app/editors';
import { renderWithApi } from '../test/render';
import { Budgets } from './Budgets';
import { Categories } from './Categories';
import { Periods } from './Periods';

const category = (id: number, name: string, parent_id: number | null, position: number) => ({
  id,
  name,
  parent_id,
  symbol: name.slice(0, 3).toUpperCase(),
  position,
});
const food = category(1, 'Food', null, 1);
const groceries = category(2, 'Groceries', 1, 1);
const salary = category(3, 'Salary', null, 2);
const period = { id: 7, name: 'Since 2000', start: '2000-01-01', end: null };
const line = { budget: { id: 9, category_id: 1, period_id: 7, amount: 50000 }, category: food, actual: -4200, remaining: 45800 };
const transaction = (id: number, description: string, splits: unknown[], net_amount: number) => ({
  id,
  date: '2026-03-10',
  description,
  notes: null,
  splits,
  kind: 'expense',
  net_amount,
});
const transactions = [
  transaction(
    1,
    'Market',
    [
      { type: 'account', account_id: 1, amount: -3000 },
      { type: 'external', amount: 2000, category_id: 2 },
      { type: 'external', amount: -5000, category_id: 3 },
    ],
    -3000,
  ),
  transaction(
    2,
    'Bakery',
    [
      { type: 'account', account_id: 1, amount: 1200 },
      { type: 'external', amount: -1200, category_id: 1 },
    ],
    -1200,
  ),
];
const routes = {
  'GET /api/v1/settings': { currency: '€', minor_digits: 2, currency_code: 'EUR' },
  'GET /api/v1/accounts': [],
  'GET /api/v1/categories': [food, groceries, salary],
  'GET /api/v1/periods': [period],
  'GET /api/v1/periods/7/budget-report': {
    period,
    lines: [line],
    total_budget: 50000,
    total_actual: -4200,
    total_remaining: 45800,
  },
  'GET /api/v1/transactions': transactions,
};

const render = (ui: ReactNode) => renderWithApi(<EditorsProvider>{ui}</EditorsProvider>, routes);

describe('item transactions', () => {
  it('opens the transactions of a category, with its subcategories, total and remaining budget', async () => {
    const user = userEvent.setup();
    const { requests } = render(<Categories />);
    await user.click(await screen.findByText('Food'));

    const dialog = await screen.findByRole('dialog', { name: 'Food' });
    expect(within(dialog).getByText('Market')).toBeInTheDocument();
    expect(within(dialog).getByText('Bakery')).toBeInTheDocument();
    // Only the splits in Food and Groceries count: 20.00 − 12.00.
    expect(within(dialog).getByText('Total').parentElement).toHaveTextContent('Total €8.00');
    expect(await within(dialog).findByText('€458.00')).toBeInTheDocument();
    expect(requests).toContainEqual(
      expect.objectContaining({
        path: '/api/v1/transactions',
        query: { category_id: '1', include_subcategories: 'true', newest_first: 'true' },
      }),
    );
  });

  it('keeps Edit in the row menu and leaves the drag handle inert', async () => {
    const user = userEvent.setup();
    render(<Categories />);
    await user.click(await screen.findByRole('button', { name: 'Reorder Food' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: 'Actions' })[0]!);
    await user.click(await screen.findByRole('menuitem', { name: /Edit/ }));
    expect(await screen.findByRole('dialog', { name: 'Edit Food' })).toBeInTheDocument();
  });

  it('opens the transactions of a budget within its period', async () => {
    const user = userEvent.setup();
    const { requests } = render(<Budgets />);
    await user.click(await screen.findByText('Food'));

    const dialog = await screen.findByRole('dialog', { name: 'Food · Since 2000' });
    expect(within(dialog).getByText('Remaining').parentElement).toHaveTextContent('Remaining €458.00');
    expect(requests).toContainEqual(
      expect.objectContaining({
        path: '/api/v1/transactions',
        query: { category_id: '1', include_subcategories: 'true', start: '2000-01-01', newest_first: 'true' },
      }),
    );
  });

  it('opens the transactions of a period with Enter on its row', async () => {
    const user = userEvent.setup();
    render(<Periods />);
    (await screen.findByText('Since 2000')).closest('tr')!.focus();
    await user.keyboard('{Enter}');

    const dialog = await screen.findByRole('dialog', { name: 'Since 2000' });
    expect(within(dialog).getByText('Total').parentElement).toHaveTextContent('Total -€42.00');
    expect(within(dialog).getByText('Budget remaining').parentElement).toHaveTextContent('€458.00');
  });
});

describe('subcategories', () => {
  it('are indented rows without a tree glyph', async () => {
    render(<Categories />);
    const row = (await screen.findByText('Groceries')).closest('tr')!;
    expect(row).toHaveClass('child');
    expect(row).not.toHaveTextContent('└');
  });

  it('are named after their parent in the budget category picker', async () => {
    const user = userEvent.setup();
    render(<Budgets />);
    await user.click(await screen.findByRole('button', { name: '+ New budget' }));
    const picker = await screen.findByLabelText('Category');
    expect(within(picker).getByRole('option', { name: 'Food › Groceries' })).toBeInTheDocument();
  });
});
