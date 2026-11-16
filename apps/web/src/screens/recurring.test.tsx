import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { describe, expect, it } from 'vitest';
import type { Schedule } from '../api/types';
import { EditorsProvider } from '../app/editors';
import { addDays, longDate, todayDay } from '../lib/dates';
import { renderWithApi } from '../test/render';
import { Overview } from './Overview';
import { Recurring } from './Recurring';

const today = todayDay();
const account = {
  id: 1, name: 'Checking', type: 'checking', account_class: 'asset', opening_balance: 0, opening_date: null,
  goal: null, notes: null, position: 1, closed_on: null, is_closed: false,
};
const bills = { id: 2, name: 'Bills', symbol: 'B', parent_id: null, position: 1 };

function schedule(overrides: Partial<Schedule>): Schedule {
  return {
    id: 1, description: 'Rent', notes: null, frequency: 'monthly', every: 1, day_of_month: 1,
    next_date: addDays(today, 3), end: null, remaining: null, mode: 'auto', paused: false, last_error: null,
    kind: 'expense', net_amount: -80000, is_finished: false,
    splits: [
      { type: 'account', account_id: 1, amount: -80000 },
      { type: 'external', amount: -80000, category_id: 2 },
    ],
    ...overrides,
  };
}

const power = schedule({
  id: 2, description: 'Power', mode: 'confirm', next_date: addDays(today, -2), net_amount: -9000,
  splits: [
    { type: 'account', account_id: 1, amount: -9000 },
    { type: 'external', amount: -9000, category_id: 2 },
  ],
});
const gym = schedule({ id: 3, description: 'Gym', paused: true, frequency: 'weekly', every: 2, day_of_month: null });
const broken = schedule({ id: 4, description: 'Phone', last_error: "account 'Old' is closed" });

const routes = {
  'GET /api/v1/settings': { currency: '€', minor_digits: 2, currency_code: 'EUR' },
  'GET /api/v1/accounts': [account],
  'GET /api/v1/categories': [bills],
  'GET /api/v1/transactions': [],
  'GET /api/v1/periods': [],
  'GET /api/v1/securities': [],
  'GET /api/v1/schedules': [power, schedule({}), gym, broken],
  'GET /api/v1/schedules/occurrences': [{ schedule_id: 1, date: addDays(today, 3) }],
};

function renderAt(path: string) {
  return renderWithApi(
    <MemoryRouter initialEntries={[path]}>
      <EditorsProvider>
        <Routes>
          <Route index element={<Overview />} />
          <Route path="recurring" element={<Recurring />} />
        </Routes>
      </EditorsProvider>
    </MemoryRouter>,
    routes,
  );
}

describe('Recurring screen', () => {
  it('lists the schedules with their rule and status', async () => {
    renderAt('/recurring');
    const rent = (await screen.findByText('Rent')).closest('tr')!;
    expect(rent).toHaveTextContent('Every month on day 1');
    expect(rent).toHaveTextContent('Checking · Bills');
    expect(rent).toHaveTextContent('-€800.00');
    expect(screen.getByText('Gym').closest('tr')).toHaveTextContent('Every 2 weeks');
    expect(within(screen.getByText('Gym').closest('tr')!).getByText('Paused')).toBeInTheDocument();
    expect(within(screen.getByText('Phone').closest('tr')!).getByText('Needs attention')).toHaveAttribute(
      'title',
      "account 'Old' is closed",
    );
    expect(screen.getByText('Power').closest('tr')).toHaveTextContent('Confirmed by you');
  });

  it('creates a schedule that repeats every other week', async () => {
    const user = userEvent.setup();
    const { requests } = renderAt('/recurring');
    await user.click(await screen.findByRole('button', { name: '+ New recurring' }));
    const dialog = await screen.findByRole('dialog', { name: 'New recurring transaction' });
    await user.clear(within(dialog).getByLabelText('First date'));
    await user.type(within(dialog).getByLabelText('First date'), '2026-12-04');
    await user.type(within(dialog).getByLabelText('Amount'), '25');
    await user.selectOptions(within(dialog).getByLabelText('Category'), 'Bills');
    await user.type(within(dialog).getByLabelText('Description'), 'Cleaning');
    await user.clear(within(dialog).getByLabelText('Every'));
    await user.type(within(dialog).getByLabelText('Every'), '2');
    await user.selectOptions(within(dialog).getByLabelText('Unit'), 'Weeks');
    await user.selectOptions(within(dialog).getByLabelText('Ends'), 'After a number of times');
    await user.type(within(dialog).getByLabelText('Times'), '10');
    await user.selectOptions(within(dialog).getByLabelText('When it is due'), 'Remind me to confirm it');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(requests.some((r) => r.method === 'POST')).toBe(true));
    expect(requests.find((r) => r.method === 'POST')).toEqual({
      method: 'POST',
      path: '/api/v1/schedules',
      body: {
        start: '2026-12-04',
        splits: [
          { type: 'account', account_id: 1, amount: -2500 },
          { type: 'external', amount: -2500, category_id: 2 },
        ],
        frequency: 'weekly',
        every: 2,
        day_of_month: null,
        end: null,
        occurrences: 10,
        mode: 'confirm',
        description: 'Cleaning',
        notes: null,
      },
    });
  });
});

describe('Overview recurring panel', () => {
  it('confirms a due bill with this month’s amount', async () => {
    const user = userEvent.setup();
    const { requests } = renderAt('/');
    const panel = await screen.findByRole('region', { name: 'Recurring transactions' });
    const due = (await within(panel).findByText('Power')).closest('li')!;
    expect(due).toHaveTextContent('to confirm');
    expect(within(panel).getByText('Phone').closest('li')).toHaveTextContent("account 'Old' is closed");
    expect(within(panel).getByText('Rent').closest('li')).toHaveTextContent('-€800.00');

    await user.click(within(due).getByRole('button', { name: 'Confirm' }));
    const dialog = await screen.findByRole('dialog', { name: 'Confirm “Power”' });
    expect(within(dialog).getByLabelText('Date')).toHaveValue(addDays(today, -2));
    await user.clear(within(dialog).getByLabelText('Amount'));
    await user.type(within(dialog).getByLabelText('Amount'), '91.37');
    await user.click(within(dialog).getByRole('button', { name: 'Record' }));
    await waitFor(() => expect(requests.some((r) => r.method === 'POST')).toBe(true));
    expect(requests.find((r) => r.method === 'POST')).toEqual({
      method: 'POST',
      path: '/api/v1/schedules/2/post',
      body: {
        date: addDays(today, -2),
        splits: [
          { type: 'account', account_id: 1, amount: -9137 },
          { type: 'external', amount: -9137, category_id: 2 },
        ],
        description: 'Power',
        notes: null,
      },
    });
  });

  it('skips a due bill and marks upcoming days on the calendar', async () => {
    const user = userEvent.setup();
    const { requests } = renderAt('/');
    const panel = await screen.findByRole('region', { name: 'Recurring transactions' });
    const due = (await within(panel).findByText('Power')).closest('li')!;
    await user.click(within(due).getByRole('button', { name: 'Skip' }));
    await waitFor(() =>
      expect(requests.find((r) => r.method === 'POST')).toMatchObject({ path: '/api/v1/schedules/2/skip' }),
    );
    expect(
      await screen.findByRole('button', { name: `${longDate(addDays(today, 3))}, recurring transaction due` }),
    ).toBeInTheDocument();
  });
});
