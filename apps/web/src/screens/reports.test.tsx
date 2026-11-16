import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { EditorsProvider } from '../app/editors';
import { renderWithApi } from '../test/render';
import { Reports } from './Reports';

const category = (id: number, name: string, parent_id: number | null, position: number) => ({
  id,
  name,
  parent_id,
  symbol: name.slice(0, 3).toUpperCase(),
  position,
});
const transaction = (id: number, description: string, splits: unknown[]) => ({
  id,
  date: '2026-03-10',
  description,
  notes: null,
  splits,
  kind: 'expense',
  net_amount: 0,
});
const routes = {
  'GET /api/v1/settings': { currency: '€', minor_digits: 2, currency_code: 'EUR' },
  'GET /api/v1/accounts': [],
  'GET /api/v1/categories': [
    category(1, 'Food', null, 1),
    category(2, 'Groceries', 1, 1),
    category(3, 'Fun', null, 2),
    category(4, 'Salary', null, 3),
  ],
  'GET /api/v1/periods': [{ id: 7, name: 'March', start: '2026-03-01', end: '2026-03-31' }],
  'GET /api/v1/transactions': [
    transaction(1, 'Market', [
      { type: 'account', account_id: 1, amount: -4000 },
      { type: 'external', amount: -3000, category_id: 2, memo: 'veg' },
      { type: 'external', amount: -1000, category_id: 3 },
    ]),
    transaction(2, 'Bakery', [
      { type: 'account', account_id: 1, amount: -1000 },
      { type: 'external', amount: -1000, category_id: 1 },
    ]),
    transaction(3, 'Pay', [
      { type: 'account', account_id: 1, amount: 90000 },
      { type: 'external', amount: 90000, category_id: 4 },
    ]),
  ],
};

const render = () => renderWithApi(<EditorsProvider><Reports /></EditorsProvider>, routes);

describe('reports', () => {
  it('lists the splits of the chosen categories in a period, with totals and a pie chart', async () => {
    const user = userEvent.setup();
    const { requests } = render();
    expect(await screen.findByText('Choose one or more categories to see their transactions.')).toBeInTheDocument();

    // A top-level category brings its subcategories along.
    await user.click(await screen.findByRole('checkbox', { name: 'Food' }));
    expect(screen.getByRole('checkbox', { name: 'Groceries' })).toBeChecked();

    const list = await screen.findByRole('list', { name: 'Splits' });
    expect(within(list).getByText('Market')).toBeInTheDocument();
    expect(within(list).getByText('Bakery')).toBeInTheDocument();
    expect(within(list).queryByText('Pay')).not.toBeInTheDocument();
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByText('Total').parentElement).toHaveTextContent('Total -€40.00');

    const legend = screen.getByRole('list', { name: 'Category totals' });
    expect(within(legend).getByText('Food').parentElement).toHaveTextContent('Food25%-€10.00');
    expect(within(legend).getByText('Food › Groceries').parentElement).toHaveTextContent('75%-€30.00');
    expect(screen.getByRole('img', { name: 'Total of each category' }).querySelectorAll('path')).toHaveLength(2);
    expect(requests).toContainEqual(
      expect.objectContaining({
        path: '/api/v1/transactions',
        query: { start: '2026-03-01', end: '2026-03-31', newest_first: 'true' },
      }),
    );
  });

  it('uses a range of days typed by hand', async () => {
    const user = userEvent.setup();
    const { requests } = render();
    await user.click(await screen.findByRole('checkbox', { name: 'Fun' }));
    await user.click(screen.getByRole('tab', { name: 'Days' }));
    const from = screen.getByLabelText('From');
    const to = screen.getByLabelText('To');
    await user.clear(from);
    await user.type(from, '2026-03-05');
    await user.clear(to);
    await user.type(to, '2026-03-02');
    expect(screen.getByRole('alert')).toHaveTextContent('The first day comes after the last day.');

    await user.clear(to);
    await user.type(to, '2026-03-20');
    const list = await screen.findByRole('list', { name: 'Splits' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(screen.getByText('Total').parentElement).toHaveTextContent('Total -€10.00');
    expect(requests).toContainEqual(
      expect.objectContaining({
        path: '/api/v1/transactions',
        query: { start: '2026-03-05', end: '2026-03-20', newest_first: 'true' },
      }),
    );
  });
});
