import type { components } from '@octo-canvas/api-types';
import { api } from './api';

export type SandboxResponse = components['schemas']['SandboxResponse'];
export type SandboxStatus = SandboxResponse['status'];

export class SandboxStateError extends Error {
  constructor(public readonly detail: string) {
    super(detail);
    this.name = 'SandboxStateError';
  }
}

export async function getOrCreateSandbox(): Promise<SandboxResponse> {
  const { data, error } = await api.POST('/api/sandboxes', {});
  if (error) throw error;
  if (!data) throw new Error('empty response from /api/sandboxes');
  return data;
}

type Transition = 'wake' | 'pause' | 'refresh' | 'reset' | 'destroy';

async function _transition(
  sandboxId: string,
  action: Transition,
): Promise<SandboxResponse> {
  const { data, error, response } = await api.POST(
    `/api/sandboxes/{sandbox_id}/${action}` as
      | '/api/sandboxes/{sandbox_id}/wake'
      | '/api/sandboxes/{sandbox_id}/pause'
      | '/api/sandboxes/{sandbox_id}/refresh'
      | '/api/sandboxes/{sandbox_id}/reset'
      | '/api/sandboxes/{sandbox_id}/destroy',
    { params: { path: { sandbox_id: sandboxId } } },
  );
  if (response.status === 409) {
    const detail =
      typeof error === 'object' && error && 'detail' in error
        ? String((error as { detail: unknown }).detail)
        : 'illegal sandbox state transition';
    throw new SandboxStateError(detail);
  }
  if (error) throw error;
  if (!data) throw new Error(`empty response from /api/sandboxes/.../${action}`);
  return data;
}

export const wakeSandbox = (id: string) => _transition(id, 'wake');
export const pauseSandbox = (id: string) => _transition(id, 'pause');
export const refreshSandbox = (id: string) => _transition(id, 'refresh');
export const resetSandbox = (id: string) => _transition(id, 'reset');
export const destroySandbox = (id: string) => _transition(id, 'destroy');
