import type { User, UserManager } from 'oidc-client-ts';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { ReturnState } from './oidc';

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

function currentLocation(): string {
  const { pathname, search, hash } = window.location;
  return pathname === CALLBACK_PATH ? '/' : `${pathname}${search}${hash}`;
}

export function AuthProvider({ manager, children }: { manager: UserManager; children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<Status>('loading');
  const [error, setError] = useState<string | null>(null);
  const renewing = useRef<Promise<User | null> | null>(null);

  const renew = useCallback(async (): Promise<User | null> => {
    renewing.current ??= manager
      .signinSilent()
      .catch(() => null)
      .finally(() => {
        renewing.current = null;
      });
    const renewed = await renewing.current;
    if (!renewed) {
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
          const signedIn = await manager.signinRedirectCallback();
          const state = signedIn.state as ReturnState | undefined;
          window.history.replaceState(null, '', state?.returnTo || '/');
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
    return () => {
      active = false;
      manager.events.removeUserLoaded(loaded);
      manager.events.removeUserUnloaded(unloaded);
      manager.events.removeUserSignedOut(unloaded);
    };
  }, [manager, renew]);

  const signIn = useCallback(
    async ({ register = false }: { register?: boolean } = {}) => {
      const state: ReturnState = { returnTo: currentLocation() };
      await manager.signinRedirect({ state, prompt: register ? 'create' : undefined });
    },
    [manager],
  );

  const signOut = useCallback(async () => {
    const current = await manager.getUser();
    await manager.removeUser();
    setUser(null);
    setStatus('signedOut');
    try {
      await manager.signoutRedirect({ id_token_hint: current?.id_token });
    } catch {
      // The identity provider is unreachable: the local session is gone anyway.
    }
  }, [manager]);

  const getToken = useCallback(async () => {
    let current = await manager.getUser();
    if (current && (current.expires_in ?? 0) < RENEW_MARGIN_SECONDS) current = await renew();
    return current?.access_token ?? null;
  }, [manager, renew]);

  const handleUnauthorized = useCallback(() => {
    void renew();
  }, [renew]);

  const value = useMemo<AuthState>(
    () => ({ status, user, error, signIn, signOut, getToken, handleUnauthorized }),
    [status, user, error, signIn, signOut, getToken, handleUnauthorized],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
