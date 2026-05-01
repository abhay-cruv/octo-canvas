import type { components } from '@octo-canvas/api-types';
import { api } from './api';

export type IntrospectionOverrides =
  components['schemas']['IntrospectionOverrides'];

export class GithubReauthRequiredError extends Error {
  constructor() {
    super('github_reauth_required');
    this.name = 'GithubReauthRequiredError';
  }
}

export async function connectRepo(input: {
  github_repo_id: number;
  full_name: string;
}): Promise<void> {
  const { error, response } = await api.POST('/api/repos/connect', {
    body: input,
  });
  if (response.status === 403) throw new GithubReauthRequiredError();
  if (error) throw error;
}

export async function disconnectRepo(repoId: string): Promise<void> {
  const { error } = await api.DELETE('/api/repos/{repo_id}', {
    params: { path: { repo_id: repoId } },
  });
  if (error) throw error;
}

export async function reintrospectRepo(repoId: string): Promise<void> {
  const { error, response } = await api.POST(
    '/api/repos/{repo_id}/reintrospect',
    { params: { path: { repo_id: repoId } } },
  );
  if (response.status === 403) throw new GithubReauthRequiredError();
  if (error) throw error;
}

export async function updateIntrospectionOverrides(input: {
  repoId: string;
  overrides: IntrospectionOverrides;
}): Promise<void> {
  const { error } = await api.PATCH('/api/repos/{repo_id}/introspection', {
    params: { path: { repo_id: input.repoId } },
    body: input.overrides,
  });
  if (error) throw error;
}
