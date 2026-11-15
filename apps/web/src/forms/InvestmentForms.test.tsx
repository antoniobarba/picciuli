import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import type { Split, Transaction } from '../api/types';
import { EditorsProvider, useEditors } from '../app/editors';
import { renderWithApi } from '../test/render';
import { tradeOf } from './InvestmentForms';

const transaction = (id: number, splits: Split[]): Transaction => ({
  id,
  date: '2026-03-10',
  description: 'Buy All-World',
  notes: null,
  kind: 'expense',
  net_amount: 0,
  splits,
});
const buy = transaction(7, [
  { type: 'account', account_id: 2, amount: 3500, security_id: 5, quantity: '1.5' },
  { type: 'account', account_id: 1, amount: -3599 },
  { type: 'external', amount: -99, category_id: 3, memo: 'Fee' },
]);
const sell = transaction(8, [
  { type: 'account', account_id: 2, amount: -3500, security_id: 5, quantity: '-1' },
  { type: 'account', account_id: 2, amount: 3770 },
  { type: 'external', amount: 500, category_id: 4, memo: 'Realized gain' },
  { type: 'external', amount: -100, category_id: null, memo: 'Fee' },
  { type: 'external', amount: -130, category_id: 3, memo: 'Tax' },
]);

describe('tradeOf', () => {
  it('reads back what the buy and sell endpoints recorded', () => {
    expect(tradeOf(buy)).toEqual({
      selling: false, date: '2026-03-10', accountId: 2, securityId: 5, quantity: '1.5', amount: 3500,
      otherId: 1, fee: 99, feeCategoryId: 3, tax: 0, taxCategoryId: null, gainCategoryId: null,
    });
    expect(tradeOf(sell)).toEqual({
      selling: true, date: '2026-03-10', accountId: 2, securityId: 5, quantity: '1', amount: 4000,
      otherId: null, fee: 100, feeCategoryId: null, tax: 130, taxCategoryId: 3, gainCategoryId: 4,
    });
  });

  it('leaves other transactions to the split editor', () => {
    const [share, cash] = buy.splits;
    expect(tradeOf(transaction(1, [cash!, { type: 'external', amount: 3599, category_id: 3 }]))).toBeNull();
    expect(tradeOf(transaction(1, [share!, cash!, { type: 'external', amount: -99, memo: 'Lunch' }]))).toBeNull();
    expect(tradeOf(transaction(1, [share!, { ...cash!, amount: -3000 }, { type: 'external', amount: -500 }]))).toBeNull();
  });
});

const account = (id: number, name: string, type: string) => ({
  id, name, type, account_class: 'asset', opening_balance: 0, opening_date: null,
  goal: null, notes: null, position: id, closed_on: null, is_closed: false,
});

function EditButton() {
  const editors = useEditors();
  return <button type="button" onClick={() => editors.editTransaction(buy)}>Open</button>;
}

describe('editing a trade', () => {
  it('opens the buy form and replaces the purchase', async () => {
    const { requests } = renderWithApi(
      <EditorsProvider>
        <EditButton />
      </EditorsProvider>,
      {
        'GET /api/v1/settings': { currency: '€', minor_digits: 2, currency_code: 'EUR' },
        'GET /api/v1/accounts': [account(1, 'Checking', 'checking'), account(2, 'Broker', 'investment')],
        'GET /api/v1/categories': [{ id: 3, name: 'Fees', symbol: 'F', parent_id: null, position: 1 }],
        'GET /api/v1/securities': [{ id: 5, name: 'All-World', symbol: 'VWCE.DE', isin: null, currency: 'EUR', kind: 'etf', notes: null }],
      },
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Open' }));
    expect(await screen.findByRole('dialog', { name: 'Edit purchase' })).toBeInTheDocument();
    expect(screen.getByLabelText('Quantity')).toHaveValue('1.5');
    expect(screen.getByLabelText('Fee')).toHaveValue('0.99');
    await user.clear(screen.getByLabelText('Quantity'));
    await user.type(screen.getByLabelText('Quantity'), '2');
    await user.clear(screen.getByLabelText('Fee'));
    await user.type(screen.getByLabelText('Fee'), '1.50');
    await user.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(requests.find((r) => r.method === 'PUT')).toEqual({
      method: 'PUT',
      path: '/api/v1/investments/buy/7',
      body: {
        date: '2026-03-10', account_id: 2, security_id: 5, quantity: '2', fee: 150,
        description: 'Buy All-World', notes: null, cost: 3500, from_account_id: 1, fee_category_id: 3,
      },
    }));
  });
});
