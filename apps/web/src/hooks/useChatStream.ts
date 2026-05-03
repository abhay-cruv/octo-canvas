/**
 * Live `BridgeToOrchestrator` event stream over `/ws/web/chats/{chat_id}`.
 *
 * Mirror of `useTaskStream` for slice-8 chat-keyed events. Same
 * heartbeat + jittered-reconnect + Resume{after_seq} replay shape.
 */

import { useEffect, useRef, useState } from 'react';

// We deliberately keep the event type loose here — `BridgeToOrchestrator`
// is generated into wire.d.ts but per-event field shapes are stable
// enough to type at the consumer level (transcript renderer narrows on
// `type` discriminators).
export type ChatStreamEvent = { type: string; chat_id?: string; seq?: number } & Record<
  string,
  unknown
>;

export type ChatStreamStatus = 'connecting' | 'live' | 'reconnecting' | 'closed';

export interface UseChatStreamResult {
  events: ChatStreamEvent[];
  status: ChatStreamStatus;
  lastSeq: number;
  forceDisconnect: () => void;
}

const HEARTBEAT_TIMEOUT_MS = 90_000;
const BASE_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 16_000;

function jitter(ms: number): number {
  return ms * (0.75 + Math.random() * 0.5);
}

function wsUrlFor(chatId: string): string {
  const httpBase = import.meta.env.VITE_ORCHESTRATOR_BASE_URL ?? '';
  const wsBase = httpBase.replace(/^http/, 'ws');
  return `${wsBase}/ws/web/chats/${chatId}`;
}

export function useChatStream(chatId: string | undefined): UseChatStreamResult {
  const [events, setEvents] = useState<ChatStreamEvent[]>([]);
  const [status, setStatus] = useState<ChatStreamStatus>('connecting');
  const [lastSeq, setLastSeq] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const closedByUserRef = useRef(false);
  const lastSeqRef = useRef(0);
  const backoffRef = useRef(BASE_BACKOFF_MS);

  useEffect(() => {
    if (!chatId) return;
    closedByUserRef.current = false;
    lastSeqRef.current = 0;
    setEvents([]);
    setLastSeq(0);

    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let rxWatchdog: ReturnType<typeof setTimeout> | null = null;

    const armRxWatchdog = () => {
      if (rxWatchdog) clearTimeout(rxWatchdog);
      rxWatchdog = setTimeout(() => {
        wsRef.current?.close(4000, 'rx_timeout');
      }, HEARTBEAT_TIMEOUT_MS);
    };

    const sendCmd = (cmd: object) => {
      wsRef.current?.send(JSON.stringify(cmd));
    };

    const connect = () => {
      setStatus((s) => (s === 'closed' ? s : 'connecting'));
      const ws = new WebSocket(wsUrlFor(chatId));
      wsRef.current = ws;

      ws.addEventListener('open', () => {
        backoffRef.current = BASE_BACKOFF_MS;
        sendCmd({ type: 'resume', after_seq: lastSeqRef.current });
        setStatus('live');
        armRxWatchdog();
      });

      ws.addEventListener('message', (e) => {
        armRxWatchdog();
        let msg: ChatStreamEvent;
        try {
          msg = JSON.parse(e.data) as ChatStreamEvent;
        } catch {
          return;
        }
        // Heartbeat plumbing — slice-5a's `ping` / `pong` events
        // travel on this same socket alongside bridge frames.
        if (msg.type === 'ping') {
          const nonce = (msg as { nonce?: string }).nonce ?? '';
          sendCmd({ type: 'pong', nonce });
          return;
        }
        if (msg.type === 'pong') return;
        const seqVal = msg.seq;
        if (typeof seqVal === 'number' && seqVal > lastSeqRef.current) {
          lastSeqRef.current = seqVal;
          setLastSeq(seqVal);
        }
        // De-dup: events get a stable key based on type + seq +
        // claude_session_id (the orchestrator allocates seq per
        // (chat, session) so the same seq can repeat across sessions).
        // React StrictMode in dev opens two WebSockets which would
        // otherwise produce two copies of every event.
        setEvents((prev) => {
          const sessId =
            (msg as { claude_session_id?: string | null }).claude_session_id ?? '';
          const key = `${msg.type}|${seqVal ?? 'nil'}|${sessId}`;
          for (const e of prev) {
            const eSess =
              (e as { claude_session_id?: string | null }).claude_session_id ?? '';
            if (`${e.type}|${e.seq ?? 'nil'}|${eSess}` === key) return prev;
          }
          return [...prev, msg];
        });
      });

      ws.addEventListener('close', () => {
        if (rxWatchdog) clearTimeout(rxWatchdog);
        if (closedByUserRef.current) {
          setStatus('closed');
          return;
        }
        setStatus('reconnecting');
        const delay = jitter(backoffRef.current);
        backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF_MS);
        reconnectTimer = setTimeout(connect, delay);
      });

      ws.addEventListener('error', () => {
        // close handler runs; let it own the reconnect path.
      });
    };

    connect();

    return () => {
      closedByUserRef.current = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (rxWatchdog) clearTimeout(rxWatchdog);
      wsRef.current?.close(1000, 'unmount');
      wsRef.current = null;
    };
  }, [chatId]);

  const forceDisconnect = () => {
    wsRef.current?.close(4000, 'force_disconnect');
  };

  return { events, status, lastSeq, forceDisconnect };
}
