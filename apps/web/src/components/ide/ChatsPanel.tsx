import { useEffect, useMemo, useState } from 'react';
import { useChatStream } from '../../hooks/useChatStream';
import {
  cancelChat,
  createChat,
  getChat,
  listChats,
  sendMessage,
  type ChatResponse,
} from '../../lib/chats';
import { ChatTranscript } from './ChatTranscript';

// List-view refresh cadence. The chat *view* uses the WS stream and
// doesn't poll at all; this only affects the sidebar's list of chats.
const POLL_MS = 5_000;

type Mode = 'list' | 'new' | { kind: 'view'; chatId: string };

export function ChatsPanel(): JSX.Element {
  const [mode, setMode] = useState<Mode>('list');
  const [chats, setChats] = useState<ChatResponse[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Poll the chat list while in `list` mode.
  useEffect(() => {
    if (mode !== 'list') return;
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await listChats();
        if (!cancelled) setChats(next);
      } catch (exc) {
        if (!cancelled) setError(String(exc));
      }
    };
    void tick();
    const t = window.setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [mode]);

  return (
    <div className="h-full flex flex-col bg-ide-panel">
      <Header
        mode={mode}
        onBack={() => setMode('list')}
        onNew={() => setMode('new')}
      />
      <div className="flex-1 min-h-0 overflow-hidden">
        {mode === 'list' && (
          <ChatList
            chats={chats}
            error={error}
            onOpen={(chatId) => setMode({ kind: 'view', chatId })}
            onNew={() => setMode('new')}
          />
        )}
        {mode === 'new' && (
          <NewChat
            onCreated={(chatId) => setMode({ kind: 'view', chatId })}
            onCancel={() => setMode('list')}
          />
        )}
        {typeof mode === 'object' && mode.kind === 'view' && (
          <ChatView chatId={mode.chatId} />
        )}
      </div>
    </div>
  );
}

function Header({
  mode,
  onBack,
  onNew,
}: {
  mode: Mode;
  onBack: () => void;
  onNew: () => void;
}): JSX.Element {
  const showBack = mode !== 'list';
  return (
    <div className="flex items-center justify-between px-3 py-2 border-b border-ide-borderSoft">
      <div className="flex items-center gap-2">
        {showBack && (
          <button
            type="button"
            onClick={onBack}
            className="text-ide-textMuted hover:text-ide-textBright text-xs"
          >
            ← Chats
          </button>
        )}
        {!showBack && (
          <div className="text-[11px] uppercase tracking-wider text-ide-textMuted font-medium">
            Chats
          </div>
        )}
      </div>
      {mode === 'list' && (
        <button
          type="button"
          onClick={onNew}
          className="px-2.5 py-1 bg-ide-accent text-ide-textBright rounded text-xs font-medium hover:bg-ide-accentHover transition-colors"
        >
          + New chat
        </button>
      )}
    </div>
  );
}

function ChatList({
  chats,
  error,
  onOpen,
  onNew,
}: {
  chats: ChatResponse[];
  error: string | null;
  onOpen: (chatId: string) => void;
  onNew: () => void;
}): JSX.Element {
  if (error) {
    return (
      <div className="p-4 text-xs text-ide-danger break-words">
        Couldn’t load chats: {error}
      </div>
    );
  }
  if (chats.length === 0) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
        <div className="text-ide-textMuted mb-3 text-sm">No chats yet</div>
        <button
          type="button"
          onClick={onNew}
          className="px-3 py-1.5 bg-ide-accent text-ide-textBright rounded text-xs font-medium hover:bg-ide-accentHover transition-colors"
        >
          Start a chat
        </button>
      </div>
    );
  }
  return (
    <div className="overflow-y-auto h-full">
      <ul className="divide-y divide-ide-borderSoft">
        {chats.map((c) => (
          <li key={c.id}>
            <button
              type="button"
              onClick={() => onOpen(c.id)}
              className="w-full text-left px-3 py-2.5 hover:bg-ide-deep transition-colors"
            >
              <div className="flex items-center gap-2">
                <StatusDot status={c.status} />
                <span className="text-sm text-ide-textBright truncate">
                  {c.title}
                </span>
              </div>
              <div className="text-[11px] text-ide-textDim mt-0.5 truncate">
                {c.status} · {new Date(c.created_at).toLocaleString()}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatusDot({ status }: { status: ChatResponse['status'] }): JSX.Element {
  const color = useMemo(() => {
    switch (status) {
      case 'running':
        return 'bg-ide-accent';
      case 'awaiting_input':
        return 'bg-ide-warn';
      case 'completed':
        return 'bg-ide-ok';
      case 'failed':
      case 'cancelled':
        return 'bg-ide-danger';
      default:
        return 'bg-ide-borderSoft';
    }
  }, [status]);
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />;
}

function NewChat({
  onCreated,
  onCancel,
}: {
  onCreated: (chatId: string) => void;
  onCancel: () => void;
}): JSX.Element {
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!prompt.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await createChat(prompt.trim());
      onCreated(res.chat.id);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full flex flex-col p-3 gap-3">
      <textarea
        autoFocus
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void submit();
          }
        }}
        placeholder="What should the agent do?"
        className="flex-1 min-h-0 bg-ide-deep border border-ide-border rounded p-2 text-sm text-ide-textBright resize-none focus:outline-none focus:border-ide-accent"
      />
      {error && <div className="text-xs text-ide-danger">{error}</div>}
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="px-2.5 py-1 text-ide-textMuted hover:text-ide-textBright text-xs"
        >
          Cancel
        </button>
        <button
          type="button"
          disabled={!prompt.trim() || busy}
          onClick={() => void submit()}
          className="px-3 py-1 bg-ide-accent text-ide-textBright rounded text-xs font-medium disabled:opacity-50 hover:bg-ide-accentHover transition-colors"
        >
          {busy ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  );
}

function ChatView({ chatId }: { chatId: string }): JSX.Element {
  const [chat, setChat] = useState<ChatResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState('');
  const [busy, setBusy] = useState(false);
  const { events, status: streamStatus } = useChatStream(chatId);
  const [dismissedSuggestions, setDismissedSuggestions] = useState<Set<string>>(
    () => new Set(),
  );

  // One-time fetch for static chat metadata (title, initial_prompt,
  // created_at). Live state — status flips, token usage, transcript —
  // arrives over the WS stream via `useChatStream`. No polling: we
  // were spamming `GET /api/chats/{id}` every 2s × StrictMode
  // double-mount. The stream is the source of truth now.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const c = await getChat(chatId);
        if (!cancelled) setChat(c);
      } catch (exc) {
        if (!cancelled) setError(String(exc));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [chatId]);

  const visibleEvents = useMemo(
    () =>
      events.filter((ev) => {
        if (ev.type !== 'user_agent.suggestion') return true;
        const sid = (ev as { suggestion_id?: string }).suggestion_id;
        return !(sid && dismissedSuggestions.has(sid));
      }),
    [events, dismissedSuggestions],
  );

  // Derive live status from the event stream. `result` ends a turn;
  // `error` flips to failed. (`chat.started` keeps "running".) This
  // replaces the previous 2s GET poll.
  useEffect(() => {
    if (!chat) return;
    const last = events[events.length - 1];
    if (!last) return;
    if (last.type === 'result') {
      const isError = Boolean((last as { is_error?: boolean }).is_error);
      const next = isError ? 'failed' : 'completed';
      if (chat.status !== next) setChat({ ...chat, status: next });
    } else if (last.type === 'error') {
      if (chat.status !== 'failed') setChat({ ...chat, status: 'failed' });
    } else if (chat.status === 'completed' || chat.status === 'failed') {
      // A new event arrived after a previous turn closed — a follow-up
      // is in flight. Flip back to running.
      setChat({ ...chat, status: 'running' });
    }
  }, [chat, events]);

  const send = async (text?: string) => {
    const value = (text ?? reply).trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      await sendMessage(chatId, value);
      if (text === undefined) setReply('');
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  };

  const onCancel = async () => {
    try {
      await cancelChat(chatId);
    } catch (exc) {
      setError(String(exc));
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 border-b border-ide-borderSoft">
        <div className="flex items-center gap-2 mb-0.5">
          {chat && <StatusDot status={chat.status} />}
          <div className="text-sm text-ide-textBright truncate flex-1">
            {chat?.title ?? '…'}
          </div>
          <StreamIndicator status={streamStatus} />
          {chat && chat.status === 'running' && (
            <button
              type="button"
              onClick={() => void onCancel()}
              className="text-[11px] text-ide-danger hover:underline"
            >
              Cancel
            </button>
          )}
        </div>
        <div className="text-[11px] text-ide-textDim">
          {chat ? `${chat.status}` : 'loading…'}
        </div>
      </div>
      {chat && (
        <ChatTranscript
          initialPrompt={chat.initial_prompt}
          events={visibleEvents}
          onAcceptSuggestion={(sid, text) => {
            setDismissedSuggestions((s) => {
              const next = new Set(s);
              next.add(sid);
              return next;
            });
            void send(text);
          }}
          onDismissSuggestion={(sid) =>
            setDismissedSuggestions((s) => {
              const next = new Set(s);
              next.add(sid);
              return next;
            })
          }
        />
      )}
      {error && (
        <div className="px-3 pb-2 text-xs text-ide-danger">{error}</div>
      )}
      <div className="border-t border-ide-borderSoft p-2 flex gap-2">
        <input
          type="text"
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          placeholder="Reply…"
          className="flex-1 bg-ide-deep border border-ide-border rounded px-2 py-1 text-sm text-ide-textBright focus:outline-none focus:border-ide-accent"
        />
        <button
          type="button"
          disabled={!reply.trim() || busy}
          onClick={() => void send()}
          className="px-3 py-1 bg-ide-accent text-ide-textBright rounded text-xs font-medium disabled:opacity-50 hover:bg-ide-accentHover transition-colors"
        >
          {busy ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  );
}

function StreamIndicator({
  status,
}: {
  status: 'connecting' | 'live' | 'reconnecting' | 'closed';
}): JSX.Element {
  const label =
    status === 'live'
      ? 'live'
      : status === 'connecting'
        ? '…'
        : status === 'reconnecting'
          ? 'reconnecting'
          : 'closed';
  const color =
    status === 'live'
      ? 'text-ide-ok'
      : status === 'reconnecting' || status === 'connecting'
        ? 'text-ide-warn'
        : 'text-ide-textDim';
  return <span className={`text-[10px] ${color}`}>{label}</span>;
}
