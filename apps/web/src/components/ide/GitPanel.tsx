/**
 * Source-control panel — lists changed files per repo grouped by
 * Staged / Modified / Untracked. Click a file → opens it in the editor
 * with the diff mode auto-enabled. Uses `useGitStatus` (slice 6).
 */

import type { RepoGitStatus } from '../../hooks/ide';
import type { GitStatusFile } from '../../lib/git';

type Props = {
  statuses: Map<string, RepoGitStatus>;
  loading: boolean;
  fetching: boolean;
  onOpenDiff: (repoPath: string, relPath: string) => void;
  onRefresh: () => void;
};

type Group = 'staged' | 'modified' | 'untracked';

const GROUP_LABEL: Record<Group, string> = {
  staged: 'Staged Changes',
  modified: 'Changes',
  untracked: 'Untracked',
};

function classify(file: GitStatusFile): Group {
  if (file.index === '?' || file.worktree === '?') return 'untracked';
  if (file.index !== ' ' && file.index !== '?') return 'staged';
  return 'modified';
}

export function GitPanel({
  statuses,
  loading,
  fetching,
  onOpenDiff,
  onRefresh,
}: Props): JSX.Element {
  const repos = Array.from(statuses.values());
  const totalChanged = repos.reduce(
    (n, r) => n + (r.status?.files.length ?? 0),
    0,
  );

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-ide-borderSoft">
        <span className="text-[11px] uppercase tracking-wider text-ide-textMuted font-medium">
          Source Control
        </span>
        <button
          type="button"
          onClick={onRefresh}
          disabled={fetching}
          className="flex items-center gap-1.5 px-2 py-1 rounded text-xs text-ide-text bg-ide-tab hover:bg-ide-hover hover:text-ide-textBright disabled:opacity-50 transition-colors border border-ide-border"
          title="Re-run git status"
        >
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={fetching ? 'animate-spin' : ''}
          >
            <polyline points="23 4 23 10 17 10" />
            <polyline points="1 20 1 14 7 14" />
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
          </svg>
          <span>{fetching ? 'Refreshing' : 'Refresh'}</span>
        </button>
      </div>
      {loading && repos.length === 0 ? (
        <div className="p-3 text-xs text-ide-textDim">Loading repos…</div>
      ) : repos.length === 0 ? (
        <Empty />
      ) : (
        <div className="flex-1 overflow-auto">
          {repos.map((r) => (
            <RepoSection key={r.repoPath} status={r} onOpenDiff={onOpenDiff} />
          ))}
          {totalChanged === 0 && repos.every((r) => r.status !== null) && (
            <div className="px-3 py-2 text-xs text-ide-textDim italic">
              All working trees clean
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RepoSection({
  status,
  onOpenDiff,
}: {
  status: RepoGitStatus;
  onOpenDiff: (repoPath: string, relPath: string) => void;
}): JSX.Element {
  // Skeleton state — fetch hasn't returned yet.
  if (status.status === null && status.error === null) {
    return (
      <div className="px-3 py-2 border-b border-ide-borderSoft">
        <div className="text-[11px] uppercase tracking-wider text-ide-textMuted">
          {status.fullName}
        </div>
        <div className="mt-1 text-xs text-ide-textDim italic">loading…</div>
      </div>
    );
  }
  // Network/orchestrator-level failure (no response). Different from a
  // git command that exited non-zero (which has `git_error` populated
  // inside `status.status` instead).
  if (status.error && status.status === null) {
    return (
      <div className="px-3 py-2 border-b border-ide-borderSoft">
        <div className="text-[11px] uppercase tracking-wider text-ide-textMuted mb-1">
          {status.fullName}
        </div>
        <div className="text-xs text-ide-danger" title={status.error}>
          fetch failed: {status.error}
        </div>
      </div>
    );
  }
  if (!status.status || status.status.files.length === 0) {
    return (
      <div className="px-3 py-2 border-b border-ide-borderSoft">
        <div className="flex items-center justify-between text-[11px] uppercase tracking-wider text-ide-textMuted">
          <span>{status.fullName}</span>
          <span className="normal-case tracking-normal text-ide-textDim">
            {status.status?.branch ?? ''}
          </span>
        </div>
        {status.status?.git_error ? (
          <div
            className="mt-1 text-xs text-ide-danger break-words"
            title={status.status.git_error}
          >
            git: {status.status.git_error}
          </div>
        ) : (
          <div className="mt-1 text-xs text-ide-textDim italic">no changes</div>
        )}
      </div>
    );
  }
  const grouped: Record<Group, GitStatusFile[]> = {
    staged: [],
    modified: [],
    untracked: [],
  };
  for (const f of status.status.files) grouped[classify(f)].push(f);

  return (
    <div className="border-b border-ide-borderSoft pb-2">
      <div className="flex items-center justify-between px-3 py-2 text-[11px] uppercase tracking-wider text-ide-textMuted">
        <span>{status.fullName}</span>
        <span className="normal-case tracking-normal text-ide-textDim font-mono">
          {status.status.branch ?? '(detached)'}
          {status.status.ahead > 0 && (
            <span className="ml-1 text-ide-warn">↑{status.status.ahead}</span>
          )}
          {status.status.behind > 0 && (
            <span className="ml-1 text-ide-warn">↓{status.status.behind}</span>
          )}
        </span>
      </div>
      {(['staged', 'modified', 'untracked'] as const).map((g) =>
        grouped[g].length > 0 ? (
          <div key={g} className="mt-1">
            <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-ide-textDim">
              {GROUP_LABEL[g]} <span className="ml-1">({grouped[g].length})</span>
            </div>
            {grouped[g].map((f) => (
              <FileRow
                key={f.rel_path}
                file={f}
                repoPath={status.repoPath}
                onOpenDiff={onOpenDiff}
              />
            ))}
          </div>
        ) : null,
      )}
    </div>
  );
}

function FileRow({
  file,
  repoPath,
  onOpenDiff,
}: {
  file: GitStatusFile;
  repoPath: string;
  onOpenDiff: (repoPath: string, relPath: string) => void;
}): JSX.Element {
  const name = file.rel_path.slice(file.rel_path.lastIndexOf('/') + 1);
  const dir =
    file.rel_path.lastIndexOf('/') === -1
      ? ''
      : file.rel_path.slice(0, file.rel_path.lastIndexOf('/'));
  const badgeChar = badgeCharFor(file);
  return (
    <button
      type="button"
      onClick={() => onOpenDiff(repoPath, file.rel_path)}
      title={file.rel_path}
      className="flex items-center justify-between w-full px-3 py-0.5 text-left hover:bg-ide-hover text-ide-text"
    >
      <span className="flex-1 truncate font-mono text-[13px]">
        {name}
        {dir && <span className="ml-2 text-ide-textDim">{dir}</span>}
      </span>
      <span
        className={
          'ml-2 w-4 text-center font-mono text-[12px] font-bold ' +
          colorForBadge(badgeChar)
        }
      >
        {badgeChar}
      </span>
    </button>
  );
}

function badgeCharFor(f: GitStatusFile): string {
  // VS Code-ish — staged dominates over worktree if both present.
  if (f.index === '?' || f.worktree === '?') return 'U';
  if (f.index === 'A') return 'A';
  if (f.index === 'D' || f.worktree === 'D') return 'D';
  if (f.index === 'R') return 'R';
  return 'M';
}

export function colorForBadge(char: string): string {
  switch (char) {
    case 'M':
      return 'text-ide-warn';
    case 'A':
      return 'text-ide-ok';
    case 'D':
      return 'text-ide-danger';
    case 'U':
      return 'text-ide-ok';
    case 'R':
      return 'text-ide-accent';
    default:
      return 'text-ide-textMuted';
  }
}

function Empty({ clean }: { clean?: boolean } = {}): JSX.Element {
  return (
    <div className="flex-1 flex items-center justify-center p-6 text-center">
      <div>
        <div className="text-ide-textMuted mb-2">Source control</div>
        <div className="text-xs text-ide-textDim">
          {clean ? 'Working tree clean' : 'No connected repos'}
        </div>
      </div>
    </div>
  );
}
