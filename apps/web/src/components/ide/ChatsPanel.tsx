import { useEffect, useMemo, useRef, useState } from 'react';
import { useChatStream } from '../../hooks/useChatStream';
import {
  cancelChat,
  createChat,
  getChat,
  listChats,
  listChatTurns,
  sendMessage,
  type ChatResponse,
} from '../../lib/chats';
import { ChatTranscript, type UserMessageEntry } from './ChatTranscript';

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
      <div className="flex items-center gap-2">
        <PermissionModeToggle />
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
    </div>
  );
}

interface UserSettings {
  user_agent_enabled: boolean;
  user_agent_provider: 'anthropic' | 'openai' | 'google';
  user_agent_model: string;
  chat_permission_mode: 'all_granted' | 'ask';
}

function settingsUrl(): string {
  const base = import.meta.env.VITE_ORCHESTRATOR_BASE_URL as string | undefined;
  if (!base) throw new Error('VITE_ORCHESTRATOR_BASE_URL is not set');
  return `${base.replace(/\/$/, '')}/api/me/settings`;
}

function PermissionModeToggle(): JSX.Element {
  // Optimistic default: most users want auto. We still fetch the
  // canonical state on mount; if it differs we update. Either way the
  // toggle is clickable from the first render.
  const [mode, setMode] = useState<'all_granted' | 'ask'>('all_granted');
  const [busy, setBusy] = useState(false);
  const [tooltip, setTooltip] = useState<string>('loading settings…');

  // Refetch on click if a previous load failed — gives a path to recover.
  const refresh = async () => {
    try {
      const r = await fetch(settingsUrl(), { credentials: 'include' });
      if (!r.ok) {
        setTooltip(`load failed: HTTP ${r.status}`);
        return;
      }
      const j = (await r.json()) as UserSettings;
      setMode(j.chat_permission_mode);
      setTooltip('');
    } catch (exc) {
      setTooltip(`load failed: ${String(exc).slice(0, 80)}`);
    }
  };

  useEffect(() => {
    void refresh();
    // Refresh once on mount only; flip() handles subsequent state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const flip = async () => {
    if (busy) return;
    const next = mode === 'all_granted' ? 'ask' : 'all_granted';
    setBusy(true);
    setMode(next); // optimistic
    try {
      const r = await fetch(settingsUrl(), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chat_permission_mode: next }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as UserSettings;
      setMode(j.chat_permission_mode);
      setTooltip('');
    } catch (exc) {
      // Rollback on failure
      setMode((prev) => (prev === next ? (next === 'ask' ? 'all_granted' : 'ask') : prev));
      setTooltip(`save failed: ${String(exc).slice(0, 80)}`);
    } finally {
      setBusy(false);
    }
  };

  const label = mode === 'all_granted' ? 'auto' : 'ask';
  const baseTitle =
    mode === 'all_granted'
      ? 'All tools auto-allowed. Click to switch to ASK mode.'
      : 'Agent asks before risky tools. Click to switch to AUTO mode.';
  const dotColor = mode === 'all_granted' ? 'bg-ide-ok' : 'bg-ide-warn';
  return (
    <button
      type="button"
      onClick={() => void flip()}
      disabled={busy}
      title={tooltip ? `${baseTitle} (${tooltip})` : baseTitle}
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-ide-deep border text-[10.5px] uppercase tracking-wider transition-colors disabled:opacity-50 ${
        tooltip
          ? 'border-ide-danger/60 text-ide-danger hover:border-ide-danger'
          : 'border-ide-borderSoft text-ide-textMuted hover:text-ide-textBright hover:border-ide-border'
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
      <span>perm: {label}</span>
    </button>
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
  // Locally-tracked follow-up user messages. Bridge events don't
  // echo user input, so we record each successful `sendMessage` and
  // pass the list to the transcript for inline rendering.
  const [followUps, setFollowUps] = useState<UserMessageEntry[]>([]);
  const replyRef = useRef<HTMLTextAreaElement | null>(null);

  // One-time fetch for static chat metadata (title, initial_prompt,
  // created_at) + persisted ChatTurn rows. Live state — status flips,
  // token usage, transcript — arrives over the WS stream via
  // `useChatStream`. The turns fetch covers page-refresh / chat-reopen:
  // optimistic followUps state is wiped on remount, so we seed from
  // the authoritative server list (skipping the initial-prompt turn,
  // which already renders via `chat.initial_prompt`).
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [c, turns] = await Promise.all([
          getChat(chatId),
          listChatTurns(chatId),
        ]);
        if (cancelled) return;
        setChat(c);
        const followUpEntries: UserMessageEntry[] = turns
          .filter((t) => t.is_follow_up)
          .map((t) => ({
            id: t.id,
            text: t.prompt,
            sentAt: Date.parse(t.started_at),
          }));
        setFollowUps(followUpEntries);
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
    // Optimistically render the user's message immediately so they
    // see what they sent without waiting for the bridge round-trip.
    const entry: UserMessageEntry = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      text: value,
      sentAt: Date.now(),
    };
    setFollowUps((prev) => [...prev, entry]);
    if (text === undefined) {
      setReply('');
      // Reset textarea height after clearing.
      if (replyRef.current) replyRef.current.style.height = 'auto';
    }
    try {
      await sendMessage(chatId, value);
    } catch (exc) {
      setError(String(exc));
      // Roll back the optimistic entry on failure.
      setFollowUps((prev) => prev.filter((e) => e.id !== entry.id));
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
          followUpUserMessages={followUps}
          status={chat.status}
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
        <div className="mx-3 my-2 px-3 py-2 rounded-lg bg-ide-danger/5 border border-ide-danger/40 text-xs text-ide-danger">
          {error}
        </div>
      )}
      <div className="border-t border-ide-borderSoft/60 bg-ide-panel/95 backdrop-blur-sm px-3 py-3">
        <div className="flex items-end gap-2 bg-ide-deep border border-ide-border rounded-2xl pl-3 pr-2 py-1.5 focus-within:border-ide-accent transition-colors">
          <textarea
            ref={replyRef}
            value={reply}
            rows={1}
            onChange={(e) => {
              setReply(e.target.value);
              // Auto-grow the textarea up to ~6 lines.
              const el = e.target;
              el.style.height = 'auto';
              el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.metaKey && !e.ctrlKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder="Send a message…   (Enter to send, Shift+Enter for newline)"
            className="flex-1 min-w-0 bg-transparent border-0 resize-none py-1.5 text-sm text-ide-textBright placeholder:text-ide-textDim focus:outline-none leading-relaxed"
          />
          <button
            type="button"
            disabled={!reply.trim() || busy}
            onClick={() => void send()}
            className="flex-shrink-0 mb-0.5 w-8 h-8 rounded-full bg-gradient-to-br from-ide-accent to-ide-accentHover text-white flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed enabled:hover:scale-105 transition-all shadow-sm"
            aria-label="Send"
          >
            {busy ? (
              <span className="block w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            ) : (
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
                <path
                  d="M2 8L14 2L8 14L7 9L2 8Z"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              </svg>
            )}
          </button>
        </div>
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
