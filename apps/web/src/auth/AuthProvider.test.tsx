import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { User, UserManager } from 'oidc-client-ts';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ToastProvider } from '../components/feedback';
import { AuthProvider, useAuth } from './AuthProvider';

function Controls() {
  const auth = useAuth();
  return (
    <>
      <span>{auth.status}</span>
      <button onClick={() => void auth.signIn({ register: true })}>Register</button>
      <button onClick={() => void auth.signOut()}>Sign out</button>
    </>
  );
}

function setup(nativeLogin = true, signedIn = false) {
  const manager = new UserManager({
    authority: 'https://identity.test', client_id: 'web', redirect_uri: 'http://localhost/callback',
  });
  const user = new User({
    access_token: 'access', refresh_token: 'refresh', id_token: 'id', token_type: 'Bearer',
    profile: { sub: 'alice', iss: 'https://identity.test', aud: 'web', exp: 9999999999, iat: 1 },
  });
  vi.spyOn(manager, 'getUser').mockResolvedValue(signedIn ? user : null);
  vi.spyOn(manager, 'signinRedirect').mockResolvedValue();
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
afterEach(() => { vi.unstubAllGlobals(); });

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
