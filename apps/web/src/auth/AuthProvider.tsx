import type { User, UserManager } from 'oidc-client-ts';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { isUserStorageEvent, type ReturnState } from './oidc';
import { loginRequest } from './login';
import { useNotify } from '../components/feedback';

type Status = 'loading' | 'signedOut' | 'signedIn' | 'error';

export interface AuthState {
  status: Status;
  user: User | null;
  error: string | null;
  signIn: (options?: { register?: boolean }) => Promise<void>;
  signOut: () => Promise<void>;
  /** A valid access token, renewing it first when it is about to expire. */
  getToken: () => Promise<string | null>;
  /** Called when the API rejected the token. */
  handleUnauthorized: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth outside AuthProvider');
  return context;
}

const CALLBACK_PATH = '/callback';
const RENEW_MARGIN_SECONDS = 30;
const RENEW_LOCK = 'picciuli-token-renewal';

// An authorization code can be redeemed only once, even if the effect runs twice.
let callbackOnce: Promise<User> | null = null;

/**
 * Runs `task` while no other tab of the app renews: Zitadel refresh tokens are
 * single-use, so a tab presenting one already spent by another tab is rejected.
 */
async function exclusively<T>(task: () => Promise<T>): Promise<T> {
  const locks = navigator.locks as LockManager | undefined;
  return locks ? await locks.request(RENEW_LOCK, task) : await task();
}

function currentLocation(): string {
  const { pathname, search, hash } = window.location;
  if ([CALLBACK_PATH, '/login', '/verify-email', '/reset-password'].includes(pathname)) {
    const saved = sessionStorage.getItem('picciuli-return-to') || '/';
    return saved.startsWith('/') && !saved.startsWith('//') ? saved : '/';
  }
  return `${pathname}${search}${hash}`;
}

export function AuthProvider({ manager, children, nativeLogin = false }: { manager: UserManager; children: ReactNode; nativeLogin?: boolean }) {
  const notify = useNotify();
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<Status>('loading');
  const [error, setError] = useState<string | null>(null);
  const renewing = useRef<Promise<User | null> | null>(null);

  /** Renews the access token; `force` also renews one that is not about to expire. */
  const renew = useCallback(async (force = false): Promise<User | null> => {
    renewing.current ??= exclusively(async () => {
      // Another tab may have renewed while this one waited for the lock.
      const stored = await manager.getUser();
      if (!force && stored && (stored.expires_in ?? 0) >= RENEW_MARGIN_SECONDS) return stored;
      return manager.signinSilent();
    })
      .catch(() => null)
      .finally(() => {
        renewing.current = null;
      });
    const renewed = await renewing.current;
    if (!renewed) {
      // Another tab may have renewed first: refresh tokens are single-use.
      const stored = await manager.getUser();
      if (stored && !stored.expired) {
        setUser(stored);
        return stored;
      }
      await manager.removeUser();
      setUser(null);
      setStatus('signedOut');
    }
    return renewed;
  }, [manager]);

  useEffect(() => {
    let active = true;
    const start = async () => {
      try {
        if (window.location.pathname === CALLBACK_PATH) {
          callbackOnce ??= manager.signinRedirectCallback();
          const signedIn = await callbackOnce;
          const state = signedIn.state as ReturnState | undefined;
          window.history.replaceState(null, '', state?.returnTo || '/');
          sessionStorage.removeItem('picciuli-return-to');
          if (active) {
            setUser(signedIn);
            setStatus('signedIn');
          }
          return;
        }
        let stored = await manager.getUser();
        if (stored?.expired && stored.refresh_token) stored = await renew();
        if (!active) return;
        setUser(stored && !stored.expired ? stored : null);
        setStatus(stored && !stored.expired ? 'signedIn' : 'signedOut');
      } catch (failure) {
        if (!active) return;
        setError(failure instanceof Error ? failure.message : String(failure));
        setStatus('error');
      }
    };
    void start();

    const loaded = (next: User) => {
      setUser(next);
      setStatus('signedIn');
    };
    const unloaded = () => {
      setUser(null);
      setStatus('signedOut');
    };
    manager.events.addUserLoaded(loaded);
    manager.events.addUserUnloaded(unloaded);
    manager.events.addUserSignedOut(unloaded);
    // Follows sign-in, renewal and sign-out in other tabs of the app.
    const synchronise = (event: StorageEvent) => {
      if (!isUserStorageEvent(event)) return;
      void manager.getUser().then((next) => {
        if (!active) return;
        if (!next) unloaded();
        else if (!next.expired) loaded(next);
      });
    };
    window.addEventListener('storage', synchronise);
    return () => {
      active = false;
      window.removeEventListener('storage', synchronise);
      manager.events.removeUserLoaded(loaded);
      manager.events.removeUserUnloaded(unloaded);
      manager.events.removeUserSignedOut(unloaded);
    };
  }, [manager, renew]);

  const signIn = useCallback(
    async ({ register = false }: { register?: boolean } = {}) => {
      const state: ReturnState = { returnTo: currentLocation() };
      sessionStorage.setItem('picciuli-return-to', state.returnTo);
      sessionStorage.setItem('picciuli-register', String(register));
      try {
        await manager.signinRedirect({ state, prompt: nativeLogin ? 'login' : register ? 'create' : undefined });
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : String(failure));
        setStatus('error');
        notify(failure instanceof Error ? failure.message : 'Cannot start sign-in.', { kind: 'error' });
      }
    },
    [manager, nativeLogin, notify],
  );

  const signOut = useCallback(async () => {
    try {
      const current = await manager.getUser();
      if (nativeLogin) {
        await loginRequest('logout');
        // The session is gone: clear the local tokens even if revocation fails.
        await manager.revokeTokens(['access_token', 'refresh_token']).catch(() => undefined);
      } else {
        // Revokes the tokens (revokeTokensOnSignout) and clears them before leaving.
        await manager.signoutRedirect({ id_token_hint: current?.id_token });
      }
      await manager.removeUser();
      setUser(null);
      setStatus('signedOut');
      window.history.replaceState(null, '', '/');
    } catch (failure) {
      notify(failure instanceof Error ? failure.message : 'Sign-out failed. Please try again.', { kind: 'error' });
    }
  }, [manager, nativeLogin, notify]);

  const getToken = useCallback(async () => {
    let current = await manager.getUser();
    if (current && (current.expires_in ?? 0) < RENEW_MARGIN_SECONDS) current = await renew();
    return current?.access_token ?? null;
  }, [manager, renew]);

  const handleUnauthorized = useCallback(() => {
    void renew(true);
  }, [renew]);

  const value = useMemo<AuthState>(
    () => ({ status, user, error, signIn, signOut, getToken, handleUnauthorized }),
    [status, user, error, signIn, signOut, getToken, handleUnauthorized],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
