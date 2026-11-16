import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { Link, MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';
import type { Account, Transaction } from '../api/types';
import { EditorsProvider } from '../app/editors';
import { TransactionListControls, useTransactionList } from '../components/TransactionListControls';
import { TransactionsModal } from '../components/TransactionsModal';
import { renderWithApi } from '../test/render';
import { Overview } from './Overview';
import { Register } from './Register';

const account: Account = {
  id: 1, name: 'Checking', type: 'checking', account_class: 'asset',
  opening_balance: 10000, opening_date: null, notes: null,
  position: 1, closed_on: null, is_closed: false,
};
const transactions: Transaction[] = Array.from({ length: 52 }, (_, index) => ({
  id: index + 1,
  date: '2026-03-10',
  description: `Purchase ${String(index + 1).padStart(2, '0')}`,
  notes: index === 0 ? 'Needle in a haystack' : null,
  kind: 'expense',
  net_amount: -100,
  splits: [
    { type: 'account', account_id: 1, amount: -100 },
    { type: 'external', category_id: 1, amount: -100 },
  ],
}));
const register = {
  account, starting_balance: 10000, ending_balance: 4800,
  entries: transactions.map((transaction, index) => ({
    transaction, amount: -100, balance: 10000 - (index + 1) * 100,
  })),
};
const routes = {
  'GET /api/v1/settings': { currency: 'EUR', minor_digits: 2, currency_code: 'EUR' },
  'GET /api/v1/accounts': [account],
  'GET /api/v1/categories': [{ id: 1, name: 'Groceries', parent_id: null, symbol: 'FOOD', position: 1 }],
  'GET /api/v1/transactions': transactions,
  'GET /api/v1/accounts/1/register': register,
  'GET /api/v1/accounts/2/register': { ...register, account: { ...account, id: 2, name: 'Savings' } },
  'GET /api/v1/investments/valuations': [],
  'GET /api/v1/accounts/balances': [],
  'GET /api/v1/periods': [],
};

function renderList(view: string) {
  return renderWithApi(
    <MemoryRouter initialEntries={[view === 'register' ? '/accounts/1' : '/?day=2026-03-10']}>
      <EditorsProvider>
        <Routes>
          <Route path="accounts/:accountId" element={
            <>
              <Link to="/accounts/1">Checking account</Link>
              <Link to="/accounts/2">Savings</Link>
              <Register />
            </>
          } />
          <Route index element={view === 'overview' ? <Overview /> : (
            <TransactionsModal
              title="All transactions" filter={{}} remaining={{ label: 'Remaining', value: 10000 }} onClose={() => {}}
            />
          )} />
        </Routes>
      </EditorsProvider>
    </MemoryRouter>,
    routes,
  );
}

describe.each(['register', 'dialog'])('%s transaction list', (view) => {
  it('pages the whole list, searches off-page notes, and resets the page when searching', async () => {
    const user = userEvent.setup();
    renderList(view);
    await screen.findByText(view === 'register' ? 'Purchase 52' : 'Purchase 01');
    expect(screen.getAllByText(/^Purchase \d+$/)).toHaveLength(25);
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText('Page 2 of 3')).toBeInTheDocument();
    expect(screen.getAllByText(/^Purchase \d+$/)).toHaveLength(25);
    await user.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getAllByText(/^Purchase \d+$/)).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Previous' }));

    const search = screen.getByRole('searchbox', { name: 'Search transactions' });
    await user.type(search, '  NEEDLE  ');
    expect(screen.getAllByText(/^Purchase \d+$/)).toHaveLength(1);
    expect(screen.getByText('Purchase 01')).toBeInTheDocument();
    expect(screen.getByText('Page 1 of 1')).toBeInTheDocument();

    await user.clear(search);
    expect(screen.getAllByText(/^Purchase \d+$/)).toHaveLength(25);
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
    await user.type(search, 'not found anywhere');
    expect(screen.getByText('No matching transactions.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    await user.clear(search);
    await user.type(search, 'checking groceries 2026-03-10');
    expect(screen.getAllByText(/^Purchase \d+$/)).toHaveLength(25);
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
  });
});

it('preserves register running balances and resets search and page on account changes', async () => {
  const user = userEvent.setup();
  renderList('register');
  const first = (await screen.findByText('Purchase 52')).closest('tr')!;
  expect(within(first).getAllByText('EUR 48.00')).toHaveLength(2);
  await user.click(screen.getByRole('button', { name: 'Next' }));
  await user.click(screen.getByRole('link', { name: 'Savings' }));
  await screen.findByRole('heading', { name: /Savings/ });
  expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
  await user.type(screen.getByRole('searchbox'), 'needle');
  const match = screen.getByText('Purchase 01').closest('tr')!;
  expect(within(match).getAllByText('EUR 99.00')).toHaveLength(2);
  expect(screen.getByText('Starting').parentElement).toHaveTextContent('EUR 100.00');
  expect(screen.getByText('Balance', { selector: 'span' })).toHaveTextContent('EUR 48.00');
  await user.click(screen.getByRole('link', { name: 'Checking account' }));
  await screen.findByRole('heading', { name: /Checking/ });
  expect(screen.getByRole('searchbox')).toHaveValue('');
  expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
});

it('totals every page of the dialog list, narrowed to the search results', async () => {
  const user = userEvent.setup();
  renderList('dialog');
  await screen.findByText('Purchase 01');
  await user.click(screen.getByRole('button', { name: 'Next' }));
  expect(screen.getByText('Total').parentElement).toHaveTextContent('-EUR 52.00');
  expect(screen.getByText('52 transactions')).toBeInTheDocument();
  await user.type(screen.getByRole('searchbox'), 'needle');
  expect(screen.getByText('Total').parentElement).toHaveTextContent('-EUR 1.00');
  expect(screen.getByText('1 transaction')).toBeInTheDocument();
  expect(screen.getByText('Remaining').parentElement).toHaveTextContent('EUR 100.00');
});

it('lists every transaction of the day on the Overview, without search or pages', async () => {
  renderList('overview');
  await screen.findByText('Purchase 01');
  expect(screen.getAllByText(/^Purchase \d+$/)).toHaveLength(52);
  expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();
  expect(screen.queryByRole('navigation', { name: 'Transaction pages' })).not.toBeInTheDocument();
});

it('clamps the page after the last page disappears on a data refresh', async () => {
  function List() {
    const [items, setItems] = useState(transactions);
    const list = useTransactionList(items, 'test', (transaction) => transaction);
    return (
      <>
        <TransactionListControls list={list} />
        {list.items.map((transaction) => <p key={transaction.id}>{transaction.description}</p>)}
        <button onClick={() => setItems(transactions.slice(0, 25))}>Refresh data</button>
      </>
    );
  }
  const user = userEvent.setup();
  renderWithApi(<List />, routes);
  await user.click(screen.getByRole('button', { name: 'Next' }));
  await user.click(screen.getByRole('button', { name: 'Next' }));
  await user.click(screen.getByRole('button', { name: 'Refresh data' }));
  expect(screen.getByText('Page 1 of 1')).toBeInTheDocument();
  expect(screen.getAllByText(/^Purchase \d+$/)).toHaveLength(25);
});
