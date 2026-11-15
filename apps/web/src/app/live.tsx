import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { unwrap } from '../api/client';
import { useApiMutation } from '../api/queries';
import { useNotify } from '../components/feedback';
import { errorMessage } from '../components/forms';
import type { Day } from '../lib/dates';

export const LIVE_SECONDS = 60;

interface LivePrices {
  live: boolean;
  setLive: (on: boolean) => void;
  refreshing: boolean;
  lastUpdate: Date | null;
  refresh: (options?: { historyStart?: Day; quiet?: boolean }) => Promise<void>;
}

const LiveContext = createContext<LivePrices | null>(null);

export function useLivePrices(): LivePrices {
  const context = useContext(LiveContext);
  if (!context) throw new Error('useLivePrices outside LivePricesProvider');
  return context;
}

/**
 * Prices are downloaded by the API on request. With live prices on, every
 * screen refreshes them every minute; the API shares quotes between users
 * for 15 minutes, so this never overloads the provider.
 */
export function LivePricesProvider({ children }: { children: ReactNode }) {
  const notify = useNotify();
  const [live, setLive] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const mutation = useApiMutation((api, historyStart: Day | undefined) =>
    unwrap(api.POST('/api/v1/investments/refresh-prices', { body: { history_start: historyStart ?? null } })),
  );
  const { mutateAsync, isPending } = mutation;

  const refresh = useCallback(
    async ({ historyStart, quiet = false }: { historyStart?: Day; quiet?: boolean } = {}) => {
      try {
        const update = await mutateAsync(historyStart);
        setLastUpdate(new Date());
        if (update.errors.length) {
          notify(update.errors.join('\n'), { title: 'Some prices were not updated', kind: 'warning' });
        } else if (!quiet) {
          notify(`${update.prices.length} prices and ${update.exchange_rates.length} exchange rates updated`, {
            title: 'Prices',
            kind: 'success',
          });
        }
      } catch (error) {
        notify(errorMessage(error), { title: 'Cannot refresh prices', kind: 'error' });
      }
    },
    [mutateAsync, notify],
  );

  const latest = useRef(refresh);
  useEffect(() => {
    latest.current = refresh;
  });
  useEffect(() => {
    if (!live) return;
    void latest.current({ quiet: true });
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void latest.current({ quiet: true });
    }, LIVE_SECONDS * 1000);
    return () => window.clearInterval(timer);
  }, [live]);

  const value = useMemo(
    () => ({ live, setLive, refreshing: isPending, lastUpdate, refresh }),
    [live, isPending, lastUpdate, refresh],
  );
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}
