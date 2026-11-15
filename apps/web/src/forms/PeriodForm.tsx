import { useState } from 'react';
import { unwrap } from '../api/client';
import { useApiMutation } from '../api/queries';
import type { Period } from '../api/types';
import { DateField } from '../components/DateField';
import { FormDialog, TextField } from '../components/forms';
import { todayDay, type Day } from '../lib/dates';
import { defaultPeriodName, optionalDate, optionalText, parseDate } from '../lib/forms';

export const PERIOD_HELP =
  'A period without an end is open-ended: it lasts until the next open-ended period starts, and starting one ends the earlier ones the day before. Periods may overlap, e.g. a holiday inside a pay cycle.';

export function PeriodForm({
  open,
  onClose,
  period,
  start,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  period?: Period | null;
  start?: Day;
  onSaved?: (period: Period) => void;
}) {
  const today = todayDay();
  const [name, setName] = useState(period?.name ?? '');
  const [first, setFirst] = useState(period?.start ?? start ?? today);
  const [last, setLast] = useState(period?.end ?? '');

  const placeholder = (() => {
    try {
      return defaultPeriodName(parseDate(first, today));
    } catch {
      return '';
    }
  })();

  const save = useApiMutation(async (api) => {
    const body = {
      start: parseDate(first, today),
      end: optionalDate(last, today),
      name: optionalText(name) ?? defaultPeriodName(parseDate(first, today)),
    };
    if (period) {
      return unwrap(
        api.PATCH('/api/v1/periods/{period_id}', { params: { path: { period_id: period.id } }, body }),
      );
    }
    return unwrap(api.POST('/api/v1/periods', { body }));
  });

  return (
    <FormDialog
      open={open}
      onClose={onClose}
      title={period ? `Edit ${period.name}` : start ? 'Start a period' : 'New period'}
      onSubmit={async () => {
        const saved = await save.mutateAsync(undefined);
        onSaved?.(saved);
      }}
      help={PERIOD_HELP}
    >
      <TextField label="Name" value={name} onChange={setName} placeholder={placeholder} data-autofocus />
      <div className="form-row">
        <DateField label="Start" value={first} onChange={setFirst} today={today} />
        <DateField label="End" value={last} onChange={setLast} today={today} placeholder="empty = open-ended" />
      </div>
    </FormDialog>
  );
}
