import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { UserManager } from 'oidc-client-ts';
import { lazy, useMemo, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import { ApiError, createApi } from '../api/client';
import { ApiContext } from '../api/context';
import { AuthProvider, useAuth } from '../auth/AuthProvider';
import { isIdentityPath, IdentityScreen } from '../auth/IdentityScreen';
import type { AppConfig } from '../config';
import { ConfirmProvider, ToastProvider, useNotify } from '../components/feedback';
import { Overview } from '../screens/Overview';
import { EditorsProvider } from './editors';
import { LivePricesProvider } from './live';
import { Shell } from './Shell';

const Accounts = lazy(() => import('../screens/Accounts').then((m) => ({ default: m.Accounts })));
const Register = lazy(() => import('../screens/Register').then((m) => ({ default: m.Register })));
const Categories = lazy(() => import('../screens/Categories').then((m) => ({ default: m.Categories })));
const Periods = lazy(() => import('../screens/Periods').then((m) => ({ default: m.Periods })));
const Budgets = lazy(() => import('../screens/Budgets').then((m) => ({ default: m.Budgets })));
const Investments = lazy(() => import('../screens/Investments').then((m) => ({ default: m.Investments })));
const Reports = lazy(() => import('../screens/Reports').then((m) => ({ default: m.Reports })));
const Settings = lazy(() => import('../screens/Settings').then((m) => ({ default: m.Settings })));

export function App({ config, manager }: { config: AppConfig; manager: UserManager }) {
  return (
    <ToastProvider>
      <AuthProvider manager={manager} nativeLogin={config.nativeLogin}>
        <Gate config={config} />
      </AuthProvider>
    </ToastProvider>
  );
}

function Gate({ config }: { config: AppConfig }) {
  const auth = useAuth();
  if (isIdentityPath()) return <IdentityScreen />;
  if (auth.status === 'loading') return <Splash />;
  if (auth.status === 'error') {
    return (
      <Welcome>
        <p className="form-error">Signing in failed: {auth.error}</p>
        <button type="button" className="button primary large" onClick={() => void auth.signIn()}>
          Try again
        </button>
      </Welcome>
    );
  }
  if (auth.status === 'signedOut') {
    return (
      <Welcome>
        <p>Your budget, your accounts and your investments, on every device.</p>
        <div className="welcome-actions">
          <button type="button" className="button primary large" onClick={() => void auth.signIn()}>
            Sign in
          </button>
          <button type="button" className="button large" onClick={() => void auth.signIn({ register: true })}>
            Create an account
          </button>
        </div>
      </Welcome>
    );
  }
  // Keyed by user: another tab may sign in as someone else, which must drop the cache.
  return <Authenticated key={auth.user?.profile.sub} config={config} />;
}

function Splash() {
  return (
    <div className="splash" aria-busy="true">
      <img src="/logo.svg" alt="" width="64" height="64" />
    </div>
  );
}

function Welcome({ children }: { children: React.ReactNode }) {
  return (
    <main className="welcome">
      <img src="/logo.svg" alt="" width="88" height="88" />
      <h1>Picciuli</h1>
      {children}
    </main>
  );
}

function shouldRetry(failures: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failures < 2;
}

/** Everything below exists only while signed in: a new session starts with an empty cache. */
function Authenticated({ config }: { config: AppConfig }) {
  const auth = useAuth();
  const notify = useNotify();
  const { getToken, handleUnauthorized } = auth;
  const api = useMemo(
    () => createApi({ baseUrl: config.apiUrl, getToken, onUnauthorized: handleUnauthorized }),
    [config.apiUrl, getToken, handleUnauthorized],
  );
  const [queryClient] = useState(
    () =>
      new QueryClient({
        queryCache: new QueryCache({
          onError: (error, query) => {
            // Offline is announced by a banner; 401 leads to a renewal or the sign-in page.
            if (query.meta?.quiet || !navigator.onLine) return;
            if (error instanceof ApiError && error.status === 401) return;
            notify(error.message, { title: 'Cannot load data', kind: 'error' });
          },
        }),
        defaultOptions: {
          queries: { staleTime: 10_000, retry: shouldRetry, refetchOnWindowFocus: true },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ApiContext.Provider value={api}>
        <ConfirmProvider>
          <LivePricesProvider>
            <BrowserRouter>
              <EditorsProvider>
                <Routes>
                  <Route element={<Shell />}>
                    <Route index element={<Overview />} />
                    <Route path="accounts" element={<Accounts />} />
                    <Route path="accounts/:accountId" element={<Register />} />
                    <Route path="categories" element={<Categories />} />
                    <Route path="periods" element={<Periods />} />
                    <Route path="budgets" element={<Budgets />} />
                    <Route path="investments" element={<Investments />} />
                    <Route path="reports" element={<Reports />} />
                    <Route path="settings" element={<Settings />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                  </Route>
                </Routes>
              </EditorsProvider>
            </BrowserRouter>
          </LivePricesProvider>
        </ConfirmProvider>
      </ApiContext.Provider>
    </QueryClientProvider>
  );
}
