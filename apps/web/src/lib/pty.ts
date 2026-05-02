/**
 * Thin wrapper around `/ws/web/sandboxes/{id}/pty/{terminal_id}`. The
 * upstream channel speaks raw binary frames (xterm bytes both ways) plus
 * JSON resize/close messages. We expose `send(bytes)`, `resize(cols, rows)`,
 * `close()`, plus an `onBytes`/`onSessionInfo`/`onExit`/`onReconnect`
 * callback surface.
 *
 * Auto-reconnect: on transport-level close (network blip, browser
 * background timeout) we reconnect with exponential backoff. The Redis-
 * backed reattach in the orchestrator pairs us back to the same Sprites
 * session so scrollback survives. We do NOT reconnect after `pty.exit`
 * (real shell exit) — that's the user's signal that the session is done.
 */

import type { PtyExit, PtySessionInfo } from '@octo-canvas/api-types';

const baseUrl = import.meta.env.VITE_ORCHESTRATOR_BASE_URL as string;

function ptyUrl(sandboxId: string, terminalId: string): string {
  const u = new URL(baseUrl);
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:';
  u.pathname = `/ws/web/sandboxes/${sandboxId}/pty/${terminalId}`;
  return u.toString();
}

export type PtyHandle = {
  send(bytes: Uint8Array): void;
  resize(cols: number, rows: number): void;
  close(): void;
};

export type PtyCallbacks = {
  onBytes?: (b: Uint8Array) => void;
  onSessionInfo?: (info: PtySessionInfo) => void;
  onExit?: (info: PtyExit) => void;
  /** Transport-level disconnect (about to retry). Set `permanent` when
   * we won't try again — e.g. a real `pty.exit` happened or `close()` was
   * called by the consumer. */
  onClose?: (code: number, permanent: boolean) => void;
  /** Called every time the WS reconnects (after the first connect). The
   * consumer should re-send terminal dimensions via `resize`. */
  onReconnect?: () => void;
};

export function openPty(
  sandboxId: string,
  terminalId: string,
  cb: PtyCallbacks,
): PtyHandle {
  let ws: WebSocket | null = null;
  let closed = false;
  let sessionExited = false;
  let backoff = 250;
  let lastResize: { cols: number; rows: number } | null = null;
  let connectCount = 0;
  // Buffer frames sent before the WS finishes opening — flushed on `open`.
  const pending: (Uint8Array | string)[] = [];

  const sendRaw = (item: Uint8Array | string): void => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    if (typeof item === 'string') ws.send(item);
    else ws.send(item.buffer.slice(item.byteOffset, item.byteOffset + item.byteLength) as ArrayBuffer);
  };

  const flush = () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    while (pending.length > 0) {
      const item = pending.shift();
      if (item === undefined) break;
      sendRaw(item);
    }
  };

  const connect = () => {
    if (closed) return;
    ws = new WebSocket(ptyUrl(sandboxId, terminalId));
    ws.binaryType = 'arraybuffer';
    ws.onopen = () => {
      backoff = 250;
      connectCount += 1;
      if (connectCount > 1) {
        cb.onReconnect?.();
        // Re-send last known dimensions so the upstream PTY matches the
        // current xterm size after reattach.
        if (lastResize && ws && ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({
              type: 'pty.resize',
              cols: lastResize.cols,
              rows: lastResize.rows,
            }),
          );
        }
      }
      flush();
    };
    ws.onmessage = (msg) => {
      if (typeof msg.data === 'string') {
        try {
          const obj = JSON.parse(msg.data) as { type: string };
          if (obj.type === 'pty.session_info' && cb.onSessionInfo) {
            cb.onSessionInfo(obj as unknown as PtySessionInfo);
          } else if (obj.type === 'pty.exit' && cb.onExit) {
            sessionExited = true;
            cb.onExit(obj as unknown as PtyExit);
          }
        } catch {
          // ignore non-JSON
        }
        return;
      }
      if (cb.onBytes) cb.onBytes(new Uint8Array(msg.data as ArrayBuffer));
    };
    ws.onclose = (ev) => {
      const permanent = closed || sessionExited;
      cb.onClose?.(ev.code, permanent);
      if (permanent) return;
      const delay = backoff;
      backoff = Math.min(backoff * 2, 8000);
      setTimeout(connect, delay);
    };
    ws.onerror = () => {
      // onclose will fire next; leave reconnect logic there.
    };
  };

  connect();

  return {
    send(bytes: Uint8Array): void {
      if (ws && ws.readyState === WebSocket.OPEN) {
        sendRaw(bytes);
      } else {
        // Buffer until `open` fires (caps to avoid memory blow-up).
        if (pending.length < 256) pending.push(bytes);
      }
    },
    resize(cols: number, rows: number): void {
      lastResize = { cols, rows };
      const frame = JSON.stringify({ type: 'pty.resize', cols, rows });
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(frame);
      } else {
        if (pending.length < 256) pending.push(frame);
      }
    },
    close(): void {
      closed = true;
      // Tell the broker we're closing intentionally so it can clear the
      // Redis reattach entry. Without this, the next reopen would
      // reattach to this same Sprites session — perpetuating any
      // wrong-cwd / wrong-cmd state from when it was created.
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ type: 'pty.close', terminal_id: terminalId }));
        } catch {
          // ignore — closing anyway
        }
      }
      ws?.close();
    },
  };
}
