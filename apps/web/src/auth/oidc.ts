import { UserManager, WebStorageStateStore, type User } from 'oidc-client-ts';
import type { AppConfig } from '../config';

/**
 * Authorization Code flow with PKCE against Zitadel. Tokens live in
 * `localStorage` so an installed app stays signed in between launches; the
 * refresh token (scope `offline_access`) renews the access token silently.
 */
export function createUserManager(config: AppConfig): UserManager {
  const origin = window.location.origin;
  return new UserManager({
    authority: config.oidcIssuer,
    client_id: config.oidcClientId,
    redirect_uri: `${origin}/callback`,
    post_logout_redirect_uri: `${origin}/`,
    response_type: 'code',
    scope: [
      'openid',
      'profile',
      'email',
      'offline_access',
      // Puts the project id in the token audience, which the API checks.
      `urn:zitadel:iam:org:project:id:${config.oidcProjectId}:aud`,
    ].join(' '),
    userStore: new WebStorageStateStore({ store: window.localStorage }),
    automaticSilentRenew: true,
    loadUserInfo: false,
  });
}

export interface ReturnState {
  returnTo: string;
}

export function displayName(user: User | null): string {
  const profile = user?.profile;
  return profile?.name || profile?.preferred_username || profile?.email || 'Signed in';
}
