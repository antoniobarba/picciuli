import { Link } from 'react-router';
import { unwrap } from '../api/client';
import { useApiMutation, useOccurrences, useSchedules } from '../api/queries';
import type { Category, Schedule } from '../api/types';
import { useEditors } from '../app/editors';
import { addDays, shortDate, type Day } from '../lib/dates';
import { transactionCategory, transferAmount, type ById } from '../lib/format';
import type { MoneyFormat } from '../lib/money';
import { failing, templateTransaction, toConfirm } from '../lib/schedules';
import { useNotify } from './feedback';
import { errorMessage } from './forms';
import { Amount } from './ui';

/** Days ahead listed as "coming up". */
export const UPCOMING_DAYS = 14;
const MAX_UPCOMING = 6;

function ScheduleAmount({ schedule, money }: { schedule: Schedule; money: MoneyFormat }) {
  if (schedule.kind === 'transfer') {
    return <Amount value={transferAmount(templateTransaction(schedule, ''))} money={money} muted />;
  }
  return <Amount value={schedule.net_amount} money={money} />;
}

/**
 * Recurring transactions on the Overview: those waiting for confirmation,
 * those that could not be added, and what is coming up in the next days.
 */
export function RecurringPanel({
  today,
  money,
  categories,
}: {
  today: Day;
  money: MoneyFormat;
  categories: ById<Category>;
}) {
  const editors = useEditors();
  const notify = useNotify();
  const schedules = useSchedules().data ?? [];
  const occurrences = useOccurrences(addDays(today, 1), addDays(today, UPCOMING_DAYS)).data ?? [];
  const skip = useApiMutation((api, id: number) =>
    unwrap(api.POST('/api/v1/schedules/{schedule_id}/skip', { params: { path: { schedule_id: id } } })),
  );
  if (!schedules.length) return null;

  const byId = new Map(schedules.map((s) => [s.id, s]));
  const due = toConfirm(schedules, today);
  const broken = failing(schedules);
  const upcoming = occurrences
    .map((o) => ({ date: o.date, schedule: byId.get(o.schedule_id) }))
    .filter((o): o is { date: Day; schedule: Schedule } => o.schedule !== undefined)
    .slice(0, MAX_UPCOMING);
  const title = (s: Schedule) => s.description || transactionCategory(templateTransaction(s, today), categories);

  return (
    <section className="card recurring-panel" aria-label="Recurring transactions">
      <div className="card-header">
        <h2>Recurring</h2>
        <Link to="/recurring" className="button small">
          All
        </Link>
      </div>
      <ul className="recurring-list">
        {due.map((schedule) => (
          <li key={`due-${schedule.id}`} className="due">
            <span className="recurring-date">{shortDate(schedule.next_date!)}</span>
            <span className="recurring-title">
              {title(schedule)}
              <small className="muted"> · to confirm</small>
            </span>
            <ScheduleAmount schedule={schedule} money={money} />
            <span className="recurring-actions">
              <button type="button" className="button small primary" onClick={() => editors.confirmOccurrence(schedule)}>
                Confirm
              </button>
              <button
                type="button"
                className="button small"
                onClick={async () => {
                  try {
                    await skip.mutateAsync(schedule.id);
                  } catch (error) {
                    notify(errorMessage(error), { title: 'Cannot skip', kind: 'error' });
                  }
                }}
              >
                Skip
              </button>
            </span>
          </li>
        ))}
        {broken.map((schedule) => (
          <li key={`failed-${schedule.id}`} className="failed">
            <span className="recurring-date">{schedule.next_date ? shortDate(schedule.next_date) : ''}</span>
            <span className="recurring-title">
              {title(schedule)}
              <small className="negative"> · {schedule.last_error}</small>
            </span>
            <ScheduleAmount schedule={schedule} money={money} />
            <span className="recurring-actions">
              <button type="button" className="button small" onClick={() => editors.editSchedule(schedule)}>
                Fix
              </button>
            </span>
          </li>
        ))}
        {upcoming.map(({ date, schedule }) => (
          <li key={`next-${schedule.id}-${date}`}>
            <span className="recurring-date">{shortDate(date)}</span>
            <span className="recurring-title">
              {title(schedule)}
              {schedule.mode === 'confirm' ? <small className="muted"> · to confirm</small> : null}
            </span>
            <ScheduleAmount schedule={schedule} money={money} />
            <span className="recurring-actions" />
          </li>
        ))}
        {!due.length && !broken.length && !upcoming.length ? (
          <li className="muted">Nothing due in the next {UPCOMING_DAYS} days.</li>
        ) : null}
      </ul>
    </section>
  );
}
