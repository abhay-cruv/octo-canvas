import { keepPreviousData, useQueries, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  fsDelete,
  fsList,
  fsRead,
  fsRename,
  fsWrite,
  type FsEntry,
  type FsFileResponse,
  FsConflictError,
} from '../lib/fs';
import { openFsWatch } from '../lib/fsWatch';
import { gitStatus, SpriteBusyError, type GitStatusResponse } from '../lib/git';
import { openPty, type PtyHandle } from '../lib/pty';

// ── usePanelLayout ─────────────────────────────────────────────────────

const LAYOUT_KEY = 'octo:layout';
const DEFAULT_LAYOUT = { left: 18, right: 22, bottom: 30 } as const;

export type LayoutSizes = { left: number; right: number; bottom: number };

export function usePanelLayout(): {
  sizes: LayoutSizes;
  setLeft: (v: number) => void;
  setRight: (v: number) => void;
  setBottom: (v: number) => void;
} {
  const [sizes, setSizes] = useState<LayoutSizes>(() => {
    try {
      const raw = localStorage.getItem(LAYOUT_KEY);
      if (raw) return { ...DEFAULT_LAYOUT, ...(JSON.parse(raw) as Partial<LayoutSizes>) };
    } catch {
      // ignore
    }
    return DEFAULT_LAYOUT;
  });
  useEffect(() => {
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(sizes));
    } catch {
      // ignore
    }
  }, [sizes]);
  return {
    sizes,
    setLeft: (v) => setSizes((s) => ({ ...s, left: v })),
    setRight: (v) => setSizes((s) => ({ ...s, right: v })),
    setBottom: (v) => setSizes((s) => ({ ...s, bottom: v })),
  };
}

// ── useGitStatus ───────────────────────────────────────────────────────

export type RepoGitStatus = {
  repoPath: string;
  /** "owner/name" — convenient label for the GitPanel section header. */
  fullName: string;
  status: GitStatusResponse | null;
  error: string | null;
};

/**
 * Per-repo `git status` powered by TanStack Query — one query per repo,
 * combined into a Map. TanStack handles caching, deduplication, retries,
 * and StrictMode-safe cancellation, so we don't have to. `bumpKey` invalidates
 * via `queryClient.invalidateQueries` instead of remounting an effect.
 *
 * `placeholderData: keepPrevious` means a refetch never blanks the panel —
 * the previous status stays visible while the new fetch is in flight.
 */
export function useGitStatus(
  sandboxId: string,
  repoPaths: readonly string[],
  bumpKey: number,
): {
  statuses: Map<string, RepoGitStatus>;
  refresh: () => void;
  isFetching: boolean;
} {
  const queryClient = useQueryClient();
  const repoKey = useMemo(() => repoPaths.join('|'), [repoPaths]);

  // Invalidate every git-status query whenever the bump changes.
  useEffect(() => {
    if (!sandboxId) return;
    void queryClient.invalidateQueries({
      queryKey: ['git', 'status', sandboxId],
    });
  }, [sandboxId, bumpKey, queryClient]);

  const queries = useQueries({
    queries: repoPaths.map((rp) => ({
      queryKey: ['git', 'status', sandboxId, rp],
      queryFn: () => gitStatus(sandboxId, rp),
      // `keepPreviousData` makes TanStack hand back the last successful
      // result while a refetch is in flight, so the panel never reverts
      // to "loading…" after the first success.
      placeholderData: keepPreviousData,
      // Refetch is driven by `bumpKey` invalidation; don't auto-refetch
      // on focus/reconnect (they'd compete with our throttled bumps).
      refetchOnWindowFocus: false,
      refetchOnReconnect: false,
      staleTime: 1000,
      enabled: Boolean(sandboxId) && rp.length > 0,
      // Don't retry-storm on `SpriteBusyError` (orchestrator returned
      // 503 because the sprite is mid-pyenv-compile or similar). The
      // next bumpKey invalidation will refetch when things settle.
      // Other errors (real 5xx, network) get the default 3 retries.
      retry: (failureCount: number, err: unknown) => {
        if (err instanceof SpriteBusyError) return false;
        return failureCount < 3;
      },
    })),
  });

  const refresh = useCallback(() => {
    if (!sandboxId) return;
    void queryClient.invalidateQueries({
      queryKey: ['git', 'status', sandboxId],
    });
  }, [sandboxId, queryClient]);

  // Build the result Map. Use `repoKey` in the dep so a repos change
  // updates the map shape; query results update via TanStack's own
  // re-render cycle.
  const statuses = useMemo<Map<string, RepoGitStatus>>(() => {
    const out = new Map<string, RepoGitStatus>();
    repoPaths.forEach((rp, i) => {
      const fullName = rp.startsWith('/work/') ? rp.slice('/work/'.length) : rp;
      const q = queries[i];
      out.set(rp, {
        repoPath: rp,
        fullName,
        status: q?.data ?? null,
        error: q?.error
          ? q.error instanceof Error
            ? q.error.message
            : String(q.error)
          : null,
      });
    });
    return out;
    // queries is a fresh array every render; rely on map-by-data for
    // identity. repoKey + bumpKey suffice as change signals.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoKey, bumpKey, queries.map((q) => q.dataUpdatedAt).join('|')]);

  const isFetching = queries.some((q) => q.isFetching);

  return { statuses, refresh, isFetching };
}

// ── useFsWatch ─────────────────────────────────────────────────────────

export function useFsWatch(
  sandboxId: string,
  onPathChanged: (path: string, kind: string) => void,
): void {
  const cb = useRef(onPathChanged);
  cb.current = onPathChanged;
  useEffect(() => {
    if (!sandboxId) return;
    return openFsWatch(sandboxId, (ev) => cb.current(ev.path, ev.kind));
  }, [sandboxId]);
}

// ── useFileTree (lazy directory expansion) ─────────────────────────────

export type TreeNode = {
  path: string;
  name: string;
  kind: 'file' | 'dir';
  size: number;
  children: TreeNode[] | null; // null = unloaded
};

export function useFileTree(sandboxId: string): {
  root: TreeNode | null;
  expanded: Set<string>;
  toggle: (path: string) => Promise<void>;
  refreshPath: (path: string) => Promise<void>;
  rename: (path: string, newPath: string) => Promise<string | null>;
  remove: (path: string, isDir: boolean) => Promise<string | null>;
  error: string | null;
} {
  const [root, setRoot] = useState<TreeNode | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['/work']));
  const [error, setError] = useState<string | null>(null);

  const loadChildren = useCallback(
    async (path: string): Promise<TreeNode[]> => {
      const list = await fsList(sandboxId, path);
      const nodes = list.entries.map(
        (e: FsEntry): TreeNode => ({
          path: path === '/' ? `/${e.name}` : `${path}/${e.name}`,
          name: e.name,
          kind: e.type,
          size: e.size,
          children: null,
        }),
      );
      return sortTreeNodes(nodes);
    },
    [sandboxId],
  );

  const refreshPath = useCallback(
    async (path: string) => {
      try {
        const children = await loadChildren(path);
        setRoot((prev) => {
          if (prev === null) return prev;
          return updateNodeAt(prev, path, (n) => ({ ...n, children }));
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [loadChildren],
  );

  // Initial load.
  useEffect(() => {
    if (!sandboxId) return;
    let cancelled = false;
    void (async () => {
      try {
        const children = await loadChildren('/work');
        if (cancelled) return;
        setRoot({
          path: '/work',
          name: 'work',
          kind: 'dir',
          size: 0,
          children,
        });
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sandboxId, loadChildren]);

  const toggle = useCallback(
    async (path: string) => {
      const isExpanded = expanded.has(path);
      const next = new Set(expanded);
      if (isExpanded) {
        next.delete(path);
        setExpanded(next);
        return;
      }
      next.add(path);
      setExpanded(next);
      const node = root && findNodeAt(root, path);
      if (node && node.children === null) {
        await refreshPath(path);
      }
    },
    [expanded, root, refreshPath],
  );

  const rename = useCallback(
    async (path: string, newPath: string): Promise<string | null> => {
      try {
        await fsRename(sandboxId, path, newPath);
        const parent = parentOf(path);
        const newParent = parentOf(newPath);
        await refreshPath(parent);
        if (newParent !== parent) await refreshPath(newParent);
        return null;
      } catch (e) {
        return e instanceof Error ? e.message : String(e);
      }
    },
    [sandboxId, refreshPath],
  );

  const remove = useCallback(
    async (path: string, isDir: boolean): Promise<string | null> => {
      try {
        await fsDelete(sandboxId, path, isDir);
        await refreshPath(parentOf(path));
        return null;
      } catch (e) {
        return e instanceof Error ? e.message : String(e);
      }
    },
    [sandboxId, refreshPath],
  );

  return { root, expanded, toggle, refreshPath, rename, remove, error };
}

/**
 * VS Code-style sort: directories first, then files. Within each group,
 * case-insensitive natural sort (so `file2.ts` comes before `file10.ts`).
 */
function sortTreeNodes(nodes: TreeNode[]): TreeNode[] {
  const collator = new Intl.Collator(undefined, {
    numeric: true,
    sensitivity: 'base',
  });
  return [...nodes].sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === 'dir' ? -1 : 1;
    return collator.compare(a.name, b.name);
  });
}

function parentOf(path: string): string {
  if (!path.includes('/') || path === '/') return '/work';
  const idx = path.lastIndexOf('/');
  return idx === 0 ? '/' : path.slice(0, idx);
}

function findNodeAt(root: TreeNode, path: string): TreeNode | null {
  if (root.path === path) return root;
  if (root.children) {
    for (const c of root.children) {
      const found = findNodeAt(c, path);
      if (found) return found;
    }
  }
  return null;
}

function updateNodeAt(
  root: TreeNode,
  path: string,
  fn: (n: TreeNode) => TreeNode,
): TreeNode {
  if (root.path === path) return fn(root);
  if (root.children === null) return root;
  return {
    ...root,
    children: root.children.map((c) => updateNodeAt(c, path, fn)),
  };
}

// ── useOpenFiles (multi-tab editor) ────────────────────────────────────

export type OpenFileState = {
  path: string;
  content: string;
  sha: string;
  dirty: boolean;
  error: string | null;
  loading: boolean;
};

export function useOpenFiles(sandboxId: string): {
  files: OpenFileState[];
  active: OpenFileState | null;
  activePath: string | null;
  open: (path: string) => Promise<void>;
  close: (path: string) => void;
  setActive: (path: string) => void;
  setContent: (path: string, s: string) => void;
  save: (path: string) => Promise<void>;
  reload: (path: string) => Promise<void>;
} {
  const [filesByPath, setFilesByPath] = useState<Map<string, OpenFileState>>(() => new Map());
  const [order, setOrder] = useState<string[]>([]);
  const [activePath, setActivePath] = useState<string | null>(null);

  const setOne = useCallback((path: string, fn: (f: OpenFileState) => OpenFileState) => {
    setFilesByPath((prev) => {
      const cur = prev.get(path);
      if (!cur) return prev;
      const next = new Map(prev);
      next.set(path, fn(cur));
      return next;
    });
  }, []);

  const open = useCallback(
    async (path: string) => {
      // If already open, just activate.
      if (filesByPath.has(path)) {
        setActivePath(path);
        return;
      }
      const placeholder: OpenFileState = {
        path,
        content: '',
        sha: '',
        dirty: false,
        error: null,
        loading: true,
      };
      setFilesByPath((prev) => {
        const next = new Map(prev);
        next.set(path, placeholder);
        return next;
      });
      setOrder((o) => (o.includes(path) ? o : [...o, path]));
      setActivePath(path);
      try {
        const r: FsFileResponse = await fsRead(sandboxId, path);
        setOne(path, () => ({
          path,
          content: r.content,
          sha: r.sha,
          dirty: false,
          error: null,
          loading: false,
        }));
      } catch (e) {
        setOne(path, (cur) => ({
          ...cur,
          loading: false,
          error: e instanceof Error ? e.message : String(e),
        }));
      }
    },
    [sandboxId, filesByPath, setOne],
  );

  const close = useCallback(
    (path: string) => {
      setFilesByPath((prev) => {
        if (!prev.has(path)) return prev;
        const next = new Map(prev);
        next.delete(path);
        return next;
      });
      setOrder((o) => o.filter((p) => p !== path));
      setActivePath((cur) => {
        if (cur !== path) return cur;
        const remaining = order.filter((p) => p !== path);
        return remaining[remaining.length - 1] ?? null;
      });
    },
    [order],
  );

  const setActive = useCallback((path: string) => {
    setActivePath(path);
  }, []);

  const setContent = useCallback(
    (path: string, s: string) => {
      setOne(path, (f) => ({
        ...f,
        content: s,
        dirty: f.sha ? f.content !== s : true,
      }));
    },
    [setOne],
  );

  const save = useCallback(
    async (path: string) => {
      const file = filesByPath.get(path);
      if (!file || !file.dirty) return;
      try {
        const r = await fsWrite(sandboxId, file.path, file.content, file.sha || null);
        setOne(path, (f) => ({ ...f, sha: r.sha, dirty: false, error: null }));
      } catch (e) {
        if (e instanceof FsConflictError) {
          setOne(path, (f) => ({
            ...f,
            error: `File changed on disk. Reload to see latest (${e.currentSha.slice(0, 8)}).`,
          }));
          return;
        }
        setOne(path, (f) => ({
          ...f,
          error: e instanceof Error ? e.message : String(e),
        }));
      }
    },
    [filesByPath, sandboxId, setOne],
  );

  const reload = useCallback(
    async (path: string) => {
      try {
        const r = await fsRead(sandboxId, path);
        setOne(path, () => ({
          path,
          content: r.content,
          sha: r.sha,
          dirty: false,
          error: null,
          loading: false,
        }));
      } catch (e) {
        setOne(path, (f) => ({ ...f, error: e instanceof Error ? e.message : String(e) }));
      }
    },
    [sandboxId, setOne],
  );

  const files = order.map((p) => filesByPath.get(p)).filter((f): f is OpenFileState => !!f);
  const active = activePath ? (filesByPath.get(activePath) ?? null) : null;

  return { files, active, activePath, open, close, setActive, setContent, save, reload };
}

// ── useTerminals (multi-tab manager) ───────────────────────────────────

const TERMS_KEY = 'octo:terminals';

export type TerminalSlot = { id: string; label: string };

export function useTerminals(): {
  terminals: TerminalSlot[];
  activeId: string | null;
  add: () => void;
  close: (id: string) => void;
  resetAll: () => void;
  setActive: (id: string) => void;
} {
  const [terminals, setTerminals] = useState<TerminalSlot[]>(() => {
    try {
      const raw = sessionStorage.getItem(TERMS_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as TerminalSlot[];
        if (Array.isArray(parsed) && parsed.length > 0) return parsed;
      }
    } catch {
      // ignore
    }
    const id = 't-' + Math.random().toString(36).slice(2, 10);
    return [{ id, label: 'bash' }];
  });
  const [activeId, setActiveId] = useState<string | null>(() => null);

  useEffect(() => {
    if (activeId === null && terminals.length > 0) {
      setActiveId(terminals[0]?.id ?? null);
    }
  }, [terminals, activeId]);

  useEffect(() => {
    try {
      sessionStorage.setItem(TERMS_KEY, JSON.stringify(terminals));
    } catch {
      // ignore
    }
  }, [terminals]);

  const add = useCallback(() => {
    const id = 't-' + Math.random().toString(36).slice(2, 10);
    setTerminals((prev) => [...prev, { id, label: `bash ${prev.length + 1}` }]);
    setActiveId(id);
  }, []);

  const close = useCallback((id: string) => {
    setTerminals((prev) => {
      const next = prev.filter((t) => t.id !== id);
      // Always keep at least one slot — re-add a fresh one if we'd empty.
      if (next.length === 0) {
        const fresh = 't-' + Math.random().toString(36).slice(2, 10);
        return [{ id: fresh, label: 'bash' }];
      }
      return next;
    });
    setActiveId((cur) => (cur === id ? null : cur));
  }, []);

  const resetAll = useCallback(() => {
    // Wipe sessionStorage + replace every slot with fresh ids. The
    // outgoing terminal_ids are never reused, so the orchestrator
    // broker's Redis cache for those ids quietly TTLs out. The new
    // ids force fresh Sprites Exec sessions with the current
    // `pty_dial_info` cmd shape (e.g. starts in /work).
    try {
      sessionStorage.removeItem(TERMS_KEY);
    } catch {
      // ignore
    }
    const id = 't-' + Math.random().toString(36).slice(2, 10);
    setTerminals([{ id, label: 'bash' }]);
    setActiveId(id);
  }, []);

  return { terminals, activeId, add, close, resetAll, setActive: setActiveId };
}

// ── useTerminal (xterm + WS pump for one slot) ─────────────────────────

export type TerminalAttachment = {
  ref: (el: HTMLDivElement | null) => void;
  focus: () => void;
  dispose: () => void;
};

export function useTerminal(
  sandboxId: string,
  terminalId: string,
): TerminalAttachment {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const ptyRef = useRef<PtyHandle | null>(null);
  const xtermRef = useRef<{
    term: import('@xterm/xterm').Terminal;
    fit: import('@xterm/addon-fit').FitAddon;
  } | null>(null);
  const mountedAt = useMemo(() => ({ id: terminalId }), [terminalId]);

  const dispose = useCallback(() => {
    ptyRef.current?.close();
    ptyRef.current = null;
    xtermRef.current?.term.dispose();
    xtermRef.current = null;
  }, []);

  const ref = useCallback(
    (el: HTMLDivElement | null) => {
      containerRef.current = el;
      if (!el || xtermRef.current) return;
      void (async () => {
        const { Terminal } = await import('@xterm/xterm');
        await import('@xterm/xterm/css/xterm.css');
        const { FitAddon } = await import('@xterm/addon-fit');
        const term = new Terminal({
          fontFamily:
            'ui-monospace, "SF Mono", Menlo, Monaco, "Cascadia Code", Consolas, monospace',
          fontSize: 13,
          lineHeight: 1.25,
          // VS Code Dark+ palette.
          theme: {
            background: '#1e1e1e',
            foreground: '#cccccc',
            cursor: '#aeafad',
            cursorAccent: '#1e1e1e',
            selectionBackground: '#264f78',
            black: '#000000',
            red: '#cd3131',
            green: '#0dbc79',
            yellow: '#e5e510',
            blue: '#2472c8',
            magenta: '#bc3fbc',
            cyan: '#11a8cd',
            white: '#e5e5e5',
            brightBlack: '#666666',
            brightRed: '#f14c4c',
            brightGreen: '#23d18b',
            brightYellow: '#f5f543',
            brightBlue: '#3b8eea',
            brightMagenta: '#d670d6',
            brightCyan: '#29b8db',
            brightWhite: '#e5e5e5',
          },
          cursorBlink: true,
          allowTransparency: false,
        });
        const fit = new FitAddon();
        term.loadAddon(fit);
        term.open(el);
        fit.fit();
        xtermRef.current = { term, fit };

        const enc = new TextEncoder();
        const dec = new TextDecoder();

        const pty = openPty(sandboxId, mountedAt.id, {
          onBytes: (b) => term.write(dec.decode(b)),
          onSessionInfo: (info) => {
            if (info.reattached) {
              term.write('\r\n\x1b[36m[reconnected]\x1b[0m\r\n');
            }
          },
          onExit: (e) => {
            term.write(`\r\n\x1b[33m[exited ${e.exit_code}]\x1b[0m\r\n`);
          },
          onClose: (_code, permanent) => {
            if (permanent) {
              term.write('\r\n\x1b[31m[session ended]\x1b[0m\r\n');
            } else {
              term.write('\r\n\x1b[33m[reconnecting…]\x1b[0m\r\n');
            }
          },
          onReconnect: () => {
            // Re-emit dimensions so the upstream PTY matches xterm size.
            const dims = term.cols && term.rows ? { cols: term.cols, rows: term.rows } : null;
            if (dims) ptyRef.current?.resize(dims.cols, dims.rows);
          },
        });
        ptyRef.current = pty;

        term.onData((data: string) => pty.send(enc.encode(data)));
        term.onResize(({ cols, rows }: { cols: number; rows: number }) => pty.resize(cols, rows));

        const ro = new ResizeObserver(() => fit.fit());
        ro.observe(el);
      })();
    },
    [sandboxId, mountedAt.id],
  );

  useEffect(() => {
    return () => dispose();
  }, [dispose]);

  return {
    ref,
    focus: () => xtermRef.current?.term.focus(),
    dispose,
  };
}
