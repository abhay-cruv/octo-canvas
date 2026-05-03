import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { sandboxesQueryOptions } from '../lib/queries';
import {
  destroySandbox,
  pauseSandbox,
  getOrCreateSandbox,
  refreshSandbox,
  resetSandbox,
  type SandboxResponse,
  SandboxStateError,
  wakeSandbox,
} from '../lib/sandbox';

const TRANSIENT: ReadonlyArray<SandboxResponse['status']> = [
  'provisioning',
  'resetting',
];

// Reconciler-emitted activity values → friendly UI strings. Anything
// unknown falls back to the raw activity name (forward-compatible with
// new phases the backend introduces).
const ACTIVITY_LABELS: Record<string, string> = {
  configuring_git: 'Setting up git…',
  installing_bridge: 'Installing agent toolchain…',
  installing_packages: 'Installing system packages…',
  installing_runtimes: 'Installing language runtimes…',
  installing_bridge_wheel: 'Installing agent runtime…',
  launching_bridge: 'Starting agent…',
  cloning: 'Cloning repository…',
  checkpointing: 'Snapshotting clean state…',
  pausing: 'Releasing compute (waiting for idle)…',
};

// Pretty-print any unknown activity slug ("foo_bar" → "Foo bar…") so a
// new backend phase reads naturally on the dashboard before someone
// adds it to the explicit map above.
function prettyActivity(activity: string): string {
  const explicit = ACTIVITY_LABELS[activity];
  if (explicit) return explicit;
  const spaced = activity.replace(/_/g, ' ').trim();
  if (!spaced) return activity;
  const first = spaced.charAt(0).toUpperCase();
  return `${first}${spaced.slice(1)}…`;
}

// Slice 8: green glowing "Agent ready" pill — shown when the bridge
// daemon is up, connected, and no setup activity is in flight.
function BridgeReadyPill({ version }: { version: string | null }): JSX.Element {
  return (
    <div className="text-xs px-2 py-1 rounded-md bg-green-50 border border-green-200 text-green-900 inline-flex items-center gap-1.5">
      <span className="relative inline-flex w-2 h-2">
        <span className="absolute inline-flex w-full h-full rounded-full bg-green-400 opacity-60 animate-ping" />
        <span className="relative inline-flex w-2 h-2 rounded-full bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.7)]" />
      </span>
      <span className="font-medium">Agent ready</span>
      {version ? (
        <span className="font-mono text-green-800/70">— bridge {version}</span>
      ) : null}
    </div>
  );
}

type DialogKind = 'reset' | 'destroy' | null;

export function SandboxPanel() {
  const queryClient = useQueryClient();
  // Burst-poll window: timestamp until which we poll fast regardless of
  // current state. Bumped on every mutation (Wake, Pause, Reset, etc.)
  // so the FE catches the next ~10s of state/activity transitions and
  // then stops polling once everything settles. Without this, polling
  // would either continue forever (annoying when nothing's happening)
  // or stop too early to catch activity flipping from null →
  // "configuring_git" a couple seconds after Wake.
  const burstUntilRef = useRef<number>(0);
  const sandboxes = useQuery({
    ...sandboxesQueryOptions,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const active = pickActive(data);
      if (!active) return false;
      // Fast poll while something is in flight OR we're inside the
      // post-mutation burst window.
      if (TRANSIENT.includes(active.status) || active.activity) return 2000;
      if (Date.now() < burstUntilRef.current) return 2000;
      // Stable state — no polling. The next user action will reopen
      // the burst window via `kickBurst`.
      return false;
    },
  });

  const active = pickActive(sandboxes.data);

  const kickBurst = (ms = 10_000) => {
    burstUntilRef.current = Date.now() + ms;
  };
  // Every sandbox-state mutation can mutate Repo rows server-side too
  // (provision binds orphans, wake retries failed, reset flips ready→
  // pending, destroy unbinds). Invalidate BOTH so the dashboard repo
  // cards refetch the new clone_status, not just the sandbox pill.
  const invalidateAll = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['sandboxes'] }),
      queryClient.invalidateQueries({ queryKey: ['repos', 'connected'] }),
    ]);
  const onSuccess = () => {
    kickBurst();
    return invalidateAll();
  };
  const onError = (err: unknown) => {
    if (err instanceof SandboxStateError) {
      void invalidateAll();
    }
  };

  const provisionMutation = useMutation({
    mutationFn: getOrCreateSandbox,
    onSuccess,
  });
  const wake = useMutation({ mutationFn: wakeSandbox, onSuccess, onError });
  const pause = useMutation({ mutationFn: pauseSandbox, onSuccess, onError });
  const refresh = useMutation({ mutationFn: refreshSandbox, onSuccess, onError });
  const reset = useMutation({ mutationFn: resetSandbox, onSuccess, onError });
  const destroy = useMutation({ mutationFn: destroySandbox, onSuccess, onError });

  const [dialog, setDialog] = useState<DialogKind>(null);

  if (sandboxes.isLoading) {
    return (
      <Card>
        <div className="text-sm text-gray-600">Loading sandbox…</div>
      </Card>
    );
  }

  if (!active) {
    return (
      <Card>
        <Header title="No sandbox yet" />
        <p className="text-sm text-gray-600">
          Provision a sandbox to clone repos and run agent tasks.
        </p>
        <button
          type="button"
          onClick={() => provisionMutation.mutate()}
          disabled={provisionMutation.isPending}
          className="mt-3 px-4 py-2 rounded-lg bg-black text-white text-sm font-medium hover:bg-gray-800 disabled:opacity-60"
        >
          {provisionMutation.isPending ? 'Provisioning…' : 'Provision sandbox'}
        </button>
      </Card>
    );
  }

  const labels = LABELS[active.status];
  const isAlive = !TRANSIENT.includes(active.status) && active.status !== 'failed';

  return (
    <Card>
      <Header
        title="Sandbox"
        pill={<StatusPill status={active.status} />}
      />
      <div className="text-sm text-gray-600 space-y-1">
        {active.activity ? (
          <div className="text-xs px-2 py-1 rounded-md bg-amber-50 border border-amber-200 text-amber-900 inline-flex items-center gap-1.5 flex-wrap">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
            <span className="font-medium">
              {prettyActivity(active.activity)}
            </span>
            {active.activity_detail ? (
              <span className="font-mono">— {active.activity_detail}</span>
            ) : null}
            {active.activity_started_at ? (
              <ElapsedSince since={active.activity_started_at} />
            ) : null}
          </div>
        ) : active.bridge_ready ? (
          <BridgeReadyPill version={active.bridge_version ?? null} />
        ) : null}
        {active.last_reconcile_error ? (
          <div className="text-xs px-2 py-1 rounded-md bg-red-50 border border-red-200 text-red-900">
            <span className="font-medium">Last setup error:</span>{' '}
            <span className="font-mono break-all">
              {active.last_reconcile_error}
            </span>
          </div>
        ) : null}
        <div>{labels.subtitle}</div>
        {active.status === 'cold' ? (
          <div className="text-xs text-gray-500">
            Paused — <span className="font-medium">no compute cost</span> while cold. Filesystem preserved. Click <span className="font-medium">Start session</span> or open the URL to wake.
          </div>
        ) : null}
        {active.status === 'warm' || active.status === 'running' ? (
          <div className="text-xs text-gray-500">
            Click <span className="font-medium">Pause</span> to release compute now (or wait — Sprites auto-pauses after idle).
          </div>
        ) : null}
        {active.status === 'failed' && active.failure_reason ? (
          <div className="text-xs text-red-600 break-all">
            {active.failure_reason}
          </div>
        ) : null}
        {active.public_url ? (
          <div className="text-xs text-gray-500">
            URL:{' '}
            <a
              href={active.public_url}
              target="_blank"
              rel="noreferrer"
              className="font-mono text-gray-700 hover:text-black hover:underline break-all"
            >
              {active.public_url}
            </a>
          </div>
        ) : null}
        <div className="text-xs text-gray-500">
          Provider: <span className="font-mono">{active.provider_name}</span>
          {active.reset_count > 0 ? <> · Reset count: {active.reset_count}</> : null}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {isAlive ? (
          <Link
            to="/sandbox"
            className="px-4 py-2 rounded-lg bg-black text-white text-sm font-medium hover:bg-gray-800"
          >
            Open IDE
          </Link>
        ) : null}
        {isAlive && active.status !== 'running' ? (
          <button
            type="button"
            onClick={() => wake.mutate(active.id)}
            disabled={wake.isPending}
            className="px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-900 text-sm hover:bg-gray-50 disabled:opacity-60"
          >
            {wake.isPending ? 'Starting…' : 'Start session'}
          </button>
        ) : null}
        {(active.status === 'warm' || active.status === 'running') && (
          <button
            type="button"
            onClick={() => pause.mutate(active.id)}
            disabled={pause.isPending}
            className="px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-900 text-sm hover:bg-gray-50 disabled:opacity-60"
            title="Release compute now; storage preserved"
          >
            {pause.isPending ? 'Pausing…' : 'Pause'}
          </button>
        )}
        {isAlive ? (
          <button
            type="button"
            onClick={() => refresh.mutate(active.id)}
            disabled={refresh.isPending}
            className="px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-900 text-sm hover:bg-gray-50 disabled:opacity-60"
            title="Resync live status from the provider"
          >
            {refresh.isPending ? 'Refreshing…' : 'Refresh'}
          </button>
        ) : null}
        {(isAlive || active.status === 'failed') && (
          <button
            type="button"
            onClick={() => setDialog('reset')}
            disabled={reset.isPending}
            className="px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-900 text-sm hover:bg-gray-50 disabled:opacity-60"
          >
            {reset.isPending ? 'Resetting…' : 'Reset'}
          </button>
        )}
        {active.status !== 'destroyed' && (
          <button
            type="button"
            onClick={() => setDialog('destroy')}
            disabled={destroy.isPending}
            className="px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-700 text-xs hover:bg-gray-50 disabled:opacity-60 ml-auto"
          >
            Delete sandbox
          </button>
        )}
      </div>
      {(reset.error instanceof SandboxStateError ||
        wake.error instanceof SandboxStateError ||
        pause.error instanceof SandboxStateError) && (
        <div className="mt-2 text-xs text-red-600">
          That action isn&apos;t allowed in the current state. The view has refreshed.
        </div>
      )}

      {dialog === 'reset' && (
        <ConfirmDialog
          title="Reset sandbox?"
          body="This wipes your sandbox's filesystem (cloned repos, installed packages, in-progress work) and gives you a fresh one. Your repo connections are preserved and will re-clone automatically. The sandbox itself stays the same."
          confirmLabel="Reset"
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            setDialog(null);
            await reset.mutateAsync(active.id);
          }}
        />
      )}
      {dialog === 'destroy' && (
        <ConfirmDialog
          title="Delete sandbox?"
          body="This fully tears down the sandbox. To use coding features again you'll need to provision a new one. (Use Reset instead if you just want a clean filesystem.)"
          confirmLabel="Delete sandbox"
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            setDialog(null);
            await destroy.mutateAsync(active.id);
          }}
        />
      )}
    </Card>
  );
}

const LABELS: Record<
  SandboxResponse['status'],
  { subtitle: string }
> = {
  provisioning: { subtitle: 'Provisioning…' },
  cold: { subtitle: 'Paused — Sprites auto-pauses after idle.' },
  warm: { subtitle: 'Warming up.' },
  running: { subtitle: 'Running.' },
  resetting: { subtitle: 'Resetting filesystem…' },
  destroyed: { subtitle: 'Sandbox deleted.' },
  failed: { subtitle: 'Sandbox failed to provision.' },
};

function pickActive(
  data: ReadonlyArray<SandboxResponse> | undefined,
): SandboxResponse | null {
  if (!data || data.length === 0) return null;
  // Orchestrator returns most-recent first. Skip destroyed docs — the user
  // should see the active one.
  for (const s of data) {
    if (s.status !== 'destroyed') return s;
  }
  return null;
}

function ElapsedSince({ since }: { since: string }) {
  // Re-renders every second so the user can tell "slow legitimate
  // compile" (timer keeps ticking) from "actually stuck" (timer rolls
  // past the timeout). The parent already polls Sandbox state every
  // 2s when activity != null, so the `since` prop refreshes whenever
  // the reconciler transitions to a new phase — this just smooths
  // the display between polls.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const handle = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(handle);
  }, []);
  const startedMs = Date.parse(since);
  if (Number.isNaN(startedMs)) return null;
  const elapsed = Math.max(0, Math.floor((now - startedMs) / 1000));
  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;
  const label = m > 0 ? `${m}m ${s}s` : `${s}s`;
  return <span className="text-amber-700/70">· {label}</span>;
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <section className="rounded-2xl bg-white border border-gray-200 shadow-sm p-5 space-y-2">
      {children}
    </section>
  );
}

function Header({ title, pill }: { title: string; pill?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
      {pill}
    </div>
  );
}

function StatusPill({ status }: { status: SandboxResponse['status'] }) {
  const styles: Record<SandboxResponse['status'], string> = {
    provisioning: 'bg-gray-50 text-gray-500 border-gray-200',
    cold: 'bg-gray-100 text-gray-700 border-gray-200',
    warm: 'bg-gray-50 text-gray-600 border-gray-200',
    running: 'bg-gray-900 text-white border-gray-900',
    resetting: 'bg-gray-50 text-gray-500 border-gray-200',
    destroyed: 'bg-gray-100 text-gray-500 border-gray-200',
    failed: 'bg-white text-red-600 border-red-200',
  };
  return (
    <span className={`px-2 py-0.5 text-[11px] rounded-md border ${styles[status]}`}>
      {status}
    </span>
  );
}

function ConfirmDialog({
  title,
  body,
  confirmLabel,
  onCancel,
  onConfirm,
}: {
  title: string;
  body: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
      onClick={onCancel}
    >
      <div
        className="bg-white border border-gray-200 rounded-2xl shadow-lg max-w-md w-full p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-base font-semibold text-gray-900">{title}</h3>
        <p className="mt-2 text-sm text-gray-700">{body}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-900 text-sm hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="px-4 py-1.5 rounded-lg bg-black text-white text-sm font-medium hover:bg-gray-800"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
