import { useState } from 'react';

export function ChatsPanel(): JSX.Element {
  const [toast, setToast] = useState<string | null>(null);
  return (
    <div className="h-full flex flex-col bg-ide-panel">
      <div className="flex items-center justify-between px-3 py-2 border-b border-ide-borderSoft">
        <div className="text-[11px] uppercase tracking-wider text-ide-textMuted font-medium">
          Chats
        </div>
        <button
          type="button"
          onClick={() => {
            setToast('Chats arrive in slice 8');
            window.setTimeout(() => setToast(null), 2400);
          }}
          className="px-2.5 py-1 bg-ide-accent text-ide-textBright rounded text-xs font-medium hover:bg-ide-accentHover transition-colors"
        >
          + New chat
        </button>
      </div>
      <div className="flex-1 flex items-center justify-center p-6 text-center">
        <div>
          <div className="text-ide-textMuted mb-2">Agent chats</div>
          <div className="text-xs text-ide-textDim leading-relaxed">
            Chat with your codebase
            <br />
            arrives in slice 8
          </div>
        </div>
      </div>
      {toast && (
        <div className="absolute bottom-3 left-3 right-3 px-3 py-2 bg-ide-deep border border-ide-border text-ide-textBright text-xs rounded shadow-lg text-center">
          {toast}
        </div>
      )}
    </div>
  );
}
