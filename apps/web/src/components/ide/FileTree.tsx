import { useEffect, useState } from 'react';

import { useFileTree, useFsWatch, type TreeNode } from '../../hooks/ide';

type Props = {
  sandboxId: string;
  onOpenFile: (path: string) => void;
  activePath: string | null;
  /** Map from ABSOLUTE path → single-char git badge ('M'/'A'/'U'/'D'/'R').
   * Pass an empty map when git status isn't available for a file. */
  gitBadges?: Map<string, string>;
};

type ContextMenu = {
  x: number;
  y: number;
  path: string;
  name: string;
  isDir: boolean;
};

export function FileTree({
  sandboxId,
  onOpenFile,
  activePath,
  gitBadges,
}: Props): JSX.Element {
  const tree = useFileTree(sandboxId);
  const [menu, setMenu] = useState<ContextMenu | null>(null);
  const [renaming, setRenaming] = useState<{ path: string; value: string } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useFsWatch(sandboxId, (path) => {
    // Ignore `.git/` internals — running git commands updates files in
    // there which would otherwise drive constant tree refreshes. Users
    // never browse those anyway since the tree filters them visually.
    if (path.includes('/.git/') || path.endsWith('/.git')) return;
    const parent = path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '/work';
    if (tree.expanded.has(parent)) void tree.refreshPath(parent);
  });

  useEffect(() => {
    if (!menu) return;
    const onClick = () => setMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenu(null);
    };
    window.addEventListener('click', onClick);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('click', onClick);
      window.removeEventListener('keydown', onKey);
    };
  }, [menu]);

  if (tree.error) {
    return (
      <div className="p-3 text-xs text-ide-danger">Could not load file tree: {tree.error}</div>
    );
  }
  if (!tree.root) {
    return <div className="p-3 text-xs text-ide-textDim">Loading…</div>;
  }
  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 text-[11px] uppercase tracking-wider text-ide-textMuted font-medium border-b border-ide-borderSoft">
        Explorer
      </div>
      {actionError && (
        <div className="px-3 py-1.5 text-xs bg-ide-danger/10 text-ide-danger border-b border-ide-danger/30 truncate">
          {actionError}
        </div>
      )}
      <div className="overflow-auto flex-1 text-[13px] py-1 select-none">
        <Branch
          node={tree.root}
          depth={0}
          expanded={tree.expanded}
          toggle={tree.toggle}
          onOpenFile={onOpenFile}
          activePath={activePath}
          gitBadges={gitBadges}
          onContextMenu={(e, n) => {
            e.preventDefault();
            setMenu({
              x: e.clientX,
              y: e.clientY,
              path: n.path,
              name: n.name,
              isDir: n.kind === 'dir',
            });
          }}
          renaming={renaming}
          onRenameChange={(v) => setRenaming((r) => (r ? { ...r, value: v } : r))}
          onRenameCommit={async () => {
            if (!renaming) return;
            const orig = renaming.path;
            const parent = orig.slice(0, orig.lastIndexOf('/'));
            const dest = `${parent}/${renaming.value}`;
            setRenaming(null);
            if (dest === orig) return;
            const err = await tree.rename(orig, dest);
            setActionError(err);
          }}
          onRenameCancel={() => setRenaming(null)}
        />
      </div>
      {menu && (
        <ul
          className="fixed z-50 bg-ide-deep border border-ide-border rounded-md shadow-2xl py-1 text-xs min-w-[160px]"
          style={{ top: menu.y, left: menu.x }}
          onClick={(e) => e.stopPropagation()}
        >
          {!menu.isDir && (
            <li>
              <button
                type="button"
                onClick={() => {
                  onOpenFile(menu.path);
                  setMenu(null);
                }}
                className="block w-full text-left px-3 py-1.5 text-ide-text hover:bg-ide-accent hover:text-ide-textBright"
              >
                Open
              </button>
            </li>
          )}
          <li>
            <button
              type="button"
              onClick={() => {
                setRenaming({ path: menu.path, value: menu.name });
                setMenu(null);
              }}
              className="block w-full text-left px-3 py-1.5 text-ide-text hover:bg-ide-accent hover:text-ide-textBright"
            >
              Rename
            </button>
          </li>
          <li>
            <button
              type="button"
              onClick={async () => {
                const ok = window.confirm(
                  `Delete ${menu.isDir ? 'folder' : 'file'} ${menu.name}?${menu.isDir ? '\n\nThis will recursively delete its contents.' : ''}`,
                );
                setMenu(null);
                if (!ok) return;
                const err = await tree.remove(menu.path, menu.isDir);
                setActionError(err);
              }}
              className="block w-full text-left px-3 py-1.5 text-ide-danger hover:bg-ide-danger/20"
            >
              Delete
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}

type BranchProps = {
  node: TreeNode;
  depth: number;
  expanded: Set<string>;
  toggle: (p: string) => Promise<void>;
  onOpenFile: (path: string) => void;
  activePath: string | null;
  gitBadges?: Map<string, string>;
  onContextMenu: (e: React.MouseEvent, n: TreeNode) => void;
  renaming: { path: string; value: string } | null;
  onRenameChange: (v: string) => void;
  onRenameCommit: () => void;
  onRenameCancel: () => void;
};

function Branch({
  node,
  depth,
  expanded,
  toggle,
  onOpenFile,
  activePath,
  gitBadges,
  onContextMenu,
  renaming,
  onRenameChange,
  onRenameCommit,
  onRenameCancel,
}: BranchProps): JSX.Element {
  const isOpen = expanded.has(node.path);
  const isActive = activePath === node.path;
  const isRenaming = renaming?.path === node.path;
  const indent = 4 + depth * 12;

  if (isRenaming) {
    return (
      <div className="flex items-center gap-1 py-0.5" style={{ paddingLeft: indent }}>
        <input
          autoFocus
          value={renaming.value}
          onChange={(e) => onRenameChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') onRenameCommit();
            if (e.key === 'Escape') onRenameCancel();
          }}
          onBlur={onRenameCommit}
          className="flex-1 mx-1 px-1.5 py-0.5 text-[13px] bg-ide-bg border border-ide-accent rounded text-ide-text focus:outline-none"
        />
      </div>
    );
  }

  if (node.kind === 'file') {
    const badge = gitBadges?.get(node.path);
    return (
      <button
        type="button"
        onClick={() => onOpenFile(node.path)}
        onContextMenu={(e) => onContextMenu(e, node)}
        className={
          'flex items-center w-full text-left py-0.5 pr-2 transition-colors ' +
          (isActive
            ? 'bg-ide-active text-ide-textBright'
            : 'text-ide-text hover:bg-ide-hover')
        }
        style={{ paddingLeft: indent }}
      >
        <span className="inline-block w-3 mr-1" />
        <FileIcon name={node.name} />
        <span className="truncate flex-1">{node.name}</span>
        {badge && (
          <span
            className={`ml-2 w-3 text-center font-mono text-[12px] font-bold ${badgeColor(badge)}`}
            title={badgeTitle(badge)}
          >
            {badge}
          </span>
        )}
      </button>
    );
  }
  return (
    <div>
      <button
        type="button"
        onClick={() => void toggle(node.path)}
        onContextMenu={(e) => onContextMenu(e, node)}
        className="flex items-center w-full text-left py-0.5 text-ide-text hover:bg-ide-hover"
        style={{ paddingLeft: indent }}
      >
        <span className="inline-flex items-center justify-center w-3 mr-1 text-ide-textMuted">
          {isOpen ? '▾' : '▸'}
        </span>
        <FolderIcon open={isOpen} />
        <span className="truncate">{node.name}</span>
      </button>
      {isOpen && node.children && (
        <div>
          {node.children.length === 0 ? (
            <div
              className="py-0.5 text-xs text-ide-textDim italic"
              style={{ paddingLeft: indent + 28 }}
            >
              empty
            </div>
          ) : (
            node.children.map((c) => (
              <Branch
                key={c.path}
                node={c}
                depth={depth + 1}
                expanded={expanded}
                toggle={toggle}
                onOpenFile={onOpenFile}
                activePath={activePath}
                gitBadges={gitBadges}
                onContextMenu={onContextMenu}
                renaming={renaming}
                onRenameChange={onRenameChange}
                onRenameCommit={onRenameCommit}
                onRenameCancel={onRenameCancel}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

function FolderIcon({ open }: { open: boolean }): JSX.Element {
  // Minimal — VS Code uses muted yellow; we keep it close.
  return (
    <span aria-hidden className="inline-block mr-1.5 text-[#dcb67a]">
      {open ? '📂' : '📁'}
    </span>
  );
}

function FileIcon({ name }: { name: string }): JSX.Element {
  // Minimal color hint. VS Code's icon theme uses subtle palette per ext.
  const ext = name.includes('.') ? name.slice(name.lastIndexOf('.') + 1).toLowerCase() : '';
  const color: Record<string, string> = {
    ts: 'text-[#3b8eea]',
    tsx: 'text-[#3b8eea]',
    js: 'text-[#dcdcaa]',
    jsx: 'text-[#dcdcaa]',
    py: 'text-[#3b8eea]',
    md: 'text-[#9a9a9a]',
    json: 'text-[#dcdcaa]',
    yml: 'text-[#c586c0]',
    yaml: 'text-[#c586c0]',
    css: 'text-[#ce9178]',
    scss: 'text-[#ce9178]',
    html: 'text-[#ce9178]',
    sh: 'text-[#4ec9b0]',
    rs: 'text-[#ce9178]',
    go: 'text-[#3b8eea]',
    lock: 'text-[#6b6b6b]',
    toml: 'text-[#c586c0]',
  };
  const cls = color[ext] ?? 'text-[#9a9a9a]';
  return <span className={`inline-block mr-1.5 ${cls}`} aria-hidden>●</span>;
}

function badgeColor(char: string): string {
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

function badgeTitle(char: string): string {
  return (
    {
      M: 'Modified',
      A: 'Added (staged)',
      D: 'Deleted',
      U: 'Untracked',
      R: 'Renamed',
    } as Record<string, string>
  )[char] ?? char;
}
