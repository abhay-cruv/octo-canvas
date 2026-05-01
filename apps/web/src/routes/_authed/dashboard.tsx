import { useEffect, useState } from 'react';
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  connectedReposQueryOptions,
  meQueryOptions,
} from '../../lib/queries';
import { logout, manageGithubAccessUrl, startGithubLogin } from '../../lib/auth';
import {
  disconnectRepo,
  GithubReauthRequiredError,
  type IntrospectionOverrides,
  reintrospectRepo,
  updateIntrospectionOverrides,
} from '../../lib/repos';
import { SandboxPanel } from '../../components/SandboxPanel';

export const Route = createFileRoute('/_authed/dashboard')({
  component: DashboardPage,
});

const PANEL_KEY = 'vibe.dashboardPanelOpen';

function DashboardPage() {
  const { data: me } = useQuery(meQueryOptions);
  const connected = useQuery(connectedReposQueryOptions);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [panelOpen, setPanelOpen] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true;
    const stored = window.localStorage.getItem(PANEL_KEY);
    return stored === null ? true : stored === '1';
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(PANEL_KEY, panelOpen ? '1' : '0');
  }, [panelOpen]);

  const disconnectMutation = useMutation({
    mutationFn: disconnectRepo,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['repos', 'connected'] });
      void queryClient.invalidateQueries({ queryKey: ['repos', 'available'] });
    },
    onError: (err) => {
      if (err instanceof GithubReauthRequiredError) {
        void queryClient.invalidateQueries({ queryKey: ['me'] });
      }
    },
  });

  const reintrospectMutation = useMutation({
    mutationFn: reintrospectRepo,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['repos', 'connected'] });
    },
    onError: (err) => {
      if (err instanceof GithubReauthRequiredError) {
        void queryClient.invalidateQueries({ queryKey: ['me'] });
      }
    },
  });

  const overridesMutation = useMutation({
    mutationFn: updateIntrospectionOverrides,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['repos', 'connected'] });
    },
  });

  if (!me) return null;

  async function handleSignOut() {
    await logout();
    queryClient.setQueryData(meQueryOptions.queryKey, null);
    void navigate({ to: '/login' });
  }

  return (
    <div className="min-h-screen bg-gray-50 flex">
      <ProfilePanel
        me={me}
        open={panelOpen}
        onToggle={() => setPanelOpen((v) => !v)}
        onSignOut={handleSignOut}
      />

      <main className="flex-1 px-6 py-10 min-w-0">
        <div className="mx-auto max-w-3xl space-y-6">
          {me.needs_github_reauth ? (
            <ReconnectCard />
          ) : (
            <>
              <SandboxPanel />
              <ReposCenter
              repos={connected.data ?? null}
              isLoading={connected.isLoading}
              onDisconnect={(id) => disconnectMutation.mutate(id)}
              disconnectingId={
                disconnectMutation.isPending ? disconnectMutation.variables : null
              }
              onReintrospect={(id) => reintrospectMutation.mutate(id)}
              reintrospectingId={
                reintrospectMutation.isPending
                  ? reintrospectMutation.variables
                  : null
              }
              onSaveOverrides={(repoId, overrides) =>
                overridesMutation.mutateAsync({ repoId, overrides })
              }
              savingOverridesId={
                overridesMutation.isPending
                  ? overridesMutation.variables.repoId
                  : null
              }
            />
            </>
          )}
        </div>
      </main>
    </div>
  );
}

type Me = NonNullable<Awaited<ReturnType<NonNullable<typeof meQueryOptions.queryFn>>>>;

function ProfilePanel({
  me,
  open,
  onToggle,
  onSignOut,
}: {
  me: Me;
  open: boolean;
  onToggle: () => void;
  onSignOut: () => void | Promise<void>;
}) {
  const displayName = me.display_name ?? me.github_username;

  return (
    <aside
      className={`shrink-0 transition-[width] duration-200 ease-out border-r border-gray-200 bg-white/80 backdrop-blur min-h-screen flex flex-col ${
        open ? 'w-72' : 'w-14'
      }`}
      aria-label="GitHub profile panel"
    >
      {open ? (
        <>
          <div className="h-14 px-4 flex items-center justify-between border-b border-gray-200">
            <div className="flex items-center gap-2 text-sm font-medium text-gray-900 min-w-0">
              <BrandMark className="h-6 w-6 shrink-0" />
              <span className="truncate">vibe-platform</span>
            </div>
            <button
              type="button"
              onClick={onToggle}
              aria-expanded
              aria-label="Collapse profile panel"
              className="h-7 w-7 shrink-0 flex items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-900 transition"
            >
              <CloseIcon className="h-4 w-4" />
            </button>
          </div>

          <nav className="flex-1 overflow-y-auto px-3 py-4 space-y-6">
            <div className="px-1 space-y-3">
              <SectionLabel>Profile</SectionLabel>
              <div className="flex items-center gap-3">
                {me.github_avatar_url ? (
                  <img
                    src={me.github_avatar_url}
                    alt=""
                    className="h-10 w-10 rounded-full border border-gray-200 shrink-0"
                  />
                ) : (
                  <div
                    className="h-10 w-10 rounded-full bg-gray-200 shrink-0"
                    aria-hidden
                  />
                )}
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-gray-900 truncate">
                    {displayName}
                  </div>
                  <a
                    href={`https://github.com/${me.github_username}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-gray-600 hover:text-black hover:underline truncate block"
                  >
                    @{me.github_username}
                  </a>
                </div>
              </div>
              <div className="text-xs text-gray-600 break-all">{me.email}</div>
            </div>
          </nav>

          <div className="px-3 py-3 border-t border-gray-200 space-y-1">
            <a
              href={manageGithubAccessUrl()}
              target="_blank"
              rel="noreferrer"
              className="block w-full px-3 py-1.5 text-sm rounded-lg text-gray-700 hover:bg-gray-100 hover:text-gray-900 transition text-left"
              title="Open GitHub's OAuth-app settings page to grant or request access for orgs"
            >
              Manage GitHub org access ↗
            </a>
            <button
              type="button"
              onClick={() => void onSignOut()}
              className="w-full px-3 py-1.5 text-sm rounded-lg text-gray-700 hover:bg-gray-100 hover:text-gray-900 transition text-left"
            >
              Sign out
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="h-14 flex items-center justify-center border-b border-gray-200">
            <BrandMark className="h-6 w-6" />
          </div>
          <div className="flex flex-col items-center pt-3">
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={false}
              aria-label="Expand profile panel"
              className="h-10 w-10 flex items-center justify-center rounded-lg text-gray-700 hover:bg-gray-100 hover:text-gray-900 transition"
            >
              <GithubIcon className="h-5 w-5" />
            </button>
          </div>
        </>
      )}
    </aside>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] uppercase tracking-wider font-medium text-gray-400">
      {children}
    </div>
  );
}

function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={`inline-block rounded-md bg-black ${className ?? ''}`}
      aria-hidden
    />
  );
}

function ReposCenter({
  repos,
  isLoading,
  onDisconnect,
  disconnectingId,
  onReintrospect,
  reintrospectingId,
  onSaveOverrides,
  savingOverridesId,
}: {
  repos: ReadonlyArray<Repo> | null;
  isLoading: boolean;
  onDisconnect: (id: string) => void;
  disconnectingId: string | null;
  onReintrospect: (id: string) => void;
  reintrospectingId: string | null;
  onSaveOverrides: (
    repoId: string,
    overrides: IntrospectionOverrides,
  ) => Promise<unknown>;
  savingOverridesId: string | null;
}) {
  return (
    <>
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-gray-900">
            Repositories
          </h1>
          <p className="text-sm text-gray-600 mt-1">
            Repositories the agent can read, branch, and open PRs in.
          </p>
        </div>
        <Link
          to="/repos/connect"
          className="shrink-0 px-4 py-2 rounded-lg bg-black text-white text-sm font-medium hover:bg-gray-800"
        >
          Browse repositories
        </Link>
      </div>

      <section className="rounded-2xl bg-white border border-gray-200 shadow-sm">
        {isLoading ? (
          <Empty>Loading…</Empty>
        ) : !repos || repos.length === 0 ? (
          <EmptyConnected />
        ) : (
          <ul className="divide-y divide-gray-200">
            {repos.map((repo) => (
              <RepoRow
                key={repo.id}
                repo={repo}
                onDisconnect={onDisconnect}
                isDisconnecting={disconnectingId === repo.id}
                onReintrospect={onReintrospect}
                isReintrospecting={reintrospectingId === repo.id}
                onSaveOverrides={onSaveOverrides}
                isSavingOverrides={savingOverridesId === repo.id}
              />
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

type Repo = Awaited<
  ReturnType<NonNullable<typeof connectedReposQueryOptions.queryFn>>
>[number];

type Introspection = NonNullable<Repo['introspection']>;

const OVERRIDE_FIELDS: ReadonlyArray<{
  key: keyof IntrospectionOverrides;
  label: string;
  placeholder: string;
}> = [
  { key: 'primary_language', label: 'Language', placeholder: 'TypeScript' },
  { key: 'package_manager', label: 'Package manager', placeholder: 'pnpm' },
  { key: 'test_command', label: 'Test', placeholder: 'pnpm test' },
  { key: 'build_command', label: 'Build', placeholder: 'pnpm build' },
  { key: 'dev_command', label: 'Dev', placeholder: 'pnpm dev' },
];

function RepoRow({
  repo,
  onDisconnect,
  isDisconnecting,
  onReintrospect,
  isReintrospecting,
  onSaveOverrides,
  isSavingOverrides,
}: {
  repo: Repo;
  onDisconnect: (id: string) => void;
  isDisconnecting: boolean;
  onReintrospect: (id: string) => void;
  isReintrospecting: boolean;
  onSaveOverrides: (
    repoId: string,
    overrides: IntrospectionOverrides,
  ) => Promise<unknown>;
  isSavingOverrides: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const overrides = repo.introspection_overrides ?? null;
  const detected = repo.introspection_detected ?? null;
  const effective = repo.introspection ?? null;

  return (
    <li className="flex flex-col gap-3 py-3 px-5">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-medium text-gray-900 truncate">
            {repo.full_name}
          </div>
          <div className="text-xs text-gray-600 mt-0.5">
            {repo.private ? 'Private' : 'Public'} ·{' '}
            <CloneStatusLabel status={repo.clone_status} />
          </div>
          <IntrospectionPills
            effective={effective}
            overrides={overrides}
            isLoading={isReintrospecting}
          />
        </div>
        <div className="shrink-0 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setEditing((v) => !v)}
            className="text-sm px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-900 hover:bg-gray-50"
          >
            {editing ? 'Close' : 'Edit fields'}
          </button>
          <button
            type="button"
            onClick={() => onReintrospect(repo.id)}
            disabled={isReintrospecting}
            className="text-sm px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-900 hover:bg-gray-50 disabled:opacity-60"
          >
            {isReintrospecting
              ? 'Detecting…'
              : detected
                ? 'Re-introspect'
                : 'Detect repo info'}
          </button>
          <button
            type="button"
            onClick={() => onDisconnect(repo.id)}
            disabled={isDisconnecting}
            className="text-sm px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-900 hover:bg-gray-100 disabled:opacity-60"
          >
            Disconnect
          </button>
        </div>
      </div>
      {editing ? (
        <OverrideEditor
          overrides={overrides}
          detected={detected}
          isSaving={isSavingOverrides}
          onCancel={() => setEditing(false)}
          onSave={async (next) => {
            await onSaveOverrides(repo.id, next);
            setEditing(false);
          }}
        />
      ) : null}
    </li>
  );
}

function OverrideEditor({
  overrides,
  detected,
  isSaving,
  onCancel,
  onSave,
}: {
  overrides: IntrospectionOverrides | null;
  detected: Introspection | null;
  isSaving: boolean;
  onCancel: () => void;
  onSave: (next: IntrospectionOverrides) => Promise<unknown>;
}) {
  const [draft, setDraft] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    if (overrides) {
      for (const { key } of OVERRIDE_FIELDS) {
        const value = overrides[key];
        if (typeof value === 'string') initial[key] = value;
      }
    }
    return initial;
  });

  function buildPayload(): IntrospectionOverrides {
    const out: Record<string, string | null> = {};
    for (const { key } of OVERRIDE_FIELDS) {
      const v = draft[key]?.trim() ?? '';
      out[key] = v === '' ? null : v;
    }
    return out as IntrospectionOverrides;
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50/50 p-4 space-y-3">
      <div className="text-xs text-gray-600">
        Override what introspection detected. Leave a field empty to fall back to the detected value.
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {OVERRIDE_FIELDS.map(({ key, label, placeholder }) => {
          const detectedValue =
            detected !== null
              ? (detected[key as keyof Introspection] as string | null | undefined)
              : null;
          return (
            <label key={key} className="flex flex-col gap-1 min-w-0">
              <span className="text-[11px] uppercase tracking-wider text-gray-500">
                {label}
              </span>
              <input
                type="text"
                value={draft[key] ?? ''}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, [key]: e.target.value }))
                }
                placeholder={detectedValue ?? placeholder}
                className="px-2 py-1.5 text-sm rounded-md border border-gray-300 bg-white focus:outline-none focus:border-black"
              />
              {detectedValue ? (
                <span className="text-[11px] text-gray-500 truncate">
                  Detected: <span className="font-mono">{detectedValue}</span>
                </span>
              ) : null}
            </label>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-2 justify-end">
        <button
          type="button"
          onClick={() => setDraft({})}
          disabled={isSaving}
          className="text-sm px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-900 hover:bg-gray-50 disabled:opacity-60"
        >
          Clear all
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={isSaving}
          className="text-sm px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-900 hover:bg-gray-50 disabled:opacity-60"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={() => void onSave(buildPayload())}
          disabled={isSaving}
          className="text-sm px-3 py-1.5 rounded-lg bg-black text-white hover:bg-gray-800 disabled:opacity-60"
        >
          {isSaving ? 'Saving…' : 'Save overrides'}
        </button>
      </div>
    </div>
  );
}

function IntrospectionPills({
  effective,
  overrides,
  isLoading,
}: {
  effective: Introspection | null;
  overrides: IntrospectionOverrides | null;
  isLoading: boolean;
}) {
  if (effective === null && overrides === null) {
    return (
      <div
        className={`mt-2 text-xs text-gray-500 italic ${isLoading ? 'opacity-60' : ''}`}
      >
        No introspection yet — click “Detect repo info” or “Edit fields”.
      </div>
    );
  }
  function pillFor(key: keyof Introspection & keyof IntrospectionOverrides) {
    const value = effective ? (effective[key] as string | null) : null;
    const isOverridden =
      overrides !== null && (overrides[key] as string | null) !== null;
    return (
      <Pill
        key={key}
        label={value}
        mono={key !== 'primary_language' && key !== 'package_manager'}
        overridden={isOverridden}
      />
    );
  }
  return (
    <div
      className={`mt-2 flex flex-wrap items-center gap-1.5 ${isLoading ? 'opacity-60' : ''}`}
    >
      {pillFor('primary_language')}
      {pillFor('package_manager')}
      {pillFor('test_command')}
      {pillFor('build_command')}
      {pillFor('dev_command')}
    </div>
  );
}

function ReconnectCard() {
  return (
    <section className="rounded-2xl bg-white border border-gray-200 shadow-sm p-6 space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">
          Reconnect GitHub to continue
        </h2>
        <p className="text-sm text-gray-600 mt-1">
          Your GitHub access has expired or been revoked. Reconnect to grant the
          <code className="mx-1 px-1 py-0.5 bg-gray-100 rounded text-xs">repo</code>
          scope so we can list, clone, and push to your repositories.
          Already-connected repos are preserved.
        </p>
      </div>
      <button
        type="button"
        onClick={startGithubLogin}
        className="px-4 py-2 rounded-lg bg-black text-white text-sm font-medium hover:bg-gray-800"
      >
        Reconnect GitHub
      </button>
    </section>
  );
}

function EmptyConnected() {
  return (
    <div className="px-5 py-12 text-center">
      <div className="text-sm font-medium text-gray-900">
        No repositories connected yet
      </div>
      <div className="text-xs text-gray-600 mt-1">
        Click “Browse repositories” above to add one.
      </div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-5 py-6 text-sm text-gray-600">{children}</div>;
}

function Pill({
  label,
  mono,
  overridden,
}: {
  label: string | null;
  mono?: boolean;
  overridden?: boolean;
}) {
  if (label === null) {
    return (
      <span className="px-1.5 py-0.5 text-[11px] rounded-md bg-gray-50 text-gray-400 border border-gray-200">
        —
      </span>
    );
  }
  return (
    <span
      className={`px-1.5 py-0.5 text-[11px] rounded-md border inline-flex items-center gap-1 ${
        overridden
          ? 'bg-black text-white border-black'
          : 'bg-gray-100 text-gray-800 border-gray-200'
      } ${mono ? 'font-mono' : ''}`}
      title={overridden ? 'Overridden by you' : undefined}
    >
      {label}
      {overridden ? <span aria-hidden>•</span> : null}
    </span>
  );
}

function CloneStatusLabel({ status }: { status: string }) {
  const label =
    status === 'pending'
      ? 'pending — sandbox not yet provisioned'
      : status === 'cloning'
        ? 'cloning'
        : status === 'ready'
          ? 'ready'
          : status === 'failed'
            ? 'clone failed'
            : status;
  return <span>{label}</span>;
}

function CloseIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden
      className={className}
    >
      <path d="M5 5l10 10M15 5L5 15" />
    </svg>
  );
}

function GithubIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden
      className={className}
    >
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.1.79-.25.79-.55v-1.93c-3.2.7-3.87-1.54-3.87-1.54-.52-1.34-1.28-1.7-1.28-1.7-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.71 1.26 3.37.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.27-5.24-5.66 0-1.25.45-2.27 1.18-3.07-.12-.29-.51-1.46.11-3.05 0 0 .96-.31 3.15 1.18a10.94 10.94 0 0 1 5.74 0c2.19-1.49 3.15-1.18 3.15-1.18.62 1.59.23 2.76.11 3.05.74.8 1.18 1.82 1.18 3.07 0 4.4-2.69 5.36-5.25 5.65.41.36.78 1.06.78 2.13v3.16c0 .31.21.66.8.55 4.57-1.52 7.85-5.83 7.85-10.91C23.5 5.65 18.35.5 12 .5Z" />
    </svg>
  );
}

