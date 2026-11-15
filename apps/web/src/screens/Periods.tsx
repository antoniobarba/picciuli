import { useMemo, useState } from 'react';
import { unwrap } from '../api/client';
import { useApiMutation, usePeriods } from '../api/queries';
import type { Period } from '../api/types';
import { useConfirm, useNotify } from '../components/feedback';
import { errorMessage } from '../components/forms';
import { Empty, Loading, PageHeader, RowMenu } from '../components/ui';
import { covers } from '../lib/calendar';
import { daysBetween, shortDate, todayDay } from '../lib/dates';
import { useHotkeys } from '../lib/useHotkeys';
import { PERIOD_HELP, PeriodForm } from '../forms/PeriodForm';

export function Periods() {
  const periods = usePeriods();
  const confirm = useConfirm();
  const notify = useNotify();
  const today = todayDay();
  const [editing, setEditing] = useState<{ period: Period | null } | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const list = useMemo(
    () => [...(periods.data ?? [])].sort((a, b) => b.start.localeCompare(a.start) || b.id - a.id),
    [periods.data],
  );
  const selected = list.find((p) => p.id === selectedId) ?? null;

  const remove = useApiMutation((api, id: number) =>
    unwrap(api.DELETE('/api/v1/periods/{period_id}', { params: { path: { period_id: id } } })),
  );
  const deletePeriod = async (period: Period) => {
    if (await confirm({ title: `Delete period “${period.name}”?`, message: 'Its budgets are deleted too; transactions are kept.' })) {
      try {
        await remove.mutateAsync(period.id);
      } catch (error) {
        notify(errorMessage(error), { title: 'Cannot do that', kind: 'error' });
      }
    }
  };

  useHotkeys({
    n: () => setEditing({ period: null }),
    e: () => selected && setEditing({ period: selected }),
    d: () => selected && void deletePeriod(selected),
  });

  return (
    <div className="page narrow">
      <PageHeader title="Periods">
        <button type="button" className="button primary" onClick={() => setEditing({ period: null })}>
          + New period
        </button>
      </PageHeader>
      {periods.isLoading ? (
        <Loading />
      ) : list.length === 0 ? (
        <Empty>
          No periods yet. A period is a range of days with its own summary and budgets, e.g. from one
          salary to the next. {PERIOD_HELP}
        </Empty>
      ) : (
        <div className="card">
          <table className="table rows-clickable">
            <thead>
              <tr>
                <th aria-label="Current" />
                <th>Name</th>
                <th>Start</th>
                <th>End</th>
                <th className="num hide-sm">Days</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {list.map((period) => (
                <tr
                  key={period.id}
                  tabIndex={0}
                  className={period.id === selectedId ? 'selected' : ''}
                  onFocus={() => setSelectedId(period.id)}
                  onClick={() => setEditing({ period })}
                  onKeyDown={(e) => e.key === 'Enter' && setEditing({ period })}
                >
                  <td>{covers(period, today) ? <span className="badge" title="Covers today">●</span> : null}</td>
                  <td className="strong">{period.name}</td>
                  <td className="nowrap">{shortDate(period.start)}</td>
                  <td className="nowrap">{period.end ? shortDate(period.end) : <span className="muted">open</span>}</td>
                  <td className="num hide-sm">{period.end ? daysBetween(period.start, period.end) + 1 : ''}</td>
                  <td className="actions" onClick={(e) => e.stopPropagation()}>
                    <RowMenu
                      actions={[
                        { label: 'Edit', onSelect: () => setEditing({ period }), shortcut: 'e' },
                        { label: 'Delete', onSelect: () => void deletePeriod(period), danger: true, shortcut: 'd' },
                      ]}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing ? <PeriodForm open period={editing.period} onClose={() => setEditing(null)} /> : null}
    </div>
  );
}
