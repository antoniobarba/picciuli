/**
 * Runtime configuration. Production images serve `/config.json`, generated from
 * environment variables when the container starts, so one build fits every
 * environment. Development falls back to `VITE_*` variables (see `.env.example`).
 */

export interface AppConfig {
  /** Base URL of the API, without `/api/v1`; empty means the same origin. */
  apiUrl: string;
  /** OpenID Connect issuer, e.g. `https://auth.picciuli.party`. */
  oidcIssuer: string;
  /** Client id of the front-end application in Zitadel. */
  oidcClientId: string;
  /** Zitadel project id: requested as token audience so the API accepts it. */
  oidcProjectId: string;
  /** Enabled only after the confidential login backend is provisioned. */
  nativeLogin?: boolean;
}

function fromEnv(): Partial<AppConfig> {
  const env = import.meta.env;
  return {
    apiUrl: env.VITE_API_URL ?? '',
    oidcIssuer: env.VITE_OIDC_ISSUER,
    oidcClientId: env.VITE_OIDC_CLIENT_ID,
    oidcProjectId: env.VITE_OIDC_PROJECT_ID,
    nativeLogin: env.VITE_NATIVE_LOGIN === 'true',
  };
}

export async function loadConfig(): Promise<AppConfig> {
  let remote: Partial<AppConfig> = {};
  try {
    const response = await fetch('/config.json', { cache: 'no-store' });
    if (response.ok && response.headers.get('content-type')?.includes('json')) {
      remote = (await response.json()) as Partial<AppConfig>;
    }
  } catch {
    // Offline or not provided: use the build-time values.
  }
  const local = fromEnv();
  const pick = (key: Exclude<keyof AppConfig, 'nativeLogin'>) => (remote[key] || local[key] || '').trim();
  const config: AppConfig = {
    apiUrl: pick('apiUrl').replace(/\/+$/, ''),
    oidcIssuer: pick('oidcIssuer').replace(/\/+$/, ''),
    oidcClientId: pick('oidcClientId'),
    oidcProjectId: pick('oidcProjectId'),
    nativeLogin: remote.nativeLogin ?? local.nativeLogin ?? false,
  };
  const missing = (['oidcIssuer', 'oidcClientId', 'oidcProjectId'] as const).filter((key) => !config[key]);
  if (missing.length) throw new Error(`Missing configuration: ${missing.join(', ')}`);
  return config;
}
