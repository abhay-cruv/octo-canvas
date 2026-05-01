import { api } from './api';

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
