export type LoginStep = 'login' | 'registered' | 'verify-email' | 'verified' | 'totp'
  | 'setup-totp' | 'change-password' | 'complete' | 'reset-sent' | 'password-reset' | 'signed-out';

export interface PasswordPolicy {
  minLength?: string;
  requiresUppercase?: boolean;
  requiresLowercase?: boolean;
  requiresNumber?: boolean;
  requiresSymbol?: boolean;
}

export interface LoginResult {
  step: LoginStep;
  can_register?: boolean;
  can_reset?: boolean;
  password_policy?: PasswordPolicy;
  callback_url?: string;
  secret?: string;
}

const steps = new Set<string>([
  'login', 'registered', 'verify-email', 'verified', 'totp', 'setup-totp',
  'change-password', 'complete', 'reset-sent', 'password-reset', 'signed-out',
]);

/** Only the same-origin backend receives credentials; never cache its responses. */
export async function loginRequest(action: string, body: object = {}): Promise<LoginResult> {
  const response = await fetch(`/api/auth/${action}`, {
    method: 'POST',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.headers.get('content-type')?.includes('application/json')) {
    throw new Error('Sign-in is temporarily unavailable. Please try again later.');
  }
  const result: unknown = await response.json();
  if (!response.ok) {
    const detail = result && typeof result === 'object' && 'detail' in result ? result.detail : null;
    throw new Error(typeof detail === 'string' ? detail : 'The request failed. Please try again.');
  }
  if (!result || typeof result !== 'object' || !('step' in result)
    || typeof result.step !== 'string' || !steps.has(result.step)) {
    throw new Error('The sign-in service returned an invalid response.');
  }
  return result as LoginResult;
}

export function passwordHint(policy?: PasswordPolicy): string {
  if (!policy) return 'Use a strong, unique password.';
  const parts = [
    `At least ${policy.minLength || '8'} characters`,
    policy.requiresUppercase && 'an uppercase letter',
    policy.requiresLowercase && 'a lowercase letter',
    policy.requiresNumber && 'a number',
    policy.requiresSymbol && 'a symbol',
  ].filter(Boolean);
  return `${parts.join(', ')}.`;
}
