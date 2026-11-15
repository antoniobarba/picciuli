import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useAuth } from './AuthProvider';
import { loginRequest, passwordHint, type LoginResult } from './login';

type Screen = LoginResult['step'] | 'register' | 'forgot' | 'reset-password';

export function isIdentityPath(): boolean {
  return ['/login', '/verify-email', '/reset-password'].includes(window.location.pathname);
}

/** Picciuli-owned identity screens; credentials are never placed in browser storage. */
export function IdentityScreen() {
  const auth = useAuth();
  const [link] = useState(() => {
    const query = new URLSearchParams(window.location.search);
    return { userId: query.get('userID') || '', code: query.get('code') || '', request: query.get('authRequest') || '' };
  });
  const [screen, setScreen] = useState<Screen>(() =>
    window.location.pathname === '/reset-password' ? 'reset-password'
      : window.location.pathname === '/verify-email' ? 'verify-email' : 'login');
  const [options, setOptions] = useState<LoginResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [secret, setSecret] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const started = useRef<Promise<LoginResult> | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    let active = true;
    if (link.userId || link.code) {
      // Do not leave one-time codes in history or referrer URLs.
      const userQuery = link.userId ? `?userID=${encodeURIComponent(link.userId)}` : '';
      window.history.replaceState(null, '', window.location.pathname + userQuery);
    }
    if (link.request) {
      started.current ??= loginRequest('start', { auth_request: link.request });
      void started.current.then((result) => {
        if (!active) return;
        setOptions(result);
        if (sessionStorage.getItem('picciuli-register') === 'true' && result.can_register) {
          setScreen('register');
        }
        sessionStorage.removeItem('picciuli-register');
      }).catch((failure: unknown) => {
        if (active) setError(failure instanceof Error ? failure.message : 'Cannot start sign-in.');
      });
    }
    return () => { active = false; };
  }, [link]);

  const changeScreen = (next: Screen) => {
    formRef.current?.reset();
    setShowPassword(false);
    setSecret('');
    setError('');
    setNotice('');
    setScreen(next);
  };

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await action();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The request failed. Please try again.');
    } finally {
      setBusy(false);
    }
  };

  const accept = (result: LoginResult) => {
    if (result.step === 'complete') {
      const callback = new URL(result.callback_url || '', window.location.origin);
      if (callback.origin !== window.location.origin || callback.pathname !== '/callback') {
        throw new Error('The sign-in callback is invalid.');
      }
      window.location.assign(callback.href);
    } else {
      changeScreen(result.step);
    }
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const text = (key: string) => String(data.get(key) || '');
    void run(async () => {
      let result: LoginResult;
      if (screen === 'login') {
        result = await loginRequest('login', { username: text('username'), password: text('password') });
      } else if (screen === 'register') {
        result = await loginRequest('register', {
          username: text('username'), password: text('password'),
          given_name: text('given_name'), family_name: text('family_name'),
        });
      } else if (screen === 'forgot') {
        result = await loginRequest('reset-request', { username: text('username') });
      } else if (screen === 'reset-password') {
        result = await loginRequest('reset-password', {
          user_id: link.userId, code: text('code'), password: text('password'),
        });
      } else if (screen === 'change-password') {
        result = await loginRequest('change-password', {
          current_password: text('current_password'), password: text('password'),
        });
      } else if (screen === 'verify-email' && link.userId) {
        result = await loginRequest('verify-email', { user_id: link.userId, code: text('code') });
      } else {
        result = await loginRequest(screen === 'setup-totp' ? 'confirm-totp' : 'verify', { code: text('code') });
      }
      accept(result);
    });
  };

  const titles: Record<Screen, string> = {
    login: 'Welcome back', register: 'Create your account', registered: 'Check your email',
    'verify-email': 'Verify your email', verified: 'Email verified',
    forgot: 'Forgot your password?', 'reset-sent': 'Check your email',
    'reset-password': 'Choose a new password', 'password-reset': 'Password updated',
    'change-password': 'Update your password', totp: 'Authenticator code',
    'setup-totp': 'Protect your account', complete: 'Signing you in', 'signed-out': 'Signed out',
  };
  const success = ['verified', 'password-reset', 'reset-sent', 'signed-out'].includes(screen);
  const hasPassword = ['login', 'register', 'reset-password', 'change-password'].includes(screen);
  const hasCode = ['registered', 'verify-email', 'totp', 'setup-totp', 'reset-password'].includes(screen);
  const ready = !link.request || options !== null;
  const canSubmit = ready && (screen !== 'login' || options !== null)
    && (screen !== 'setup-totp' || Boolean(secret));

  return (
    <main className="identity">
      <a className="identity-brand" href="/" aria-label="Picciuli home">
        <img src="/logo.svg" alt="" width="48" height="48" /><span>Picciuli</span>
      </a>
      <section className="identity-card" aria-labelledby="identity-title" aria-busy={busy || !ready}>
        <h1 id="identity-title">{titles[screen]}</h1>
        <p className="muted">Your money, your plans. All in one place.</p>
        {error && <p className="form-error" role="alert">{error}</p>}
        {notice && <p role="status">{notice}</p>}
        {screen === 'reset-sent' && <p>If that email belongs to an account, a password reset link is on its way. Check your spam folder too.</p>}
        {['registered', 'verify-email'].includes(screen) && <p>Enter the code from your email to finish verifying your account. You can also open the link in the message.</p>}
        {screen === 'totp' && <p>Enter the current code from your authenticator app. If you just set it up, wait for the next code.</p>}
        {screen === 'setup-totp' && (
          <>
            <p>Your account requires two-step verification. Add a time-based account in your authenticator app using this setup key.</p>
            {secret ? <code className="identity-secret">{secret}</code> : (
              <button className="button" type="button" disabled={busy} onClick={() => void run(async () => {
                const result = await loginRequest('setup-totp');
                if (!result.secret) throw new Error('No authenticator setup key was returned.');
                setSecret(result.secret);
              })}>Get setup key</button>
            )}
          </>
        )}
        {!success && (
          <form ref={formRef} onSubmit={submit} className="identity-form">
            <fieldset disabled={busy || !canSubmit}>
              {screen === 'register' && (
                <div className="identity-names">
                  <label>First name<input name="given_name" autoComplete="given-name" maxLength={200} required /></label>
                  <label>Last name<input name="family_name" autoComplete="family-name" maxLength={200} required /></label>
                </div>
              )}
              {['login', 'register', 'forgot'].includes(screen) && (
                <label>{screen === 'login' ? 'Email or username' : 'Email'}
                  <input name="username" type={screen === 'login' ? 'text' : 'email'} autoComplete="username" autoCapitalize="none" spellCheck={false} maxLength={200} required />
                </label>
              )}
              {screen === 'change-password' && (
                <label>Current password<input name="current_password" type="password" autoComplete="current-password" maxLength={200} required /></label>
              )}
              {hasPassword && (
                <>
                  <label>{screen === 'login' ? 'Password' : 'New password'}
                    <input name="password" type={showPassword ? 'text' : 'password'} autoComplete={screen === 'login' ? 'current-password' : 'new-password'} maxLength={200} required aria-describedby={screen !== 'login' ? 'password-hint' : undefined} />
                  </label>
                  <label className="identity-show"><input type="checkbox" checked={showPassword} onChange={(e) => setShowPassword(e.target.checked)} />Show password</label>
                  {screen !== 'login' && <small id="password-hint" className="muted">{passwordHint(options?.password_policy)}</small>}
                </>
              )}
              {hasCode && (
                <label>Verification code<input key={screen} name="code" defaultValue={link.code} autoComplete="one-time-code" maxLength={20} required /></label>
              )}
              <button className="button primary large" type="submit">
                {busy ? 'Please wait...' : screen === 'login' ? 'Sign in' : screen === 'register' ? 'Create account'
                  : screen === 'forgot' ? 'Send reset link' : hasPassword ? 'Save password' : 'Continue'}
              </button>
            </fieldset>
          </form>
        )}
        <div className="identity-links">
          {screen === 'login' && options?.can_reset && <button type="button" disabled={busy} onClick={() => changeScreen('forgot')}>Forgot password?</button>}
          {screen === 'login' && options?.can_register && <button type="button" disabled={busy} onClick={() => changeScreen('register')}>Create an account</button>}
          {['registered', 'verify-email'].includes(screen) && !link.userId && (
            <button type="button" disabled={busy} onClick={() => void run(async () => {
              await loginRequest('resend-email');
              setNotice('Another verification email has been requested. Check your inbox.');
            })}>Resend email</button>
          )}
          {(screen !== 'login' || error || !link.request) && (
            <button type="button" disabled={busy} onClick={() => void run(() => auth.signIn())}>
              {success ? 'Continue to sign in' : 'Back to sign in'}
            </button>
          )}
        </div>
      </section>
      <p className="muted small">Your financial data stays private to your account.</p>
    </main>
  );
}
