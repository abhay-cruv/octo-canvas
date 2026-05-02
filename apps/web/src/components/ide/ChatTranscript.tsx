/**
 * ChatTranscript — slice 8 Phase 8b.
 *
 * Renders a unified merged transcript of:
 *  - the original user prompt (chat header above this component)
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
 * Streaming `assistant.delta` events are folded into the most recent
 * live assistant block until the matching `assistant.message` arrives;
 * then the live block is replaced by the final canonical block.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { ChatStreamEvent } from '../../hooks/useChatStream';

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

interface ResultBlock {
  kind: 'result';
  id: string;
  isError: boolean;
  durationMs: number;
}

type Block =
  | AssistantBlock
  | ThinkingBlockItem
  | ToolBlock
  | FileEditBlock
  | SuggestionBlock
  | ErrorBlock
  | ResultBlock;

interface ReducedState {
  blocks: Block[];
  // Tracking the in-flight assistant block per turn (we close it on
  // assistant.message and start a fresh one on next assistant.delta).
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
      // Replace the live block with the finalized text (the SDK emits
      // the same content as a single canonical block at turn close).
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
      return {
        ...state,
        blocks: [
          ...state.blocks,
          {
            kind: 'result',
            id,
            isError: Boolean(ev.is_error),
            durationMs: (ev.duration_ms as number) ?? 0,
          },
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

interface ChatTranscriptProps {
  initialPrompt: string;
  events: ChatStreamEvent[];
  onAcceptSuggestion?: (suggestionId: string, text: string) => void;
  onDismissSuggestion?: (suggestionId: string) => void;
}

export function ChatTranscript({
  initialPrompt,
  events,
  onAcceptSuggestion,
  onDismissSuggestion,
}: ChatTranscriptProps): JSX.Element {
  const state = useMemo(() => reduceEvents(events), [events]);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll on new content.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [state.blocks.length, state.totalInputTokens, state.totalOutputTokens]);

  return (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
      <UserBubble>{initialPrompt}</UserBubble>
      {state.blocks.map((b) => (
        <BlockRenderer
          key={b.id}
          block={b}
          onAcceptSuggestion={onAcceptSuggestion}
          onDismissSuggestion={onDismissSuggestion}
        />
      ))}
      {(state.totalInputTokens > 0 || state.totalOutputTokens > 0) && (
        <div className="text-[11px] text-ide-textDim text-center pt-1">
          tokens: in {state.totalInputTokens} / out {state.totalOutputTokens}
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
    case 'result':
      // No-op visually — token chips already surface usage; result
      // arrival just signals end-of-turn.
      return null;
    case 'error':
      return <ErrorCard block={block} />;
    default:
      return null;
  }
}

function UserBubble({ children }: { children: React.ReactNode }): JSX.Element {
  return (
    <div className="flex justify-end">
      <div className="bg-ide-accent text-ide-textBright text-sm px-3 py-2 rounded max-w-[85%] whitespace-pre-wrap break-words">
        {children}
      </div>
    </div>
  );
}

function AssistantBubbleView({ block }: { block: AssistantBlock }): JSX.Element {
  const indicator = block.finalized ? null : (
    <span className="ml-1 text-ide-textDim animate-pulse">▋</span>
  );
  return (
    <div className="flex justify-start">
      <div className="bg-ide-deep text-ide-textBright text-sm px-3 py-2 rounded max-w-[85%] whitespace-pre-wrap break-words">
        {block.text}
        {indicator}
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
  return (
    <div className="rounded border border-ide-borderSoft bg-ide-deep overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-2.5 py-1.5 text-[11px] uppercase tracking-wider text-ide-textMuted hover:bg-ide-bg flex items-center justify-between"
      >
        <span>{title}</span>
        <span className="text-ide-textDim">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <pre
          className={`px-2.5 py-2 text-xs whitespace-pre-wrap break-words ${
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
  return (
    <div
      className={`rounded border overflow-hidden ${
        isError ? 'border-ide-danger bg-ide-deep' : 'border-ide-borderSoft bg-ide-deep'
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full text-left px-2.5 py-1.5 text-xs hover:bg-ide-bg flex items-center justify-between"
      >
        <span className="font-mono text-ide-textBright">
          {block.toolName}
          {!block.result && (
            <span className="ml-2 text-ide-textDim">running…</span>
          )}
          {block.result && isError && (
            <span className="ml-2 text-ide-danger">error</span>
          )}
        </span>
        <span className="text-ide-textDim">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <div className="px-2.5 py-2 text-xs space-y-2">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-ide-textMuted mb-0.5">
              args
            </div>
            <pre className="text-ide-text whitespace-pre-wrap break-words">
              {argsJson}
            </pre>
          </div>
          {block.result && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-ide-textMuted mb-0.5">
                result
              </div>
              <pre
                className={`whitespace-pre-wrap break-words ${
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
    <div className="rounded border border-ide-borderSoft bg-ide-deep px-2.5 py-1.5 text-xs flex items-center gap-2">
      <span className="text-ide-ok">●</span>
      <span className="font-mono text-ide-textBright truncate flex-1">
        {block.path}
      </span>
      <span className="text-ide-textDim">{block.summary || 'edited'}</span>
    </div>
  );
}

function ErrorCard({ block }: { block: ErrorBlock }): JSX.Element {
  return (
    <div className="rounded border border-ide-danger bg-ide-deep px-2.5 py-1.5 text-xs">
      <div className="text-ide-danger font-mono">{block.errorKind}</div>
      <div className="text-ide-text mt-0.5 break-words">{block.message}</div>
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
    <div className="rounded border border-ide-warn bg-ide-deep px-3 py-2 text-xs space-y-2">
      <div className="text-ide-warn font-medium">
        User agent suggested a reply{' '}
        {!expired && (
          <span className="text-ide-textDim">
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
            onClick={() =>
              onAccept?.(block.suggestionId, block.suggestedReply)
            }
            className="px-2 py-0.5 bg-ide-accent text-ide-textBright rounded text-[11px] hover:bg-ide-accentHover"
          >
            Send now
          </button>
          <button
            type="button"
            onClick={() => onDismiss?.(block.suggestionId)}
            className="px-2 py-0.5 text-ide-textMuted hover:text-ide-textBright text-[11px]"
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
