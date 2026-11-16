import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { unwrap } from '../api/client';
import { useApi } from '../api/context';
import { useNotify } from '../components/feedback';
import { todayDay } from '../lib/dates';
import { catchUpMessage } from '../lib/schedules';

/**
 * Once a day, when the app starts or comes back to the foreground on a new
 * day, record the due recurring transactions and start the current monthly
 * period. The server does nothing on its own: the user's own day decides.
 */
export function useCatchUp(): void {
  const api = useApi();
  const client = useQueryClient();
  const notify = useNotify();
  const lastDay = useRef<string | null>(null);

  useEffect(() => {
    const run = async () => {
      const today = todayDay();
      if (lastDay.current === today || !navigator.onLine) return;
      lastDay.current = today;
      try {
        const result = await unwrap(api.POST('/api/v1/schedules/catch-up', { body: { today } }));
        if (result.posted.length || result.periods.length || result.due.length || result.failed.length) {
          await client.invalidateQueries();
        }
        const message = catchUpMessage(result);
        if (message) notify(message, { title: 'Recurring', kind: 'success' });
        const [first] = result.failed;
        if (first) {
          const others = result.failed.length - 1;
          notify(`“${first.description || 'Recurring transaction'}”${others ? ` and ${others} more` : ''}: ${first.last_error}`, {
            title: 'Could not add a recurring transaction',
            kind: 'warning',
          });
        }
      } catch {
        // Try again on the next return to the app.
        lastDay.current = null;
      }
    };
    void run();
    const onReturn = () => {
      if (document.visibilityState === 'visible') void run();
    };
    document.addEventListener('visibilitychange', onReturn);
    window.addEventListener('online', onReturn);
    return () => {
      document.removeEventListener('visibilitychange', onReturn);
      window.removeEventListener('online', onReturn);
    };
  }, [api, client, notify]);
}
