import { api } from './api';

export function startGithubLogin(): void {
  window.location.href = `${import.meta.env.VITE_ORCHESTRATOR_BASE_URL}/api/auth/github/login`;
}

export function manageGithubAccessUrl(): string {
  return `${import.meta.env.VITE_ORCHESTRATOR_BASE_URL}/api/auth/github/manage`;
}

export async function logout(): Promise<void> {
  await api.POST('/api/auth/logout');
}
