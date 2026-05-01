import createClient from 'openapi-fetch';
import type { paths } from '@vibe-platform/api-types';

const baseUrl = import.meta.env.VITE_ORCHESTRATOR_BASE_URL;
if (!baseUrl) {
  throw new Error('VITE_ORCHESTRATOR_BASE_URL is not set');
}

export const api = createClient<paths>({
  baseUrl,
  credentials: 'include',
});
