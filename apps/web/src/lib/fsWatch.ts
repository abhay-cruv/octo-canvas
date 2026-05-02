/**
 * Subscribes to `/ws/web/sandboxes/{id}/fs/watch` and dispatches
 * `FileEditEvent`s to a callback. Auto-reconnects with backoff.
 */

import type { FileEditEvent, FsWatchToWeb } from '@octo-canvas/api-types';

const baseUrl = import.meta.env.VITE_ORCHESTRATOR_BASE_URL as string;

function wsUrl(sandboxId: string): string {
  const u = new URL(baseUrl);
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
  u.pathname = `/ws/web/sandboxes/${sandboxId}/fs/watch`;
  return u.toString();
}

export function openFsWatch(
  sandboxId: string,
  onEvent: (ev: FileEditEvent) => void,
): () => void {
  let closed = false;
  let ws: WebSocket | null = null;
  let backoff = 250;

  const connect = () => {
    if (closed) return;
    ws = new WebSocket(wsUrl(sandboxId));
    ws.onopen = () => {
      backoff = 250;
    };
    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data as string) as FsWatchToWeb;
        if (data.type === 'file.edit') onEvent(data);
      } catch {
        // ignore malformed
      }
    };
    ws.onclose = () => {
      if (closed) return;
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 8000);
    };
    ws.onerror = () => {
      // onclose will fire next.
    };
  };

  connect();
  return () => {
    closed = true;
    ws?.close();
  };
}
