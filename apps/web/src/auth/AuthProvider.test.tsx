import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { User, UserManager } from 'oidc-client-ts';
import { useState } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ToastProvider } from '../components/feedback';
import { AuthProvider, useAuth } from './AuthProvider';

function Controls() {
  const auth = useAuth();
  const [token, setToken] = useState<string | null>(null);
  return (
    <>
      <span>{auth.status}</span>
      <span>{token}</span>
      <button onClick={() => void auth.signIn({ register: true })}>Register</button>
      <button onClick={() => void auth.signOut()}>Sign out</button>
      <button onClick={() => void auth.getToken().then(setToken)}>Token</button>
    </>
  );
}

function makeUser(accessToken = 'access', expiresIn?: number) {
  return new User({
    access_token: accessToken, refresh_token: 'refresh', id_token: 'id', token_type: 'Bearer',
    expires_at: expiresIn === undefined ? undefined : Math.floor(Date.now() / 1000) + expiresIn,
    profile: { sub: 'alice', iss: 'https://identity.test', aud: 'web', exp: 9999999999, iat: 1 },
  });
}

function setup(nativeLogin = true, signedIn: boolean | User = false) {
  const manager = new UserManager({
    authority: 'https://identity.test', client_id: 'web', redirect_uri: 'http://localhost/callback',
  });
  const user = signedIn instanceof User ? signedIn : makeUser();
  vi.spyOn(manager, 'getUser').mockResolvedValue(signedIn ? user : null);
  vi.spyOn(manager, 'signinRedirect').mockResolvedValue();
  vi.spyOn(manager, 'signinSilent').mockResolvedValue(null);
  vi.spyOn(manager, 'signoutRedirect').mockResolvedValue();
  vi.spyOn(manager, 'revokeTokens').mockResolvedValue();
  vi.spyOn(manager, 'removeUser').mockResolvedValue();
  render(<ToastProvider><AuthProvider manager={manager} nativeLogin={nativeLogin}><Controls /></AuthProvider></ToastProvider>);
  return manager;
}

beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, '', '/accounts/7');
});
afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, 'locks');
});

it('retains the requested destination across verification and a fresh login', async () => {
  const manager = setup();
  await screen.findByText('signedOut');
  await userEvent.click(screen.getByRole('button', { name: 'Register' }));
  expect(manager.signinRedirect).toHaveBeenLastCalledWith({ state: { returnTo: '/accounts/7' }, prompt: 'login' });
  window.history.replaceState(null, '', '/verify-email?userID=alice');
  await userEvent.click(screen.getByRole('button', { name: 'Register' }));
  expect(manager.signinRedirect).toHaveBeenLastCalledWith({ state: { returnTo: '/accounts/7' }, prompt: 'login' });
});

it('preserves hosted registration when native login is disabled', async () => {
  const manager = setup(false);
  await screen.findByText('signedOut');
  await userEvent.click(screen.getByRole('button', { name: 'Register' }));
  expect(manager.signinRedirect).toHaveBeenCalledWith({ state: { returnTo: '/accounts/7' }, prompt: 'create' });
});

it('terminates the native session and revokes tokens without showing hosted logout', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{"step":"signed-out"}', { headers: { 'Content-Type': 'application/json' } })));
  const manager = setup(true, true);
  await screen.findByText('signedIn');
  await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));
  await screen.findByText('signedOut');
  expect(manager.revokeTokens).toHaveBeenCalledWith(['access_token', 'refresh_token']);
  expect(manager.removeUser).toHaveBeenCalled();
  expect(manager.signoutRedirect).not.toHaveBeenCalled();
});

it('reports failed remote logout and retains tokens so it can be retried', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{"detail":"Try again later"}', { status: 503, headers: { 'Content-Type': 'application/json' } })));
  const manager = setup(true, true);
  await screen.findByText('signedIn');
  await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Try again later'));
  expect(manager.removeUser).not.toHaveBeenCalled();
  expect(manager.revokeTokens).not.toHaveBeenCalled();
  expect(screen.getByText('signedIn')).toBeInTheDocument();
});

it('clears local tokens after native sign-out even when revocation fails', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{"step":"signed-out"}', { headers: { 'Content-Type': 'application/json' } })));
  const manager = setup(true, true);
  vi.mocked(manager.revokeTokens).mockRejectedValue(new Error('offline'));
  await screen.findByText('signedIn');
  await userEvent.click(screen.getByRole('button', { name: 'Sign out' }));
  await screen.findByText('signedOut');
  expect(manager.removeUser).toHaveBeenCalled();
});

it('signs out when another tab removes the stored tokens', async () => {
  const manager = setup(true, true);
  await screen.findByText('signedIn');
  vi.mocked(manager.getUser).mockResolvedValue(null);
  window.dispatchEvent(new StorageEvent('storage', { key: 'oidc.user:https://identity.test:web', storageArea: localStorage }));
  await screen.findByText('signedOut');
});

it('renews one tab at a time and reuses a token another tab already renewed', async () => {
  const request = vi.fn((_name: string, task: () => Promise<unknown>) => task());
  Object.defineProperty(navigator, 'locks', { value: { request }, configurable: true });
  const manager = setup(true, makeUser('expiring', 10));
  await screen.findByText('signedIn');
  vi.mocked(manager.getUser)
    .mockResolvedValueOnce(makeUser('expiring', 10))
    .mockResolvedValueOnce(makeUser('renewed-elsewhere', 3600));
  await userEvent.click(screen.getByRole('button', { name: 'Token' }));
  expect(await screen.findByText('renewed-elsewhere')).toBeInTheDocument();
  expect(request).toHaveBeenCalledWith('picciuli-token-renewal', expect.any(Function));
  expect(manager.signinSilent).not.toHaveBeenCalled();
});

it('refreshes an expiring token once, while holding the lock', async () => {
  const request = vi.fn((_name: string, task: () => Promise<unknown>) => task());
  Object.defineProperty(navigator, 'locks', { value: { request }, configurable: true });
  const manager = setup(true, makeUser('expiring', 10));
  vi.mocked(manager.signinSilent).mockResolvedValue(makeUser('renewed', 3600));
  await screen.findByText('signedIn');
  await userEvent.click(screen.getByRole('button', { name: 'Token' }));
  expect(await screen.findByText('renewed')).toBeInTheDocument();
  expect(request).toHaveBeenCalledTimes(1);
  expect(manager.signinSilent).toHaveBeenCalledTimes(1);
});
