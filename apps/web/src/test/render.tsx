import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import type { ReactNode } from 'react';
import { vi } from 'vitest';
import { createApi } from '../api/client';
import { ApiContext } from '../api/context';
import { ConfirmProvider, ToastProvider } from '../components/feedback';

export interface FakeRequest {
  method: string;
  path: string;
  body: unknown;
}

/**
 * Render a component with a real typed API client whose `fetch` answers from
 * `routes` ("GET /api/v1/accounts" → body) and records every request.
 */
export function renderWithApi(ui: ReactNode, routes: Record<string, unknown> = {}) {
  const requests: FakeRequest[] = [];
  const fetchMock = vi.fn(async (input: Request) => {
    const url = new URL(input.url);
    const text = await input.text();
    const body = text ? JSON.parse(text) : null;
    requests.push({ method: input.method, path: url.pathname, body });
    const key = `${input.method} ${url.pathname}`;
    if (key in routes) return Response.json(routes[key], { status: input.method === 'POST' ? 201 : 200 });
    if (input.method !== 'GET') return Response.json(body ?? {}, { status: input.method === 'POST' ? 201 : 200 });
    return Response.json({ error: 'not_found', detail: `no route for ${key}` }, { status: 404 });
  });
  const api = createApi({
    baseUrl: 'http://api.test',
    getToken: async () => 'token',
    onUnauthorized: () => {},
    fetch: fetchMock as unknown as typeof fetch,
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const result = render(
    <QueryClientProvider client={client}>
      <ApiContext.Provider value={api}>
        <ToastProvider>
          <ConfirmProvider>{ui}</ConfirmProvider>
        </ToastProvider>
      </ApiContext.Provider>
    </QueryClientProvider>,
  );
  return { ...result, requests };
}
