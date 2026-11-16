import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import type { Settings } from '../api/types';
import { renderWithApi } from '../test/render';
import { MonthlyPeriodsForm } from './Settings';

const settings: Settings = {
  currency: '€',
  minor_digits: 2,
  currency_code: 'EUR',
  cost_method: 'average',
  price_provider: 'yahoo',
  rate_provider: 'yahoo',
  period_start_day: null,
  period_weekend_shift: true,
};

it('turns on monthly periods, previews and applies the changes to existing periods', async () => {
  const user = userEvent.setup();
  const old = { id: 1, name: 'November', start: '2026-11-01', end: '2026-11-30' };
  const { requests } = renderWithApi(<MonthlyPeriodsForm settings={settings} />, {
    'PATCH /api/v1/settings': { ...settings, period_start_day: 27, period_weekend_shift: false },
    'GET /api/v1/periods/regenerate': [
      { kind: 'update', period: old, name: 'November 2026', start: '2026-10-27', end: '2026-11-26' },
    ],
    'POST /api/v1/periods/regenerate': [],
    'POST /api/v1/schedules/catch-up': { periods: [], posted: [], due: [], failed: [] },
  });

  await user.selectOptions(screen.getByLabelText('Each period starts on'), 'Day 27');
  await user.click(screen.getByRole('checkbox'));
  await user.click(screen.getByRole('button', { name: 'Save periods' }));

  const dialog = await screen.findByRole('dialog', { name: 'Update your existing periods?' });
  const row = within(dialog).getByText('November 2026').closest('tr')!;
  expect(row).toHaveTextContent('Changed');
  expect(row).toHaveTextContent('27 Oct 2026 – 26 Nov 2026');
  expect(row).toHaveTextContent('November, 01 Nov 2026 – 30 Nov 2026');
  await user.click(within(dialog).getByRole('button', { name: 'Update periods' }));

  await waitFor(() => expect(requests.at(-1)?.path).toBe('/api/v1/schedules/catch-up'));
  expect(requests.filter((r) => r.method !== 'GET').map((r) => [r.method, r.path, r.body])).toEqual([
    ['PATCH', '/api/v1/settings', { period_start_day: 27, period_weekend_shift: false }],
    ['POST', '/api/v1/periods/regenerate', { today: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) }],
    ['POST', '/api/v1/schedules/catch-up', { today: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) }],
  ]);
  expect(await screen.findByText('Monthly periods saved')).toBeInTheDocument();
});
