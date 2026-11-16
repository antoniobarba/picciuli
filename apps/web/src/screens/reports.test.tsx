import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
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
const routes = {
  'GET /api/v1/settings': { currency: '€', minor_digits: 2, currency_code: 'EUR' },
  'GET /api/v1/accounts': [account(1, 'Checking'), account(2, 'Card'), account(3, 'Mortgage')],
  'GET /api/v1/categories': [
    category(1, 'Food', null, 1),
    category(2, 'Groceries', 1, 1),
    category(3, 'Fun', null, 2),
    category(4, 'Salary', null, 3),
    category(5, 'Interest', null, 4),
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
    transaction(4, 'Mortgage payment', [
      { type: 'account', account_id: 1, amount: -10000 },
      { type: 'account', account_id: 3, amount: 9000 },
      { type: 'external', amount: -1000, category_id: 5 },
    ]),
    transaction(5, 'Card bill', [
      { type: 'account', account_id: 1, amount: -2000 },
      { type: 'account', account_id: 2, amount: 2000 },
    ]),
  ],
};

const render = (url = '/reports', overrides: Record<string, unknown> = {}) =>
  renderWithApi(
    <MemoryRouter initialEntries={[url]}>
      <EditorsProvider>
        <Reports />
      </EditorsProvider>
    </MemoryRouter>,
    { ...routes, ...overrides },
  );

describe('reports', () => {
  it('reports the splits without a category, ticked like a category', async () => {
    const user = userEvent.setup();
    render('/reports?period=7&uncategorized=1', {
      'GET /api/v1/transactions': [
        ...routes['GET /api/v1/transactions'],
        transaction(6, 'Parking', [
          { type: 'account', account_id: 1, amount: -500 },
          { type: 'external', amount: -500, category_id: null },
        ]),
      ],
    });

    const box = await screen.findByRole('checkbox', { name: /^Uncategorized/ });
    expect(box).toBeChecked();
    const list = await screen.findByRole('list', { name: 'Splits' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(within(list).getByText('Parking')).toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Category totals' })).getByText('Uncategorized').parentElement).toHaveTextContent(
      'Uncategorized100%-€5.00',
    );

    await user.click(screen.getByRole('button', { name: 'None' }));
    expect(box).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: 'All' }));
    expect(box).toBeChecked();
  });

  it('opens on the period and categories in the URL, for the whole portfolio', async () => {
    const { requests } = render('/reports?period=7&categories=1,2', {
      'GET /api/v1/periods': [
        { id: 7, name: 'March', start: '2026-03-01', end: '2026-03-31' },
        { id: 8, name: 'April', start: '2026-04-01', end: '2026-04-30' },
      ],
    });

    expect(await screen.findByRole('combobox', { name: 'Period' })).toHaveDisplayValue(/^March/);
    expect(await screen.findByRole('checkbox', { name: 'Food' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Groceries' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Fun' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Checking' })).not.toBeChecked();
    const list = await screen.findByRole('list', { name: 'Splits' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(requests).toContainEqual(
      expect.objectContaining({
        path: '/api/v1/transactions',
        query: { start: '2026-03-01', end: '2026-03-31', newest_first: 'true' },
      }),
    );
  });

  it('lists the splits of the chosen categories in a period, with totals and a pie chart', async () => {
    const user = userEvent.setup();
    const { requests } = render();
    expect(await screen.findByText('Choose one or more categories to see their transactions.')).toBeInTheDocument();

    // A top-level category totals its subcategories...
    await user.click(await screen.findByRole('checkbox', { name: 'Food' }));
    expect(screen.getByRole('checkbox', { name: 'Groceries' })).not.toBeChecked();

    const list = await screen.findByRole('list', { name: 'Splits' });
    expect(within(list).getByText('Market')).toBeInTheDocument();
    expect(within(list).getByText('Bakery')).toBeInTheDocument();
    expect(within(list).queryByText('Pay')).not.toBeInTheDocument();
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByText('Total').parentElement).toHaveTextContent('Total -€40.00');
    const legend = screen.getByRole('list', { name: 'Category totals' });
    expect(within(legend).getByText('Food').parentElement).toHaveTextContent('Food100%-€40.00');
    expect(screen.getByRole('img', { name: 'Total of each category' }).querySelectorAll('path')).toHaveLength(1);

    // ...unless they are ticked to show apart.
    await user.click(screen.getByRole('checkbox', { name: 'Groceries' }));
    expect(screen.getByText('Total').parentElement).toHaveTextContent('Total -€40.00');
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

  it('reports the cash flow of chosen accounts, with transfers to the others', async () => {
    const user = userEvent.setup();
    render();
    await user.click(await screen.findByRole('checkbox', { name: 'Interest' }));
    let list = await screen.findByRole('list', { name: 'Splits' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);

    const accounts = screen.getByRole('group', { name: 'Accounts' });
    await user.click(within(accounts).getByRole('checkbox', { name: 'Checking' }));
    await user.click(within(accounts).getByRole('checkbox', { name: 'Card' }));
    const transfers = screen.getByRole('group', { name: 'Transfers with' });
    expect(within(transfers).queryByRole('checkbox', { name: 'Card' })).not.toBeInTheDocument();
    await user.click(within(transfers).getByRole('checkbox', { name: 'Mortgage' }));

    list = screen.getByRole('list', { name: 'Splits' });
    // The mortgage principal now shows up; the card bill moves money inside the chosen accounts.
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(within(list).queryByText('Card bill')).not.toBeInTheDocument();
    expect(screen.getByText('Total').parentElement).toHaveTextContent('Total -€100.00');
    const legend = screen.getByRole('list', { name: 'Category totals' });
    expect(within(legend).getByText('Transfers › Mortgage').parentElement).toHaveTextContent('90%-€90.00');

    // Without the card, paying its bill is a transfer out of checking.
    await user.click(within(accounts).getByRole('checkbox', { name: 'Card' }));
    await user.click(within(screen.getByRole('group', { name: 'Transfers with' })).getByRole('checkbox', { name: 'Card' }));
    expect(within(screen.getByRole('list', { name: 'Splits' })).getByText('Card bill')).toBeInTheDocument();
    expect(screen.getByText('Total').parentElement).toHaveTextContent('Total -€120.00');

    await user.click(screen.getByRole('button', { name: 'Whole portfolio' }));
    expect(screen.queryByRole('group', { name: 'Transfers with' })).not.toBeInTheDocument();
    expect(within(screen.getByRole('list', { name: 'Splits' })).getAllByRole('listitem')).toHaveLength(1);
  });

  it('steps through periods and shifts days with the arrow keys', async () => {
    const user = userEvent.setup();
    const { requests } = render('/reports?period=7&categories=3', {
      'GET /api/v1/periods': [
        { id: 6, name: 'February', start: '2026-02-01', end: '2026-02-28' },
        { id: 7, name: 'March', start: '2026-03-01', end: '2026-03-31' },
        { id: 8, name: 'April', start: '2026-04-01', end: '2026-04-30' },
      ],
    });
    const period = await screen.findByRole('combobox', { name: 'Period' });
    await user.keyboard('{ArrowRight}');
    expect(period).toHaveDisplayValue(/^April/);
    await user.keyboard('{ArrowRight}');
    expect(period).toHaveDisplayValue(/^April/);
    await user.keyboard('{ArrowLeft}{ArrowLeft}');
    expect(period).toHaveDisplayValue(/^February/);

    await user.click(screen.getByRole('tab', { name: 'Days' }));
    const from = screen.getByLabelText('From');
    const to = screen.getByLabelText('To');
    await user.clear(from);
    await user.type(from, '2026-01-10');
    await user.clear(to);
    await user.type(to, '2026-01-15');
    await user.click(document.body);
    await user.keyboard('{ArrowLeft}');
    expect(from).toHaveValue('2026-01-04');
    expect(to).toHaveValue('2026-01-09');
    await user.keyboard('{ArrowRight}{ArrowRight}');
    expect(from).toHaveValue('2026-01-16');
    expect(to).toHaveValue('2026-01-21');
    await screen.findByRole('list', { name: 'Splits' });
    expect(requests).toContainEqual(
      expect.objectContaining({
        path: '/api/v1/transactions',
        query: { start: '2026-01-16', end: '2026-01-21', newest_first: 'true' },
      }),
    );
  });

  it('hides the accounts and categories but keeps the range', async () => {
    const user = userEvent.setup();
    render('/reports?period=7&categories=1,2');
    const toggle = await screen.findByRole('button', { name: 'Hide accounts and categories' });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await user.click(toggle);
    expect(screen.queryByRole('group', { name: 'Categories' })).not.toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Accounts' })).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Period' })).toBeInTheDocument();
    expect(screen.getByText('Whole portfolio · 2 categories')).toBeInTheDocument();
    expect(await screen.findByRole('list', { name: 'Splits' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Show accounts and categories' }));
    expect(screen.getByRole('checkbox', { name: 'Food' })).toBeChecked();
  });

  it('shows a slice tooltip as soon as the pointer is over it', async () => {
    const user = userEvent.setup();
    render();
    await user.click(await screen.findByRole('checkbox', { name: 'Food' }));
    const [slice] = screen.getByRole('img', { name: 'Total of each category' }).querySelectorAll('path');
    await user.hover(slice!);
    expect(screen.getByRole('tooltip')).toHaveTextContent('Food-€40.00 (100%)');
    await user.unhover(slice!);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });
});
