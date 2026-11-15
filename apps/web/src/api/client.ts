import createClient, { type Client, type Middleware } from 'openapi-fetch';
import type { paths } from './schema';

export type ApiClient = Client<paths>;

/** An error answered by the API: `{"error": "<code>", "detail": "<message>"}`. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    detail: string,
    readonly errors: unknown[] = [],
  ) {
    super(detail);
    this.name = 'ApiError';
  }
}

interface ErrorBody {
  error?: unknown;
  detail?: unknown;
  errors?: unknown;
}

function describeValidation(errors: unknown[]): string | null {
  const first = errors[0] as { msg?: unknown; loc?: unknown } | undefined;
  if (!first || typeof first.msg !== 'string') return null;
  const where = Array.isArray(first.loc) ? first.loc.filter((part) => part !== 'body').join('.') : '';
  return where ? `${where}: ${first.msg}` : first.msg;
}

export function toApiError(status: number, body: unknown): ApiError {
  const data = (body && typeof body === 'object' ? body : {}) as ErrorBody;
  const code = typeof data.error === 'string' ? data.error : `http_${status}`;
  const errors = Array.isArray(data.errors) ? data.errors : [];
  let detail = typeof data.detail === 'string' ? data.detail : '';
  if (code === 'invalid_request') detail = describeValidation(errors) ?? detail;
  if (!detail) detail = status >= 500 ? 'The server had a problem; try again later.' : `Request failed (${status})`;
  return new ApiError(status, code, detail, errors);
}

/** Return the body of a successful call or throw an `ApiError`. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: { data?: T; error?: unknown; response: Response };
  try {
    result = await call;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, 'network_error', 'Cannot reach the server. Check your connection.');
  }
  if (!result.response.ok) throw toApiError(result.response.status, result.error);
  return result.data as T;
}

export interface ApiOptions {
  baseUrl: string;
  getToken: () => Promise<string | null>;
  onUnauthorized: () => void;
  fetch?: typeof fetch;
}

export function createApi({ baseUrl, getToken, onUnauthorized, fetch: fetchImpl }: ApiOptions): ApiClient {
  const client = createClient<paths>({ baseUrl, fetch: fetchImpl });
  const auth: Middleware = {
    async onRequest({ request }) {
      const token = await getToken();
      if (token) request.headers.set('Authorization', `Bearer ${token}`);
      return request;
    },
    onResponse({ response }) {
      if (response.status === 401) onUnauthorized();
      return response;
    },
  };
  client.use(auth);
  return client;
}
