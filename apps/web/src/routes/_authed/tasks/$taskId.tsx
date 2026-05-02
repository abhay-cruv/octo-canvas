import { useState } from 'react';
import { createFileRoute } from '@tanstack/react-router';
import { useTaskStream } from '../../../hooks/useTaskStream';

export const Route = createFileRoute('/_authed/tasks/$taskId')({
  component: TaskDebugPage,
});

function TaskDebugPage() {
  const { taskId } = Route.useParams();
  const { events, status, lastSeq, forceDisconnect } = useTaskStream(taskId);
  const [injecting, setInjecting] = useState(false);
  const [injectError, setInjectError] = useState<string | null>(null);

  const inject = async () => {
    setInjecting(true);
    setInjectError(null);
    try {
      const baseUrl = import.meta.env.VITE_ORCHESTRATOR_BASE_URL ?? '';
      const res = await fetch(`${baseUrl}/api/_internal/tasks/${taskId}/events`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ message: `hello at ${new Date().toISOString()}` }),
      });
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    } catch (err) {
      setInjectError(err instanceof Error ? err.message : String(err));
    } finally {
      setInjecting(false);
    }
  };

  return (
    <div style={{ padding: 24, fontFamily: 'monospace' }}>
      <h1 style={{ fontSize: 18, marginBottom: 12 }}>Task stream debug</h1>
      <div style={{ marginBottom: 12 }}>
        <strong>task_id:</strong> {taskId}
        {' · '}
        <strong>status:</strong> {status}
        {' · '}
        <strong>last_seq:</strong> {lastSeq}
      </div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button type="button" onClick={inject} disabled={injecting}>
          {injecting ? 'Injecting...' : 'Inject event'}
        </button>
        <button type="button" onClick={forceDisconnect}>
          Force disconnect
        </button>
      </div>
      {injectError && (
        <div style={{ color: 'red', marginBottom: 12 }}>Inject failed: {injectError}</div>
      )}
      <div
        style={{
          border: '1px solid #ccc',
          background: '#fafafa',
          padding: 8,
          maxHeight: '60vh',
          overflowY: 'auto',
        }}
      >
        {events.length === 0 ? (
          <em>(no events yet)</em>
        ) : (
          events.map((ev, i) => (
            <pre key={i} style={{ margin: 0, padding: '2px 0' }}>
              {JSON.stringify(ev)}
            </pre>
          ))
        )}
      </div>
    </div>
  );
}

