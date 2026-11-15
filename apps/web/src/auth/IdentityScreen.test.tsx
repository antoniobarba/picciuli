import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IdentityScreen } from './IdentityScreen';

const signIn = vi.fn(async () => {});
vi.mock('./AuthProvider', () => ({ useAuth: () => ({ signIn }) }));

function mockServer(results: Record<string, object>) {
  const requests: { action: string; body: unknown }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit) => {
    const action = url.split('/').at(-1)!;
    requests.push({ action, body: JSON.parse(String(options.body)) });
    return new Response(JSON.stringify(results[action] || { detail: 'Not accepted' }), {
      status: action in results ? 200 : 400, headers: { 'Content-Type': 'application/json' },
    });
  }));
  return requests;
}

const start = { step: 'login', can_register: true, can_reset: true, password_policy: { minLength: '12' } };

beforeEach(() => {
  window.history.replaceState(null, '', '/login?authRequest=V2_test');
  sessionStorage.clear();
});
afterEach(() => { vi.unstubAllGlobals(); });

describe('native identity screens', () => {
  it('keeps login errors in Picciuli without persisting passwords', async () => {
    const requests = mockServer({ start });
    render(<IdentityScreen />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByLabelText('Password')).toBeEnabled());
    await user.type(screen.getByLabelText('Email or username'), 'alice@example.test');
    await user.type(screen.getByLabelText('Password'), 'private-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Not accepted');
    expect(requests.at(-1)).toEqual({ action: 'login', body: { username: 'alice@example.test', password: 'private-password' } });
    expect(JSON.stringify(sessionStorage)).not.toContain('private-password');
    expect(JSON.stringify(localStorage)).not.toContain('private-password');
  });

  it('registers and verifies email before offering sign-in', async () => {
    sessionStorage.setItem('picciuli-register', 'true');
    const requests = mockServer({ start, register: { step: 'registered' }, verify: { step: 'verified' } });
    render(<IdentityScreen />);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('First name'), 'Alice');
    await user.type(screen.getByLabelText('Last name'), 'Example');
    await user.type(screen.getByLabelText('Email', { exact: true }), 'alice@example.test');
    await user.type(screen.getByLabelText('New password'), 'private-password');
    expect(screen.getByText('At least 12 characters.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    await user.type(await screen.findByLabelText('Verification code'), 'email-code');
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByRole('heading', { name: 'Email verified' })).toBeInTheDocument();
    expect(requests.at(-1)).toEqual({ action: 'verify', body: { code: 'email-code' } });
    expect(screen.queryByLabelText('New password')).not.toBeInTheDocument();
  });

  it('opens recovery links without automatically consuming the code', async () => {
    window.history.replaceState(null, '', '/reset-password?userID=user&code=reset-code');
    const requests = mockServer({ 'reset-password': { step: 'password-reset' } });
    render(<IdentityScreen />);
    expect(requests).toHaveLength(0);
    expect(window.location.search).toBe('?userID=user');
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('New password'), 'new-password');
    await user.click(screen.getByRole('button', { name: 'Save password' }));
    expect(await screen.findByRole('heading', { name: 'Password updated' })).toBeInTheDocument();
    expect(requests).toEqual([{ action: 'reset-password', body: { user_id: 'user', code: 'reset-code', password: 'new-password' } }]);
  });

  it('handles password recovery and authenticator challenges in-app', async () => {
    mockServer({ start, login: { step: 'totp' }, verify: { step: 'totp' } });
    render(<IdentityScreen />);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByLabelText('Password')).toBeEnabled());
    await user.type(screen.getByLabelText('Email or username'), 'alice');
    await user.type(screen.getByLabelText('Password'), 'private-password');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('heading', { name: 'Authenticator code' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
  });

  it('does not offer disabled registration or recovery', async () => {
    mockServer({ start: { step: 'login', can_register: false, can_reset: false } });
    render(<IdentityScreen />);
    await waitFor(() => expect(screen.getByLabelText('Password')).toBeEnabled());
    expect(screen.queryByRole('button', { name: 'Create an account' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Forgot password?' })).not.toBeInTheDocument();
  });
});
