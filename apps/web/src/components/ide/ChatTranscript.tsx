/**
 * ChatTranscript — slice 8 Phase 8b.
 *
 * Renders a unified merged transcript of:
 *  - the original user prompt + every follow-up the user sends
 *  - dev-agent streaming events from `useChatStream`:
 *      assistant.delta (accumulated into a single live block)
 *      assistant.message (final block at turn close)
 *      thinking (collapsible)
 *      tool.started / tool.finished (collapsible card)
 *      file.edit (inline diff link)
 *      token.usage (footer chip)
 *      result, error
 *  - user-agent suggestions (UserAgentSuggestion with override countdown)
 *
 * Streaming `assistant.delta` events fold into the live assistant
 * block until the matching `assistant.message` arrives; then the live
 * block's text is replaced by the canonical final text.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatStreamEvent } from '../../hooks/useChatStream';

export interface UserMessageEntry {
  /** Stable id; we use the timestamp for now since user messages
   * don't echo back from the bridge. */
  id: string;
  text: string;
  /** Used to position the message inside the transcript: a follow-up
   * sent at time T appears AFTER the most recent `result` event whose
   * arrival time is <= T (or at the end if no such result exists yet). */
  sentAt: number;
}

interface AssistantBlock {
  kind: 'assistant';
  id: string;
  text: string;
  finalized: boolean;
}

interface ThinkingBlockItem {
  kind: 'thinking';
  id: string;
  text: string;
}

interface ToolBlock {
  kind: 'tool';
  id: string;
  toolName: string;
  args: Record<string, unknown>;
  result?: { text: string; isError: boolean };
}

interface FileEditBlock {
  kind: 'file_edit';
  id: string;
  path: string;
  beforeSha: string | null;
  afterSha: string;
  summary: string;
}

interface SuggestionBlock {
  kind: 'suggestion';
  id: string;
  suggestionId: string;
  suggestedReply: string;
  reason: string;
  overrideDeadlineAt: string;
}

interface ErrorBlock {
  kind: 'error';
  id: string;
  errorKind: string;
  message: string;
}

interface UserBlock {
  kind: 'user';
  id: string;
  text: string;
}

interface TurnEndBlock {
  kind: 'turn_end';
  id: string;
}

type Block =
  | UserBlock
  | AssistantBlock
  | ThinkingBlockItem
  | ToolBlock
  | FileEditBlock
  | SuggestionBlock
  | ErrorBlock
  | TurnEndBlock;

interface ReducedState {
  blocks: Block[];
  liveAssistantId: string | null;
  totalInputTokens: number;
  totalOutputTokens: number;
}

const INITIAL: ReducedState = {
  blocks: [],
  liveAssistantId: null,
  totalInputTokens: 0,
  totalOutputTokens: 0,
};

function reduceEvents(events: ChatStreamEvent[]): ReducedState {
  let state: ReducedState = INITIAL;
  for (const ev of events) {
    state = applyEvent(state, ev);
  }
  return state;
}

function applyEvent(state: ReducedState, ev: ChatStreamEvent): ReducedState {
  const id = `${ev.type}-${ev.seq ?? Math.random().toString(36).slice(2)}`;
  switch (ev.type) {
    case 'assistant.delta': {
      const text = (ev.text as string) ?? '';
      if (state.liveAssistantId !== null) {
        const blocks = state.blocks.map((b) =>
          b.kind === 'assistant' && b.id === state.liveAssistantId
            ? { ...b, text: b.text + text }
            : b,
        );
        return { ...state, blocks };
      }
      const newId = id;
      return {
        ...state,
        liveAssistantId: newId,
        blocks: [
          ...state.blocks,
          { kind: 'assistant', id: newId, text, finalized: false },
        ],
      };
    }
    case 'assistant.message': {
      const text = (ev.text as string) ?? '';
      if (state.liveAssistantId !== null) {
        const blocks = state.blocks.map((b) =>
          b.kind === 'assistant' && b.id === state.liveAssistantId
            ? { ...b, text, finalized: true }
            : b,
        );
        return { ...state, blocks, liveAssistantId: null };
      }
      return {
        ...state,
        blocks: [
          ...state.blocks,
          { kind: 'assistant', id, text, finalized: true },
        ],
      };
    }
    case 'thinking': {
      return {
        ...state,
        blocks: [
          ...state.blocks,
          { kind: 'thinking', id, text: (ev.text as string) ?? '' },
        ],
      };
    }
    case 'tool.started': {
      const toolUseId = (ev.tool_use_id as string) ?? id;
      return {
        ...state,
        blocks: [
          ...state.blocks,
          {
            kind: 'tool',
            id: toolUseId,
            toolName: (ev.tool_name as string) ?? 'tool',
            args: (ev.args as Record<string, unknown>) ?? {},
          },
        ],
      };
    }
    case 'tool.finished': {
      const toolUseId = (ev.tool_use_id as string) ?? '';
      const blocks = state.blocks.map((b) =>
        b.kind === 'tool' && b.id === toolUseId
          ? {
              ...b,
              result: {
                text: (ev.result_preview as string) ?? '',
                isError: Boolean(ev.is_error),
              },
            }
          : b,
      );
      return { ...state, blocks };
    }
    case 'file.edit': {
      return {
        ...state,
        blocks: [
          ...state.blocks,
          {
            kind: 'file_edit',
            id,
            path: (ev.path as string) ?? '',
            beforeSha: (ev.before_sha as string | null) ?? null,
            afterSha: (ev.after_sha as string) ?? '',
            summary: (ev.summary as string) ?? '',
          },
        ],
      };
    }
    case 'user_agent.suggestion': {
      return {
        ...state,
        blocks: [
          ...state.blocks,
          {
            kind: 'suggestion',
            id,
            suggestionId: (ev.suggestion_id as string) ?? id,
            suggestedReply: (ev.suggested_reply as string) ?? '',
            reason: (ev.reason as string) ?? '',
            overrideDeadlineAt: (ev.override_deadline_at as string) ?? '',
          },
        ],
      };
    }
    case 'token.usage': {
      return {
        ...state,
        totalInputTokens: state.totalInputTokens + ((ev.input_delta as number) ?? 0),
        totalOutputTokens:
          state.totalOutputTokens + ((ev.output_delta as number) ?? 0),
      };
    }
    case 'result': {
      // Marker block — used to interleave follow-up user messages.
      return {
        ...state,
        liveAssistantId: null,
        blocks: [
          ...state.blocks,
          { kind: 'turn_end', id },
        ],
      };
    }
    case 'error': {
      return {
        ...state,
        blocks: [
          ...state.blocks,
          {
            kind: 'error',
            id,
            errorKind: (ev.kind as string) ?? 'error',
            message: (ev.message as string) ?? '',
          },
        ],
      };
    }
    default:
      return state;
  }
}

function interleaveUserMessages(
  baseBlocks: Block[],
  initialPrompt: string,
  followUps: UserMessageEntry[],
): Block[] {
  // Place the initial prompt at the very top, then interleave each
  // follow-up user message AFTER the next `turn_end` marker. If we
  // run out of turn_end markers, append the rest at the bottom (the
  // user's most recent send is in flight — they should see their text
  // immediately, even before any assistant frames arrive).
  const out: Block[] = [{ kind: 'user', id: 'initial', text: initialPrompt }];
  let followUpIdx = 0;
  for (const b of baseBlocks) {
    if (b.kind === 'turn_end') {
      // Drop the marker; insert next pending user message.
      const f = followUps[followUpIdx];
      if (f) {
        followUpIdx++;
        out.push({ kind: 'user', id: `u-${f.id}`, text: f.text });
      }
      continue;
    }
    out.push(b);
  }
  // Any follow-ups beyond the available turn_ends are pending — show
  // them at the end so the user sees their input immediately.
  while (followUpIdx < followUps.length) {
    const f = followUps[followUpIdx];
    if (!f) break;
    followUpIdx++;
    out.push({ kind: 'user', id: `u-${f.id}`, text: f.text });
  }
  return out;
}

interface ChatTranscriptProps {
  initialPrompt: string;
  events: ChatStreamEvent[];
  followUpUserMessages?: UserMessageEntry[];
  status?: 'running' | 'awaiting_input' | 'completed' | 'failed' | 'cancelled' | string;
  onAcceptSuggestion?: (suggestionId: string, text: string) => void;
  onDismissSuggestion?: (suggestionId: string) => void;
}

export function ChatTranscript({
  initialPrompt,
  events,
  followUpUserMessages = [],
  status = 'running',
  onAcceptSuggestion,
  onDismissSuggestion,
}: ChatTranscriptProps): JSX.Element {
  const state = useMemo(() => reduceEvents(events), [events]);
  const merged = useMemo(
    () => interleaveUserMessages(state.blocks, initialPrompt, followUpUserMessages),
    [state.blocks, initialPrompt, followUpUserMessages],
  );
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll on new content.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [merged.length, state.totalInputTokens, state.totalOutputTokens]);

  // "Agent is thinking" indicator: we're running AND the most recent
  // visible block isn't a finalized assistant message (ie. agent is
  // mid-tool-call, mid-thinking, or hasn't started replying yet).
  const showWorkingDot =
    status === 'running' &&
    !merged.some(
      (b, i) =>
        i === merged.length - 1 && b.kind === 'assistant' && b.finalized,
    );

  return (
    <div
      ref={scrollRef}
      className="flex-1 min-h-0 overflow-y-auto px-4 py-4 space-y-4 bg-gradient-to-b from-ide-bg to-ide-deep/30"
    >
      {merged.map((b) => (
        <BlockRenderer
          key={b.id}
          block={b}
          onAcceptSuggestion={onAcceptSuggestion}
          onDismissSuggestion={onDismissSuggestion}
        />
      ))}
      {showWorkingDot && <WorkingIndicator />}
      {(state.totalInputTokens > 0 || state.totalOutputTokens > 0) && (
        <div className="text-[10px] text-ide-textDim text-center pt-2 font-mono tracking-wider">
          {state.totalInputTokens.toLocaleString()} in · {state.totalOutputTokens.toLocaleString()} out
        </div>
      )}
    </div>
  );
}

function BlockRenderer({
  block,
  onAcceptSuggestion,
  onDismissSuggestion,
}: {
  block: Block;
  onAcceptSuggestion?: (id: string, text: string) => void;
  onDismissSuggestion?: (id: string) => void;
}): JSX.Element | null {
  switch (block.kind) {
    case 'user':
      return <UserBubble text={block.text} />;
    case 'assistant':
      return <AssistantBubbleView block={block} />;
    case 'thinking':
      return <CollapsibleBlock title="Thinking" body={block.text} muted />;
    case 'tool':
      return <ToolCard block={block} />;
    case 'file_edit':
      return <FileEditCard block={block} />;
    case 'suggestion':
      return (
        <SuggestionCard
          block={block}
          onAccept={onAcceptSuggestion}
          onDismiss={onDismissSuggestion}
        />
      );
    case 'turn_end':
      return null;
    case 'error':
      return <ErrorCard block={block} />;
    default:
      return null;
  }
}

function UserBubble({ text }: { text: string }): JSX.Element {
  return (
    <div className="flex justify-end animate-fadeIn">
      <div className="group max-w-[78%]">
        <div className="bg-gradient-to-br from-ide-accent to-ide-accentHover text-white text-sm px-4 py-2.5 rounded-2xl rounded-br-md shadow-sm whitespace-pre-wrap break-words leading-relaxed">
          {text}
        </div>
        <div className="text-[10px] text-ide-textDim text-right mt-1 pr-1 opacity-0 group-hover:opacity-100 transition-opacity">
          you
        </div>
      </div>
    </div>
  );
}

function AssistantBubbleView({ block }: { block: AssistantBlock }): JSX.Element {
  // Typewriter: while the block is mid-stream, reveal at a steady cadence
  // even when deltas arrive in clumps. When finalized, snap to the full
  // canonical text (no point typing-out the rest if Anthropic dumped a
  // 2 KB chunk at the end of the turn).
  const visibleText = useTypewriter(block.text, block.finalized);
  return (
    <div className="flex justify-start animate-fadeIn">
      <div className="flex gap-2.5 max-w-[88%]">
        <Avatar />
        <div className="group flex-1 min-w-0">
          <div className="bg-ide-deep/60 backdrop-blur-sm border border-ide-borderSoft/60 text-ide-text text-[13.5px] px-4 py-2.5 rounded-2xl rounded-tl-md shadow-sm break-words leading-relaxed">
            <MarkdownContent text={visibleText} />
            {!block.finalized && (
              <span className="ml-0.5 inline-block w-1.5 h-3 bg-ide-textBright/70 align-middle animate-pulse" />
            )}
          </div>
          <div className="text-[10px] text-ide-textDim mt-1 pl-1 opacity-0 group-hover:opacity-100 transition-opacity">
            agent
          </div>
        </div>
      </div>
    </div>
  );
}

/** Reveal characters at ~120/s, smoothing out chunky delta arrivals.
 *  Speeds up if we're falling behind so the visible cursor never lags
 *  more than ~600ms behind the actual stream. Snaps to full on finalize. */
function useTypewriter(target: string, finalized: boolean): string {
  const [shown, setShown] = useState('');
  const targetRef = useRef('');
  const shownRef = useRef('');
  const rafRef = useRef<number | null>(null);
  const lastTickRef = useRef<number>(0);

  // Update target without triggering a render-loop. Visible state
  // updates happen inside the rAF tick.
  targetRef.current = target;

  useEffect(() => {
    if (finalized) {
      // End of turn — snap to full text. Cancels any in-flight ticking.
      shownRef.current = target;
      setShown(target);
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      return;
    }
    if (rafRef.current !== null) return; // already ticking
    const tick = (t: number) => {
      const last = lastTickRef.current || t;
      const dt = t - last;
      lastTickRef.current = t;
      const tgt = targetRef.current;
      let cur = shownRef.current;
      if (cur.length < tgt.length) {
        // Base rate: 120 chars/s. Catch-up: scale by how far behind we are.
        const lag = tgt.length - cur.length;
        const cps = 120 + lag * 4; // up to several thousand cps if very far behind
        const advance = Math.max(1, Math.floor((cps * dt) / 1000));
        const next = Math.min(tgt.length, cur.length + advance);
        cur = tgt.slice(0, next);
        shownRef.current = cur;
        setShown(cur);
      }
      rafRef.current = cur.length < tgt.length ? requestAnimationFrame(tick) : null;
      if (rafRef.current === null) lastTickRef.current = 0;
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [target, finalized]);

  // Reset when block resets (id changes — i.e., a fresh turn).
  // Detect via a falling target length (full text shorter than what
  // we've shown) and re-prime.
  useEffect(() => {
    if (target.length < shownRef.current.length) {
      shownRef.current = target;
      setShown(target);
    }
  }, [target]);

  return shown;
}

function MarkdownContent({ text }: { text: string }): JSX.Element {
  return (
    <div className="prose-chat">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          // Headings — softer than default browser h1-h3 sizes; agent
          // replies are conversational, not document-level.
          h1: ({ children }) => (
            <h3 className="text-[15px] font-semibold text-ide-textBright mt-3 mb-1.5 first:mt-0">
              {children}
            </h3>
          ),
          h2: ({ children }) => (
            <h4 className="text-[14px] font-semibold text-ide-textBright mt-3 mb-1.5 first:mt-0">
              {children}
            </h4>
          ),
          h3: ({ children }) => (
            <h5 className="text-[13.5px] font-semibold text-ide-textBright mt-2.5 mb-1 first:mt-0">
              {children}
            </h5>
          ),
          h4: ({ children }) => (
            <h6 className="text-[13px] font-semibold text-ide-textBright mt-2 mb-1 first:mt-0">
              {children}
            </h6>
          ),
          p: ({ children }) => (
            <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>
          ),
          ul: ({ children }) => (
            <ul className="list-disc pl-5 my-1.5 space-y-0.5 marker:text-ide-textDim">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-5 my-1.5 space-y-0.5 marker:text-ide-textDim">
              {children}
            </ol>
          ),
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          strong: ({ children }) => (
            <strong className="font-semibold text-ide-textBright">
              {children}
            </strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="text-ide-accent hover:underline"
            >
              {children}
            </a>
          ),
          hr: () => <hr className="my-3 border-ide-borderSoft/60" />,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-ide-borderSoft pl-3 my-2 text-ide-textMuted italic">
              {children}
            </blockquote>
          ),
          // react-markdown 10 dropped the `inline` boolean. Rule of
          // thumb: a code block always sits inside a `<pre>`; inline
          // code does not. So the `code` component renders inline-style
          // (no extra wrapper), and `pre` renders the block container —
          // pulling the inner <code>'s text out so we control the
          // padding/scroll on the wrapper.
          code: ({ children, className, ...props }) => (
            <code
              className={
                'bg-ide-deep border border-ide-borderSoft/60 rounded px-1 py-0.5 text-[12.5px] font-mono text-ide-textBright ' +
                (className ?? '')
              }
              {...props}
            >
              {children}
            </code>
          ),
          pre: ({ children }) => (
            <pre className="bg-ide-deep border border-ide-borderSoft/60 rounded-lg p-3 my-2 overflow-x-auto text-[12.5px] font-mono leading-snug text-ide-text [&>code]:bg-transparent [&>code]:border-0 [&>code]:p-0">
              {children}
            </pre>
          ),
          table: ({ children }) => (
            <div className="my-2 overflow-x-auto rounded-lg border border-ide-borderSoft/60">
              <table className="w-full text-[12.5px]">{children}</table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-ide-deep/60">{children}</thead>
          ),
          th: ({ children }) => (
            <th className="px-3 py-1.5 text-left font-semibold text-ide-textBright border-b border-ide-borderSoft/60">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-3 py-1.5 border-b border-ide-borderSoft/40 last:border-b-0">
              {children}
            </td>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function Avatar(): JSX.Element {
  return (
    <div className="flex-shrink-0 w-7 h-7 rounded-full bg-gradient-to-br from-ide-accent/80 to-ide-accentHover/80 flex items-center justify-center text-[10px] font-semibold text-white tracking-wider mt-0.5">
      A
    </div>
  );
}

function WorkingIndicator(): JSX.Element {
  return (
    <div className="flex justify-start animate-fadeIn">
      <div className="flex gap-2.5">
        <Avatar />
        <div className="bg-ide-deep/60 border border-ide-borderSoft/60 px-4 py-3 rounded-2xl rounded-tl-md flex items-center gap-1">
          <span className="w-1.5 h-1.5 bg-ide-textMuted rounded-full animate-bounce [animation-delay:0ms]" />
          <span className="w-1.5 h-1.5 bg-ide-textMuted rounded-full animate-bounce [animation-delay:120ms]" />
          <span className="w-1.5 h-1.5 bg-ide-textMuted rounded-full animate-bounce [animation-delay:240ms]" />
        </div>
      </div>
    </div>
  );
}

function CollapsibleBlock({
  title,
  body,
  muted,
}: {
  title: string;
  body: string;
  muted?: boolean;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  // Collapsed = single tight line under the avatar column. Looks like
  // a small inline status pill rather than a card so it doesn't compete
  // with the agent's text.
  return (
    <div className="ml-9">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-ide-deep/40 border border-ide-borderSoft/40 text-[10px] uppercase tracking-wider text-ide-textMuted hover:text-ide-textBright hover:border-ide-borderSoft transition-colors"
      >
        <span className="w-1 h-1 rounded-full bg-ide-textDim" />
        <span>{title}</span>
        <span className={`text-ide-textDim transition-transform ${open ? 'rotate-90' : ''}`}>›</span>
      </button>
      {open && (
        <pre
          className={`mt-1 px-3 py-2 rounded-lg bg-ide-deep/40 border border-ide-borderSoft/40 text-xs whitespace-pre-wrap break-words ${
            muted ? 'text-ide-textMuted italic' : 'text-ide-text'
          }`}
        >
          {body}
        </pre>
      )}
    </div>
  );
}

function ToolCard({ block }: { block: ToolBlock }): JSX.Element {
  const [open, setOpen] = useState(false);
  const argsJson = JSON.stringify(block.args, null, 2);
  const isError = block.result?.isError ?? false;
  const running = !block.result;
  const argsSummary = useMemo(() => {
    const first = Object.entries(block.args)[0];
    if (!first) return '';
    const [k, v] = first;
    const vs = typeof v === 'string' ? v : JSON.stringify(v);
    return `${k}: ${vs}`;
  }, [block.args]);
  return (
    <div className="ml-9">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10.5px] tracking-wide transition-colors ${
          isError
            ? 'border-ide-danger/60 bg-ide-deep/40 text-ide-danger'
            : 'border-ide-borderSoft/40 bg-ide-deep/40 text-ide-textMuted hover:text-ide-textBright hover:border-ide-borderSoft'
        }`}
      >
        <span
          className={`w-1 h-1 rounded-full ${
            running
              ? 'bg-ide-warn animate-pulse'
              : isError
                ? 'bg-ide-danger'
                : 'bg-ide-ok'
          }`}
        />
        <span className="font-mono">{block.toolName}</span>
        {argsSummary && (
          <span className="font-mono text-ide-textDim truncate max-w-[220px]">
            {argsSummary}
          </span>
        )}
        {running && <span className="italic text-ide-textDim">…</span>}
        <span className={`text-ide-textDim transition-transform ${open ? 'rotate-90' : ''}`}>›</span>
      </button>
      {open && (
        <div className="mt-1 px-3 py-2 rounded-lg bg-ide-deep/40 border border-ide-borderSoft/40 text-xs space-y-2">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-ide-textMuted mb-1">
              args
            </div>
            <pre className="text-ide-text whitespace-pre-wrap break-words font-mono">
              {argsJson}
            </pre>
          </div>
          {block.result && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-ide-textMuted mb-1">
                result
              </div>
              <pre
                className={`whitespace-pre-wrap break-words font-mono ${
                  isError ? 'text-ide-danger' : 'text-ide-text'
                }`}
              >
                {block.result.text || '(no output)'}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FileEditCard({ block }: { block: FileEditBlock }): JSX.Element {
  return (
    <div className="ml-9 rounded-xl border border-ide-ok/40 bg-ide-deep/40 px-3 py-2 text-xs flex items-center gap-2.5">
      <span className="w-1.5 h-1.5 rounded-full bg-ide-ok flex-shrink-0" />
      <span className="font-mono text-ide-textBright truncate flex-1">
        {block.path}
      </span>
      <span className="text-ide-textDim font-mono">{block.summary || 'edited'}</span>
    </div>
  );
}

function ErrorCard({ block }: { block: ErrorBlock }): JSX.Element {
  return (
    <div className="ml-9 rounded-xl border border-ide-danger/60 bg-ide-danger/5 px-3 py-2 text-xs">
      <div className="flex items-center gap-1.5 text-ide-danger font-mono mb-0.5">
        <span className="w-1.5 h-1.5 rounded-full bg-ide-danger" />
        {block.errorKind}
      </div>
      <div className="text-ide-text break-words">{block.message}</div>
    </div>
  );
}

function SuggestionCard({
  block,
  onAccept,
  onDismiss,
}: {
  block: SuggestionBlock;
  onAccept?: (id: string, text: string) => void;
  onDismiss?: (id: string) => void;
}): JSX.Element {
  const [secondsLeft, setSecondsLeft] = useState<number>(() =>
    secondsUntil(block.overrideDeadlineAt),
  );

  useEffect(() => {
    const tick = () => setSecondsLeft(secondsUntil(block.overrideDeadlineAt));
    tick();
    const t = window.setInterval(tick, 250);
    return () => window.clearInterval(t);
  }, [block.overrideDeadlineAt]);

  const expired = secondsLeft <= 0;

  return (
    <div className="ml-9 rounded-xl border border-ide-warn/60 bg-ide-warn/5 px-4 py-3 text-xs space-y-2">
      <div className="text-ide-warn font-medium flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-ide-warn" />
        User agent suggested a reply
        {!expired && (
          <span className="text-ide-textDim font-mono">
            · auto-sending in {secondsLeft}s
          </span>
        )}
        {expired && <span className="text-ide-textDim">· sent</span>}
      </div>
      <div className="text-ide-text whitespace-pre-wrap break-words">
        {block.suggestedReply}
      </div>
      {block.reason && (
        <div className="text-[11px] text-ide-textDim italic">
          why: {block.reason}
        </div>
      )}
      {!expired && (
        <div className="flex gap-2 pt-1">
          <button
            type="button"
            onClick={() => onAccept?.(block.suggestionId, block.suggestedReply)}
            className="px-3 py-1 bg-ide-accent text-white rounded-md text-[11px] font-medium hover:bg-ide-accentHover transition-colors"
          >
            Send now
          </button>
          <button
            type="button"
            onClick={() => onDismiss?.(block.suggestionId)}
            className="px-3 py-1 text-ide-textMuted hover:text-ide-textBright text-[11px] transition-colors"
          >
            Override
          </button>
        </div>
      )}
    </div>
  );
}

function secondsUntil(iso: string): number {
  if (!iso) return 0;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 0;
  return Math.max(0, Math.ceil((t - Date.now()) / 1000));
}
