import { useEffect, useRef, useState } from 'react';
import type { OrchestratorToWeb, WebToOrchestrator } from '../lib/wire';

export type StreamStatus = 'connecting' | 'live' | 'reconnecting' | 'closed';

export interface UseTaskStreamResult {
  events: OrchestratorToWeb[];
  status: StreamStatus;
  lastSeq: number;
  forceDisconnect: () => void;
}

const HEARTBEAT_TIMEOUT_MS = 90_000;
const BASE_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 16_000;

function jitter(ms: number): number {
  return ms * (0.75 + Math.random() * 0.5);
}

function wsUrlFor(taskId: string): string {
  const httpBase = import.meta.env.VITE_ORCHESTRATOR_BASE_URL ?? '';
  // http(s):// → ws(s)://
  const wsBase = httpBase.replace(/^http/, 'ws');
  return `${wsBase}/ws/web/tasks/${taskId}`;
}

export function useTaskStream(taskId: string | undefined): UseTaskStreamResult {
  const [events, setEvents] = useState<OrchestratorToWeb[]>([]);
  const [status, setStatus] = useState<StreamStatus>('connecting');
  const [lastSeq, setLastSeq] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const closedByUserRef = useRef(false);
  const lastSeqRef = useRef(0);
  const backoffRef = useRef(BASE_BACKOFF_MS);

  useEffect(() => {
    if (!taskId) return;
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

    const send = (cmd: WebToOrchestrator) => {
      wsRef.current?.send(JSON.stringify(cmd));
    };

    const connect = () => {
      setStatus((s) => (s === 'closed' ? s : 'connecting'));
      const ws = new WebSocket(wsUrlFor(taskId));
      wsRef.current = ws;

      ws.addEventListener('open', () => {
        backoffRef.current = BASE_BACKOFF_MS;
        send({ type: 'resume', after_seq: lastSeqRef.current });
        setStatus('live');
        armRxWatchdog();
      });

      ws.addEventListener('message', (e) => {
        armRxWatchdog();
        let msg: OrchestratorToWeb;
        try {
          msg = JSON.parse(e.data) as OrchestratorToWeb;
        } catch {
          return;
        }
        // Heartbeat: server-initiated ping → reply pong; type-narrow on `type`.
        if ('type' in msg && msg.type === 'ping') {
          const nonce = (msg as { nonce?: string }).nonce ?? '';
          send({ type: 'pong', nonce });
          return;
        }
        if ('type' in msg && msg.type === 'pong') return;
        const seqVal = (msg as { seq?: number }).seq;
        if (typeof seqVal === 'number' && seqVal > lastSeqRef.current) {
          lastSeqRef.current = seqVal;
          setLastSeq(seqVal);
        }
        setEvents((prev) => [...prev, msg]);
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
        // close handler will run; let it own the reconnect path.
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
  }, [taskId]);

  const forceDisconnect = () => {
    // Close without unsetting `closedByUserRef` so the reconnect loop runs —
    // this is the "test the reconnect path" affordance.
    wsRef.current?.close(4000, 'forced');
  };

  return { events, status, lastSeq, forceDisconnect };
}
