/**
 * Slice 6 FS REST client. Types track `routes/sandbox_fs.py`.
 *
 * Bypasses `openapi-fetch` because the generated OpenAPI types lag the
 * server until the codegen step runs. The shapes are small + stable
 * enough to hand-type for now.
 */

const baseUrl = import.meta.env.VITE_ORCHESTRATOR_BASE_URL as string;
if (!baseUrl) throw new Error('VITE_ORCHESTRATOR_BASE_URL not set');

export type FsEntry = { name: string; type: 'file' | 'dir'; size: number };

export type FsListResponse = {
  type: 'list';
  path: string;
  entries: FsEntry[];
};

export type FsFileResponse = {
  type: 'file';
  path: string;
  content: string;
  sha: string;
  size: number;
};

export type FsWriteResponse = { path: string; sha: string; size: number };
export type FsRenameResponse = { path: string; new_path: string };

export class FsConflictError extends Error {
  constructor(
    public readonly currentSha: string,
    public readonly path: string,
  ) {
    super(`file changed underneath us at ${path}`);
    this.name = 'FsConflictError';
  }
}

function url(sandboxId: string, params: Record<string, string>) {
  const qs = new URLSearchParams(params).toString();
  return `${baseUrl}/api/sandboxes/${sandboxId}/fs?${qs}`;
}

export async function fsList(
  sandboxId: string,
  path: string,
): Promise<FsListResponse> {
  const r = await fetch(url(sandboxId, { path, list: 'true' }), {
    credentials: 'include',
  });
  if (!r.ok) throw new Error(`fsList ${r.status}`);
  return (await r.json()) as FsListResponse;
}

export async function fsRead(
  sandboxId: string,
  path: string,
): Promise<FsFileResponse> {
  const r = await fetch(url(sandboxId, { path }), { credentials: 'include' });
  if (r.status === 415) {
    throw new Error(
      'Binary file (not viewable in slice-6 editor; open via terminal)',
    );
  }
  if (!r.ok) throw new Error(`fsRead ${r.status}`);
  return (await r.json()) as FsFileResponse;
}

export async function fsWrite(
  sandboxId: string,
  path: string,
  content: string,
  ifMatchSha: string | null,
): Promise<FsWriteResponse> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (ifMatchSha) headers['If-Match'] = ifMatchSha;
  const r = await fetch(url(sandboxId, { path }), {
    method: 'PUT',
    credentials: 'include',
    headers,
    body: JSON.stringify({ content }),
  });
  if (r.status === 412) {
    const body = (await r.json()) as { detail: { current_sha: string } };
    throw new FsConflictError(body.detail.current_sha, path);
  }
  if (!r.ok) throw new Error(`fsWrite ${r.status}`);
  return (await r.json()) as FsWriteResponse;
}

export async function fsDelete(
  sandboxId: string,
  path: string,
  recursive = false,
): Promise<void> {
  const r = await fetch(
    url(sandboxId, { path, recursive: recursive ? 'true' : 'false' }),
    { method: 'DELETE', credentials: 'include' },
  );
  if (!r.ok && r.status !== 204) throw new Error(`fsDelete ${r.status}`);
}

export async function fsRename(
  sandboxId: string,
  src: string,
  newPath: string,
): Promise<FsRenameResponse> {
  const r = await fetch(url(sandboxId, { path: src, op: 'rename' }), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_path: newPath }),
  });
  if (!r.ok) throw new Error(`fsRename ${r.status}`);
  return (await r.json()) as FsRenameResponse;
}
