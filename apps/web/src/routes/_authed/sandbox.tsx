import { useQuery } from '@tanstack/react-query';
import { createFileRoute, Link } from '@tanstack/react-router';
import { useEffect, useMemo, useRef, useState } from 'react';

import { ActivityBar, type ActivityView } from '../../components/ide/ActivityBar';
import { ChatsPanel } from '../../components/ide/ChatsPanel';
import { FileEditor } from '../../components/ide/FileEditor';
import { FileTree } from '../../components/ide/FileTree';
import { GitPanel } from '../../components/ide/GitPanel';
import { Layout } from '../../components/ide/Layout';
import { Terminals } from '../../components/ide/Terminals';
import { useFsWatch, useGitStatus, useOpenFiles } from '../../hooks/ide';
import { gitShow, splitRepoPath } from '../../lib/git';
import { connectedReposQueryOptions, sandboxesQueryOptions } from '../../lib/queries';

export const Route = createFileRoute('/_authed/sandbox')({
  component: SandboxIde,
});

function SandboxIde(): JSX.Element {
  const sandboxes = useQuery(sandboxesQueryOptions);
  const sandbox = sandboxes.data?.[0] ?? null;

  if (sandboxes.isLoading) return <CenterMessage>Loading sandbox…</CenterMessage>;
  if (!sandbox) {
    return (
      <CenterMessage>
        No sandbox yet.{' '}
        <Link to="/dashboard" className="text-ide-accent hover:text-ide-textBright underline">
          Go to dashboard
        </Link>{' '}
        to create one.
      </CenterMessage>
    );
  }
  return (
    <SandboxIdeInner
      sandboxId={sandbox.id}
      publicUrl={sandbox.public_url}
      status={sandbox.status}
    />
  );
}

function SandboxIdeInner({
  sandboxId,
  publicUrl,
  status,
}: {
  sandboxId: string;
  publicUrl: string | null;
  status: string;
}): JSX.Element {
  const opened = useOpenFiles(sandboxId);
  const [view, setView] = useState<ActivityView>('files');
  const [diffMode, setDiffMode] = useState<boolean>(false);
  const [diffOriginalByPath, setDiffOriginalByPath] = useState<Map<string, string>>(
    () => new Map(),
  );
  const [diffLoading, setDiffLoading] = useState(false);

  // Connected repos → list of `/work/<owner>/<repo>` for git status.
  const repos = useQuery(connectedReposQueryOptions);
  const repoPaths = useMemo<string[]>(() => {
    const list = repos.data ?? [];
    return list
      .map((r) => `/work/${r.full_name}`)
      .sort();
  }, [repos.data]);

  // Bump key — fs/watch storms would otherwise hammer `git status` on a
  // loop. Three layers of defense:
  //
  // 1. **Path filter** — ignore events under `.git/` (running `git
  //    status` itself updates `.git/index` mtime → fs/watch fires →
  //    triggers another git status → infinite feedback loop). Also
  //    ignore events outside any tracked repo path so changes in
  //    `/work/scratch/...` don't drive git fetches.
  // 2. **Leading-edge fire** — first relevant event fires immediately
  //    so saves show up fast.
  // 3. **15s cooldown** with trailing fire — caps refresh rate; trailing
  //    fire ensures the last event before quiet still gets reflected.
  const [gitBump, setGitBump] = useState(0);
  const lastFireRef = useRef(0);
  const trailingTimerRef = useRef<number | null>(null);
  const COOLDOWN_MS = 15000;
  useFsWatch(sandboxId, (path) => {
    // .git internals — running `git status` itself touches these. Don't
    // let our own observation drive us in circles.
    if (path.includes('/.git/') || path.endsWith('/.git')) return;
    // Only react to paths inside a tracked repo. Anything else can't
    // affect git status of any panel section.
    const inRepo = repoPaths.some(
      (rp) => path === rp || path.startsWith(rp + '/'),
    );
    if (!inRepo) return;

    const now = Date.now();
    const elapsed = now - lastFireRef.current;
    if (elapsed >= COOLDOWN_MS) {
      lastFireRef.current = now;
      setGitBump((n) => n + 1);
      return;
    }
    if (trailingTimerRef.current !== null) {
      window.clearTimeout(trailingTimerRef.current);
    }
    trailingTimerRef.current = window.setTimeout(() => {
      trailingTimerRef.current = null;
      lastFireRef.current = Date.now();
      setGitBump((n) => n + 1);
    }, COOLDOWN_MS - elapsed);
  });
  useEffect(() => {
    return () => {
      if (trailingTimerRef.current !== null) {
        window.clearTimeout(trailingTimerRef.current);
      }
    };
  }, []);

  const {
    statuses,
    refresh: refreshGit,
    isFetching: gitFetching,
  } = useGitStatus(sandboxId, repoPaths, gitBump);

  // Map absolute path → single-char badge for the file tree.
  const gitBadges = useMemo<Map<string, string>>(() => {
    const out = new Map<string, string>();
    for (const r of statuses.values()) {
      if (!r.status) continue;
      for (const f of r.status.files) {
        const abs = `${r.repoPath}/${f.rel_path}`;
        // Same precedence as GitPanel: untracked > added > deleted > rename > modified.
        let char: string;
        if (f.index === '?' || f.worktree === '?') char = 'U';
        else if (f.index === 'A') char = 'A';
        else if (f.index === 'D' || f.worktree === 'D') char = 'D';
        else if (f.index === 'R') char = 'R';
        else char = 'M';
        out.set(abs, char);
      }
    }
    return out;
  }, [statuses]);

  const totalChanged = useMemo(
    () =>
      Array.from(statuses.values()).reduce(
        (n, r) => n + (r.status?.files.length ?? 0),
        0,
      ),
    [statuses],
  );

  // Pre-fetch HEAD content as soon as a file is opened (not when diff is
  // toggled on). Means clicking "Diff" feels instant instead of waiting
  // 300–500ms for the gitShow round-trip every time. Cached per-path; the
  // gitBump-driven invalidation below clears it on save / external change.
  useEffect(() => {
    if (!opened.active) return;
    if (diffOriginalByPath.has(opened.active.path)) return;
    const split = splitRepoPath(opened.active.path);
    if (!split) {
      // File isn't inside a tracked repo — show empty diff (added).
      setDiffOriginalByPath((m) => new Map(m).set(opened.active!.path, ''));
      return;
    }
    let cancelled = false;
    if (diffMode) setDiffLoading(true);
    void (async () => {
      try {
        const r = await gitShow(sandboxId, split.repoPath, split.relPath, 'HEAD');
        if (cancelled) return;
        setDiffOriginalByPath((m) => new Map(m).set(opened.active!.path, r.content));
      } catch {
        if (cancelled) return;
        setDiffOriginalByPath((m) => new Map(m).set(opened.active!.path, ''));
      } finally {
        if (!cancelled) setDiffLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [opened.active, diffOriginalByPath, sandboxId, diffMode]);

  // Re-fetch HEAD content on save / fs/watch — the file's HEAD content
  // doesn't change with edits, so we only invalidate when content might
  // diverge from the cache (e.g. user committed externally).
  useEffect(() => {
    setDiffOriginalByPath(new Map());
  }, [gitBump]);

  const handleOpenDiff = (repoPath: string, relPath: string): void => {
    const abs = `${repoPath}/${relPath}`;
    void opened.open(abs).then(() => {
      setDiffMode(true);
      setView('files');  // swap back to file view so the editor is visible
    });
  };

  return (
    <div className="h-screen flex bg-ide-bg text-ide-text">
      <ActivityBar view={view} setView={setView} gitBadge={totalChanged} />
      <div className="flex-1 min-w-0">
        <Layout
          topBar={
            <div className="flex items-center justify-between px-4 py-2">
              <div className="flex items-center gap-3 min-w-0">
                <Link
                  to="/dashboard"
                  className="text-xs text-ide-textMuted hover:text-ide-textBright transition-colors"
                >
                  ← Dashboard
                </Link>
                <div className="h-4 w-px bg-ide-border" />
                <div className="text-sm font-semibold text-ide-textBright">octo-canvas</div>
                <StatusPill status={status} />
                {publicUrl && (
                  <a
                    href={publicUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs font-mono text-ide-textMuted hover:text-ide-textBright truncate max-w-[28rem] transition-colors"
                    title={publicUrl}
                  >
                    {publicUrl.replace(/^https?:\/\//, '')}
                  </a>
                )}
              </div>
              <div className="text-[10px] text-ide-textDim font-mono">slice 6 · ide</div>
            </div>
          }
          fileTree={
            view === 'files' ? (
              <FileTree
                sandboxId={sandboxId}
                onOpenFile={(p) => {
                  setDiffMode(false);
                  void opened.open(p);
                }}
                activePath={opened.activePath}
                gitBadges={gitBadges}
              />
            ) : (
              <GitPanel
                statuses={statuses}
                loading={repos.isLoading}
                fetching={gitFetching}
                onOpenDiff={handleOpenDiff}
                onRefresh={refreshGit}
              />
            )
          }
          editor={
            <FileEditor
              files={opened.files}
              active={opened.active}
              diffMode={diffMode}
              diffOriginal={
                opened.active ? diffOriginalByPath.get(opened.active.path) ?? null : null
              }
              diffLoading={diffLoading}
              onActivate={opened.setActive}
              onClose={opened.close}
              onChange={opened.setContent}
              onSave={(p) => {
                void (async () => {
                  await opened.save(p);
                  // Saves are an explicit user signal — bypass the
                  // fs/watch throttle so the modified file shows up in
                  // Source Control immediately.
                  refreshGit();
                  // Also force a re-fetch of the HEAD content for diff
                  // mode so the diff editor recomputes against the saved
                  // working tree.
                  setDiffOriginalByPath((m) => {
                    if (!m.has(p)) return m;
                    const next = new Map(m);
                    next.delete(p);
                    return next;
                  });
                })();
              }}
              onReload={(p) => void opened.reload(p)}
              onToggleDiff={() => setDiffMode((m) => !m)}
            />
          }
          terminal={<Terminals sandboxId={sandboxId} />}
          chats={<ChatsPanel />}
        />
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: string }): JSX.Element {
  const styles: Record<string, string> = {
    warm: 'bg-ide-ok/10 text-ide-ok ring-ide-ok/30',
    running: 'bg-ide-ok/10 text-ide-ok ring-ide-ok/30',
    cold: 'bg-ide-textMuted/10 text-ide-textMuted ring-ide-textMuted/30',
    failed: 'bg-ide-danger/10 text-ide-danger ring-ide-danger/30',
    provisioning: 'bg-ide-warn/10 text-ide-warn ring-ide-warn/30',
    resetting: 'bg-ide-warn/10 text-ide-warn ring-ide-warn/30',
    destroyed: 'bg-ide-textDim/10 text-ide-textDim ring-ide-textDim/30',
  };
  const cls = styles[status] ?? 'bg-ide-textMuted/10 text-ide-textMuted ring-ide-textMuted/30';
  return (
    <span
      className={`px-2 py-0.5 text-[10px] uppercase tracking-wider font-medium rounded-full ring-1 ring-inset ${cls}`}
    >
      <span className="inline-block w-1.5 h-1.5 rounded-full bg-current mr-1.5 align-middle" />
      {status}
    </span>
  );
}

function CenterMessage({ children }: { children: React.ReactNode }): JSX.Element {
  return (
    <div className="h-screen flex items-center justify-center text-sm text-ide-text bg-ide-bg">
      <div className="px-6 py-4 bg-ide-panel rounded-lg border border-ide-border">{children}</div>
    </div>
  );
}
