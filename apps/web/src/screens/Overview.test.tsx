import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useParams } from 'react-router';
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
  'GET /api/v1/accounts/balances': accounts.map((a) => ({ account: a, balance: 1000 * a.id })),
  'GET /api/v1/investments/valuations': [],
};

function AccountView() {
  return <p>Register of account {useParams().accountId}</p>;
}

function renderOverview() {
  return renderWithApi(
    <MemoryRouter initialEntries={['/?day=2026-03-10']}>
      <EditorsProvider>
        <Routes>
          <Route index element={<Overview />} />
          <Route path="accounts/:accountId" element={<AccountView />} />
        </Routes>
      </EditorsProvider>
    </MemoryRouter>,
    routes,
  );
}

describe('Overview', () => {
  it('opens the account register when a balance row is clicked', async () => {
    const user = userEvent.setup();
    renderOverview();
    const balances = await screen.findByRole('region', { name: 'Balances' });
    await user.click(balances.querySelectorAll('td.num')[1]!);
    expect(await screen.findByText('Register of account 2')).toBeInTheDocument();
  });

  it('opens the account register with Enter on the focused balance link', async () => {
    const user = userEvent.setup();
    renderOverview();
    const link = await screen.findByRole('link', { name: 'Checking' });
    link.focus();
    await user.keyboard('{Enter}');
    expect(await screen.findByText('Register of account 1')).toBeInTheDocument();
  });

  it('starts a new transaction on a double-clicked day, while a click only selects it', async () => {
    const user = userEvent.setup();
    renderOverview();
    await screen.findByRole('link', { name: 'Checking' });
    const day = screen.getByRole('button', { name: longDate('2026-03-12') });

    await user.click(day);
    expect(day).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('dialog', { name: 'New transaction' })).not.toBeInTheDocument();

    await user.dblClick(day);
    await screen.findByRole('dialog', { name: 'New transaction' });
    expect(screen.getByLabelText('Date')).toHaveValue('2026-03-12');
  });
});
