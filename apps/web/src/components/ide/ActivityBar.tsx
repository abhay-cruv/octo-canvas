/**
 * VS Code-style 48px vertical strip on the very left of the IDE. Two
 * sections in slice 6 — Files and Git. Each is a button that swaps the
 * left-panel content via the `view` prop on the route.
 */

export type ActivityView = 'files' | 'git';

type Props = {
  view: ActivityView;
  setView: (v: ActivityView) => void;
  /** Number to show as a small badge next to the Git icon. Hidden when 0. */
  gitBadge?: number;
};

export function ActivityBar({ view, setView, gitBadge = 0 }: Props): JSX.Element {
  return (
    <div className="h-full w-12 bg-ide-deep border-r border-ide-border flex flex-col items-center py-2 gap-1">
      <ActivityButton
        label="Explorer (Cmd+Shift+E)"
        active={view === 'files'}
        onClick={() => setView('files')}
      >
        <FilesIcon />
      </ActivityButton>
      <ActivityButton
        label="Source Control (Cmd+Shift+G)"
        active={view === 'git'}
        onClick={() => setView('git')}
        badge={gitBadge}
      >
        <GitIcon />
      </ActivityButton>
    </div>
  );
}

function ActivityButton({
  active,
  onClick,
  label,
  children,
  badge,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  children: React.ReactNode;
  badge?: number;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={
        'relative w-12 h-12 flex items-center justify-center transition-colors ' +
        (active
          ? 'text-ide-textBright border-l-2 border-l-ide-accent -ml-px'
          : 'text-ide-textMuted hover:text-ide-textBright')
      }
    >
      {children}
      {badge !== undefined && badge > 0 && (
        <span className="absolute top-1 right-1 min-w-[18px] h-[18px] px-1 bg-ide-accent text-ide-textBright text-[10px] font-medium rounded-full flex items-center justify-center">
          {badge > 99 ? '99+' : badge}
        </span>
      )}
    </button>
  );
}

// Small inline SVGs — avoid the dependency on an icon library. They follow
// VS Code Codicons in spirit (~24px viewBox, 1.5px strokes).

function FilesIcon(): JSX.Element {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}

function GitIcon(): JSX.Element {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="6" cy="6" r="2" />
      <circle cx="6" cy="18" r="2" />
      <circle cx="18" cy="12" r="2" />
      <path d="M6 8v8" />
      <path d="M18 10a4 4 0 0 0-4-4H10" />
      <path d="M10 6L8 4" />
      <path d="M10 6l-2 2" />
    </svg>
  );
}
