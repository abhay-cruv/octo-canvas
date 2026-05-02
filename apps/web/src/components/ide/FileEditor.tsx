import { lazy, Suspense, useEffect } from 'react';

import { type OpenFileState } from '../../hooks/ide';

const Monaco = lazy(() =>
  import('@monaco-editor/react').then((m) => ({ default: m.default })),
);
const MonacoDiff = lazy(() =>
  import('@monaco-editor/react').then((m) => ({ default: m.DiffEditor })),
);

type Props = {
  files: OpenFileState[];
  active: OpenFileState | null;
  diffMode: boolean;
  /** HEAD content for the active file (null when not loaded / no diff). */
  diffOriginal: string | null;
  diffLoading: boolean;
  onActivate: (path: string) => void;
  onClose: (path: string) => void;
  onChange: (path: string, s: string) => void;
  onSave: (path: string) => void;
  onReload: (path: string) => void;
  onToggleDiff: () => void;
};

export function FileEditor({
  files,
  active,
  diffMode,
  diffOriginal,
  diffLoading,
  onActivate,
  onClose,
  onChange,
  onSave,
  onReload,
  onToggleDiff,
}: Props): JSX.Element {
  useEffect(() => {
    function handler(e: KeyboardEvent): void {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        if (active) onSave(active.path);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'w') {
        e.preventDefault();
        if (active) onClose(active.path);
      }
    }
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [active, onSave, onClose]);

  if (files.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-ide-textDim bg-ide-bg">
        <div className="text-center">
          <div className="text-ide-textMuted mb-2 text-base">No file open</div>
          <div className="text-xs text-ide-textDim">
            Pick a file from the Explorer · <span className="font-mono">⌘S</span> save · <span className="font-mono">⌘W</span> close
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="h-full flex flex-col bg-ide-bg">
      <Tabs
        files={files}
        active={active}
        diffMode={diffMode}
        onActivate={onActivate}
        onClose={onClose}
        onToggleDiff={onToggleDiff}
      />
      {active && (
        <>
          {active.error && (
            <div className="px-3 py-1.5 text-xs bg-ide-danger/10 text-ide-danger border-b border-ide-danger/30 flex items-center justify-between">
              <span className="truncate">{active.error}</span>
              {active.error.includes('changed on disk') && (
                <button
                  type="button"
                  onClick={() => onReload(active.path)}
                  className="ml-2 px-2 py-0.5 bg-ide-accent text-ide-textBright rounded text-xs hover:bg-ide-accentHover"
                >
                  Reload
                </button>
              )}
            </div>
          )}
          <div className="flex-1 min-h-0">
            <Suspense fallback={<EditorFallback />}>
              {active.loading ? (
                <EditorFallback />
              ) : diffMode ? (
                <DiffView active={active} original={diffOriginal} loading={diffLoading} />
              ) : (
                <Monaco
                  height="100%"
                  path={active.path}
                  defaultLanguage={undefined}
                  theme="vs-dark"
                  value={active.content}
                  onChange={(v) => onChange(active.path, v ?? '')}
                  options={{
                    minimap: { enabled: false },
                    fontSize: 13,
                    fontFamily:
                      'ui-monospace, "SF Mono", Menlo, Monaco, "Cascadia Code", Consolas, monospace',
                    automaticLayout: true,
                    tabSize: 2,
                    smoothScrolling: true,
                    scrollBeyondLastLine: false,
                    renderLineHighlight: 'all',
                    cursorSmoothCaretAnimation: 'on',
                    padding: { top: 8 },
                    // Long lines scroll horizontally instead of wrapping.
                    wordWrap: 'off',
                    // Make the horizontal scrollbar visible (default is
                    // `auto` which hides until hover; that confused users
                    // into thinking long lines were truncated).
                    scrollbar: {
                      horizontal: 'visible',
                      vertical: 'visible',
                      horizontalScrollbarSize: 12,
                      verticalScrollbarSize: 12,
                    },
                  }}
                />
              )}
            </Suspense>
          </div>
          <StatusBar file={active} diffMode={diffMode} />
        </>
      )}
    </div>
  );
}

function DiffView({
  active,
  original,
  loading,
}: {
  active: OpenFileState;
  original: string | null;
  loading: boolean;
}): JSX.Element {
  if (loading || original === null) {
    return <EditorFallback label="Loading diff…" />;
  }
  const language = languageFromPath(active.path);
  const noChange = original === active.content;
  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-1 flex items-center gap-3 text-[11px] bg-ide-deep border-b border-ide-borderSoft">
        <span className="flex items-center gap-1.5 text-ide-textMuted">
          <span className="w-2 h-2 rounded-sm bg-ide-danger/40" /> HEAD
        </span>
        <span className="text-ide-textDim">vs</span>
        <span className="flex items-center gap-1.5 text-ide-textMuted">
          <span className="w-2 h-2 rounded-sm bg-ide-ok/40" /> working tree
        </span>
        {noChange && (
          <span className="ml-auto text-ide-textDim italic">
            no diff — current matches HEAD
          </span>
        )}
      </div>
      <div className="flex-1 min-h-0">
        <MonacoDiff
          height="100%"
          theme="vs-dark"
          original={original}
          modified={active.content}
          language={language}
          options={{
            readOnly: false,
            renderSideBySide: true,
            fontSize: 13,
            fontFamily:
              'ui-monospace, "SF Mono", Menlo, Monaco, "Cascadia Code", Consolas, monospace',
            automaticLayout: true,
            scrollBeyondLastLine: false,
            minimap: { enabled: false },
            renderOverviewRuler: false,
            // Long lines scroll horizontally instead of wrapping — much
            // easier to read code diffs without forced wrap.
            diffWordWrap: 'off',
            wordWrap: 'off',
            ignoreTrimWhitespace: false,
            originalEditable: false,
            scrollbar: {
              horizontal: 'visible',
              vertical: 'visible',
              horizontalScrollbarSize: 12,
              verticalScrollbarSize: 12,
            },
          }}
        />
      </div>
    </div>
  );
}

function languageFromPath(path: string): string | undefined {
  const ext = path.includes('.') ? path.slice(path.lastIndexOf('.') + 1).toLowerCase() : '';
  const map: Record<string, string> = {
    ts: 'typescript',
    tsx: 'typescript',
    js: 'javascript',
    jsx: 'javascript',
    py: 'python',
    md: 'markdown',
    json: 'json',
    yml: 'yaml',
    yaml: 'yaml',
    css: 'css',
    scss: 'scss',
    html: 'html',
    sh: 'shell',
    bash: 'shell',
    rs: 'rust',
    go: 'go',
    toml: 'ini',
    sql: 'sql',
    xml: 'xml',
    Dockerfile: 'dockerfile',
  };
  return map[ext];
}

function Tabs({
  files,
  active,
  diffMode,
  onActivate,
  onClose,
  onToggleDiff,
}: {
  files: OpenFileState[];
  active: OpenFileState | null;
  diffMode: boolean;
  onActivate: (path: string) => void;
  onClose: (path: string) => void;
  onToggleDiff: () => void;
}): JSX.Element {
  return (
    <div className="flex items-stretch border-b border-ide-border bg-ide-deep overflow-x-auto">
      <div className="flex-1 flex items-stretch overflow-x-auto">
        {files.map((f) => {
          const isActive = active?.path === f.path;
          const name = f.path.slice(f.path.lastIndexOf('/') + 1);
          return (
            <div
              key={f.path}
              role="button"
              tabIndex={0}
              onClick={() => onActivate(f.path)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onActivate(f.path);
                }
              }}
              className={
                'group flex items-center gap-1.5 pl-3 pr-1.5 py-1.5 text-xs border-r border-ide-border cursor-pointer transition-colors ' +
                (isActive
                  ? 'bg-ide-tabActive text-ide-textBright border-t-2 border-t-ide-accent -mt-px'
                  : 'bg-ide-tab text-ide-textMuted hover:text-ide-text')
              }
              title={f.path}
            >
              <span className="font-mono whitespace-nowrap">{name}</span>
              {f.dirty && <span className="w-1.5 h-1.5 rounded-full bg-ide-accent" />}
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(f.path);
                }}
                className="ml-1 w-4 h-4 flex items-center justify-center rounded text-ide-textMuted hover:bg-ide-hover hover:text-ide-textBright"
                aria-label={`Close ${name}`}
              >
                ×
              </button>
            </div>
          );
        })}
      </div>
      {active && (
        <button
          type="button"
          onClick={onToggleDiff}
          className={
            'px-3 text-xs border-l border-ide-border transition-colors ' +
            (diffMode
              ? 'bg-ide-accent text-ide-textBright'
              : 'text-ide-textMuted hover:text-ide-textBright hover:bg-ide-hover')
          }
          title="Toggle diff against HEAD"
        >
          Diff
        </button>
      )}
    </div>
  );
}

function StatusBar({
  file,
  diffMode,
}: {
  file: OpenFileState;
  diffMode: boolean;
}): JSX.Element {
  return (
    <div className="flex items-center justify-between px-3 py-1 text-[11px] text-ide-textMuted bg-ide-deep border-t border-ide-border">
      <span className="font-mono truncate">{file.path}</span>
      <div className="flex items-center gap-3">
        {diffMode && <span className="text-ide-accent">diff vs HEAD</span>}
        <span>{file.content.length} chars</span>
        {file.dirty && <span className="text-ide-warn">● modified</span>}
        {file.sha && (
          <span className="font-mono text-ide-textDim">sha {file.sha.slice(0, 7)}</span>
        )}
      </div>
    </div>
  );
}

function EditorFallback({ label }: { label?: string } = {}): JSX.Element {
  return (
    <div className="h-full flex items-center justify-center text-xs text-ide-textDim">
      {label ?? 'Loading editor…'}
    </div>
  );
}
