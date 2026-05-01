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
