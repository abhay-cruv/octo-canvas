import { queryOptions } from '@tanstack/react-query';
import { api } from './api';

export const meQueryOptions = queryOptions({
  queryKey: ['me'],
  queryFn: async () => {
    const { data, response } = await api.GET('/api/me');
    if (response.status === 401) return null;
    if (!data) throw new Error('Failed to fetch /api/me');
    return data;
  },
  staleTime: 30_000,
  retry: false,
});

export function availableReposQueryOptions(
  page: number,
  perPage = 30,
  q?: string,
  scopeMine = true,
) {
  const trimmed = q?.trim() ?? '';
  return queryOptions({
    queryKey: ['repos', 'available', page, perPage, trimmed, scopeMine],
    queryFn: async () => {
      const { data, response, error } = await api.GET('/api/repos/available', {
        params: {
          query: {
            page,
            per_page: perPage,
            scope_mine: scopeMine,
            ...(trimmed ? { q: trimmed } : {}),
          },
        },
      });
      if (response.status === 403) return { reauth: true as const };
      if (error || !data) throw error ?? new Error('failed to load repos');
      return {
        reauth: false as const,
        repos: data.repos,
        page: data.page,
        per_page: data.per_page,
        has_more: data.has_more,
      };
    },
    staleTime: 30_000,
    retry: false,
    placeholderData: (prev) => prev,
  });
}

export const connectedReposQueryOptions = queryOptions({
  queryKey: ['repos', 'connected'],
  queryFn: async () => {
    const { data, error } = await api.GET('/api/repos');
    if (error) throw error;
    return data ?? [];
  },
});

export const sandboxesQueryOptions = queryOptions({
  queryKey: ['sandboxes'],
  queryFn: async () => {
    const { data, error } = await api.GET('/api/sandboxes');
    if (error) throw error;
    return data ?? [];
  },
});
