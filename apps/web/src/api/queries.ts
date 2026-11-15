import {
  keepPreviousData,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
  type QueryKey,
  type UseQueryResult,
} from '@tanstack/react-query';
import { useMemo } from 'react';
import type { Day } from '../lib/dates';
import { MoneyFormat } from '../lib/money';
import { applyMove, type Positioned } from '../lib/reorder';
import { unwrap, type ApiClient } from './client';
import { useApi } from './context';
import type { LatestPrice, Security } from './types';

/**
 * Every write can change balances, summaries and valuations everywhere, so a
 * successful mutation simply refetches all the data on screen.
 */
export function useApiMutation<TVariables, TResult = unknown>(
  run: (api: ApiClient, variables: TVariables) => Promise<TResult>,
) {
  const api = useApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (variables: TVariables) => run(api, variables),
    onSuccess: () => client.invalidateQueries(),
  });
}

export interface Move {
  id: number;
  /** New 1-based position among its siblings. */
  position: number;
}

/**
 * Move an item of the list cached under `queryKey`: the new order shows at
 * once, and the old one comes back if the server refuses the move.
 */
export function useOptimisticMove<T extends Positioned>(
  queryKey: QueryKey,
  run: (api: ApiClient, move: Move) => Promise<unknown>,
  sameGroup?: (a: T, b: T) => boolean,
) {
  const api = useApi();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (move: Move) => run(api, move),
    onMutate: async ({ id, position }) => {
      await client.cancelQueries({ queryKey });
      const previous = client.getQueryData<T[]>(queryKey);
      if (previous) client.setQueryData(queryKey, applyMove(previous, id, position, sameGroup));
      return { previous };
    },
    onError: (_error, _move, context) => {
      if (context?.previous) client.setQueryData(queryKey, context.previous);
    },
    onSettled: () => client.invalidateQueries(),
  });
}

export function useSettings() {
  const api = useApi();
  return useQuery({
    queryKey: ['settings'],
    queryFn: () => unwrap(api.GET('/api/v1/settings')),
    staleTime: 60_000,
  });
}

const DEFAULT_MONEY = new MoneyFormat('€', 2);

export function useMoney(): MoneyFormat {
  const { data } = useSettings();
  return useMemo(
    () => (data ? new MoneyFormat(data.currency, data.minor_digits) : DEFAULT_MONEY),
    [data],
  );
}

export function useMe() {
  const api = useApi();
  return useQuery({ queryKey: ['me'], queryFn: () => unwrap(api.GET('/api/v1/me')), staleTime: Infinity });
}

export function useAccounts(includeClosed = true) {
  const api = useApi();
  return useQuery({
    queryKey: ['accounts', includeClosed],
    queryFn: () => unwrap(api.GET('/api/v1/accounts', { params: { query: { include_closed: includeClosed } } })),
  });
}

export function useCategories() {
  const api = useApi();
  return useQuery({ queryKey: ['categories'], queryFn: () => unwrap(api.GET('/api/v1/categories')) });
}

export function usePeriods() {
  const api = useApi();
  return useQuery({ queryKey: ['periods'], queryFn: () => unwrap(api.GET('/api/v1/periods')) });
}

/** Periods covering a day, most recently started first. */
export function usePeriodsOn(day: Day) {
  const api = useApi();
  return useQuery({
    queryKey: ['periods', 'on', day],
    queryFn: () => unwrap(api.GET('/api/v1/periods', { params: { query: { on: day } } })),
    placeholderData: keepPreviousData,
  });
}

export function usePeriodSummary(periodId: number | null) {
  const api = useApi();
  return useQuery({
    queryKey: ['period-summary', periodId],
    queryFn: () =>
      unwrap(api.GET('/api/v1/periods/{period_id}/summary', { params: { path: { period_id: periodId! } } })),
    enabled: periodId !== null,
    placeholderData: keepPreviousData,
  });
}

export function useBudgetReport(periodId: number | null) {
  const api = useApi();
  return useQuery({
    queryKey: ['budget-report', periodId],
    queryFn: () =>
      unwrap(api.GET('/api/v1/periods/{period_id}/budget-report', { params: { path: { period_id: periodId! } } })),
    enabled: periodId !== null,
    placeholderData: keepPreviousData,
  });
}

export interface TransactionFilter {
  start?: Day;
  end?: Day;
  account_id?: number;
  category_id?: number;
  /** With `category_id`, also match its subcategories. */
  include_subcategories?: boolean;
  text?: string;
  newest_first?: boolean;
}

export function useTransactions(filter: TransactionFilter, enabled = true) {
  const api = useApi();
  return useQuery({
    queryKey: ['transactions', filter],
    queryFn: () => unwrap(api.GET('/api/v1/transactions', { params: { query: filter } })),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useBalances(asOf?: Day) {
  const api = useApi();
  return useQuery({
    queryKey: ['balances', asOf ?? null],
    queryFn: () =>
      unwrap(api.GET('/api/v1/accounts/balances', { params: { query: { as_of: asOf, include_closed: false } } })),
    placeholderData: keepPreviousData,
  });
}

/** Market value of every open account, as of a day. */
export function useValuations(asOf?: Day) {
  const api = useApi();
  return useQuery({
    queryKey: ['valuations', asOf ?? null],
    queryFn: () => unwrap(api.GET('/api/v1/investments/valuations', { params: { query: { as_of: asOf } } })),
    placeholderData: keepPreviousData,
  });
}

/** Net worth with holdings at market value. */
export function useNetWorth(asOf?: Day) {
  const api = useApi();
  return useQuery({
    queryKey: ['net-worth', asOf ?? null],
    queryFn: () => unwrap(api.GET('/api/v1/investments/net-worth', { params: { query: { as_of: asOf } } })),
    placeholderData: keepPreviousData,
  });
}

export function useRegister(accountId: number) {
  const api = useApi();
  return useQuery({
    queryKey: ['register', accountId],
    queryFn: () =>
      unwrap(api.GET('/api/v1/accounts/{account_id}/register', { params: { path: { account_id: accountId } } })),
  });
}

export function useSecurities() {
  const api = useApi();
  return useQuery({ queryKey: ['securities'], queryFn: () => unwrap(api.GET('/api/v1/securities')) });
}

/** Latest price of each security, keyed by security id. */
export function useLatestPrices(securities: readonly Security[] | undefined): Map<number, LatestPrice> {
  const api = useApi();
  const results: UseQueryResult<LatestPrice>[] = useQueries({
    queries: (securities ?? []).map((security) => ({
      queryKey: ['latest-price', security.id],
      queryFn: () =>
        unwrap(
          api.GET('/api/v1/securities/{security_id}/latest-price', {
            params: { path: { security_id: security.id } },
          }),
        ),
    })),
  });
  const map = new Map<number, LatestPrice>();
  (securities ?? []).forEach((security, index) => {
    const data = results[index]?.data;
    if (data) map.set(security.id, data);
  });
  return map;
}

export function usePriceProviders() {
  const api = useApi();
  return useQuery({
    queryKey: ['providers', 'prices'],
    queryFn: () => unwrap(api.GET('/api/v1/providers/prices')),
    staleTime: Infinity,
  });
}

export function useRateProviders() {
  const api = useApi();
  return useQuery({
    queryKey: ['providers', 'rates'],
    queryFn: () => unwrap(api.GET('/api/v1/providers/rates')),
    staleTime: Infinity,
  });
}
