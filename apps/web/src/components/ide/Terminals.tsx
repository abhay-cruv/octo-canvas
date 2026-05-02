import { useTerminals } from '../../hooks/ide';
import { Terminal } from './Terminal';

type Props = { sandboxId: string };

export function Terminals({ sandboxId }: Props): JSX.Element {
  const { terminals, activeId, add, close, resetAll, setActive } = useTerminals();

  return (
    <div className="h-full flex flex-col bg-ide-bg">
      <div className="flex items-stretch border-b border-ide-border bg-ide-deep text-xs">
        <div className="px-3 py-1.5 text-[11px] uppercase tracking-wider text-ide-textMuted font-medium border-r border-ide-border">
          Terminal
        </div>
        {terminals.map((t, idx) => {
          const isActive = t.id === activeId;
          return (
            <div
              key={t.id}
              role="button"
              tabIndex={0}
              onClick={() => setActive(t.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setActive(t.id);
                }
              }}
              className={
                'group flex items-center gap-1.5 pl-3 pr-1.5 py-1.5 border-r border-ide-border cursor-pointer transition-colors ' +
                (isActive
                  ? 'bg-ide-tabActive text-ide-textBright border-t-2 border-t-ide-accent -mt-px'
                  : 'bg-ide-tab text-ide-textMuted hover:text-ide-text')
              }
            >
              <span className="font-mono">{idx + 1}</span>
              <span className="text-ide-textDim">·</span>
              <span className="font-mono">{t.label}</span>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  close(t.id);
                }}
                className="ml-1 w-4 h-4 flex items-center justify-center rounded text-ide-textMuted hover:bg-ide-hover hover:text-ide-textBright"
                aria-label={`Close terminal ${idx + 1}`}
              >
                ×
              </button>
            </div>
          );
        })}
        <button
          type="button"
          onClick={add}
          className="px-3 py-1.5 text-ide-textMuted hover:text-ide-textBright hover:bg-ide-hover transition-colors"
          aria-label="New terminal"
          title="New terminal"
        >
          +
        </button>
        <button
          type="button"
          onClick={resetAll}
          className="ml-auto px-3 py-1.5 text-ide-textMuted hover:text-ide-danger hover:bg-ide-hover transition-colors"
          aria-label="Reset all terminals"
          title="Force-replace every terminal with a fresh session (clears stale Sprites Exec sessions)"
        >
          ↻
        </button>
      </div>
      <div className="flex-1 min-h-0 relative">
        {terminals.map((t) => (
          <div
            key={t.id}
            className="absolute inset-0"
            style={{ display: t.id === activeId ? 'block' : 'none' }}
          >
            <Terminal sandboxId={sandboxId} terminalId={t.id} visible={t.id === activeId} />
          </div>
        ))}
      </div>
    </div>
  );
}
