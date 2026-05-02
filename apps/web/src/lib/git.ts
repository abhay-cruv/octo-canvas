/**
 * Slice 6 git read-surface client. Backed by `routes/sandbox_git.py`,
 * which shells out via `provider.exec_oneshot` — no new Protocol method.
 */

const baseUrl = import.meta.env.VITE_ORCHESTRATOR_BASE_URL as string;
if (!baseUrl) throw new Error('VITE_ORCHESTRATOR_BASE_URL not set');

export type GitStatusFile = {
  rel_path: string;
  index: string;
  worktree: string;
  rel_path_orig: string | null;
};

export type GitStatusResponse = {
  repo_path: string;
  branch: string | null;
  detached: boolean;
  ahead: number;
  behind: number;
  files: GitStatusFile[];
  /** Set when git itself exited non-zero (e.g. "not a git repository", a
   * `fatal:` blip mid-clone). The route still returns 200 with empty
   * `files` so one bad repo doesn't poison the panel. */
  git_error?: string | null;
};

export type GitShowResponse = {
  repo_path: string;
  rel_path: string;
  ref: string;
  exists: boolean;
  content: string;
  truncated: boolean;
};

export async function gitStatus(
  sandboxId: string,
  repoPath: string,
): Promise<GitStatusResponse> {
  const qs = new URLSearchParams({ repo_path: repoPath }).toString();
  const r = await fetch(`${baseUrl}/api/sandboxes/${sandboxId}/git/status?${qs}`, {
    credentials: 'include',
  });
  if (!r.ok) throw new Error(`gitStatus ${r.status}`);
  return (await r.json()) as GitStatusResponse;
}

export async function gitShow(
  sandboxId: string,
  repoPath: string,
  relPath: string,
  ref = 'HEAD',
): Promise<GitShowResponse> {
  const qs = new URLSearchParams({
    repo_path: repoPath,
    rel_path: relPath,
    ref,
  }).toString();
  const r = await fetch(`${baseUrl}/api/sandboxes/${sandboxId}/git/show?${qs}`, {
    credentials: 'include',
  });
  if (!r.ok) throw new Error(`gitShow ${r.status}`);
  return (await r.json()) as GitShowResponse;
}

/**
 * Split an absolute working-tree path (`/work/<owner>/<repo>/<rel>`) into
 * `(repo_path, rel_path)`. Returns null when the path doesn't live inside
 * a repo (e.g. user scratch under `/work/scratch/...`).
 */
export function splitRepoPath(
  absolute: string,
): { repoPath: string; relPath: string } | null {
  if (!absolute.startsWith('/work/')) return null;
  const parts = absolute.slice('/work/'.length).split('/');
  if (parts.length < 3 || !parts[0] || !parts[1]) return null;
  const repoPath = `/work/${parts[0]}/${parts[1]}`;
  const relPath = parts.slice(2).join('/');
  return { repoPath, relPath };
}
