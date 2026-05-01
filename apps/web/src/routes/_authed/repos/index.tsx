import { createFileRoute, Link } from '@tanstack/react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  connectedReposQueryOptions,
  meQueryOptions,
} from '../../../lib/queries';
import { startGithubLogin } from '../../../lib/auth';
import { disconnectRepo, GithubReauthRequiredError } from '../../../lib/repos';

export const Route = createFileRoute('/_authed/repos/')({
  component: ReposPage,
});

function ReposPage() {
  const queryClient = useQueryClient();
  const me = useQuery(meQueryOptions);
  const connected = useQuery(connectedReposQueryOptions);

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

  const needsReauth = me.data?.needs_github_reauth === true;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="px-6 py-5 border-b border-gray-200 bg-white">
        <div className="mx-auto max-w-3xl flex items-center justify-between">
          <Link
            to="/dashboard"
            className="text-sm font-medium text-gray-900 flex items-center gap-2 hover:text-black"
          >
            <span className="inline-block h-6 w-6 rounded-md bg-black" aria-hidden />
            vibe-platform
          </Link>
          <Link to="/dashboard" className="text-sm text-gray-600 hover:text-black">
            ← Dashboard
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-10 space-y-8">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-gray-900">
            Repositories
          </h1>
          <p className="text-sm text-gray-600 mt-1">
            Repositories the agent can read, branch, and open PRs in. Access uses
            your GitHub OAuth token.
          </p>
        </div>

        {needsReauth ? (
          <ReconnectCard />
        ) : (
          <>
            <div className="flex justify-end">
              <Link
                to="/repos/connect"
                className="px-4 py-2 rounded-lg bg-black text-white text-sm font-medium hover:bg-gray-800"
              >
                Browse repositories
              </Link>
            </div>

            <Section title="Connected">
              {connected.isLoading ? (
                <Empty>Loading…</Empty>
              ) : !connected.data || connected.data.length === 0 ? (
                <Empty>
                  No repositories connected yet. Click &ldquo;Browse repositories&rdquo; to add some.
                </Empty>
              ) : (
                <ul className="divide-y divide-gray-200">
                  {connected.data.map((repo) => (
                    <li
                      key={repo.id}
                      className="flex items-center justify-between py-3 px-1"
                    >
                      <div className="min-w-0">
                        <div className="font-medium text-gray-900 truncate">
                          {repo.full_name}
                        </div>
                        <div className="text-xs text-gray-600">
                          {repo.private ? 'Private' : 'Public'} ·{' '}
                          <CloneStatusLabel status={repo.clone_status} />
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => disconnectMutation.mutate(repo.id)}
                        disabled={disconnectMutation.isPending}
                        className="text-sm px-3 py-1.5 rounded-lg bg-white border border-gray-300 hover:bg-gray-100 disabled:opacity-60"
                      >
                        Disconnect
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </>
        )}
      </main>
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-gray-600">
        {title}
      </h2>
      <div className="rounded-2xl bg-white border border-gray-200 shadow-sm px-5">
        {children}
      </div>
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="py-6 text-sm text-gray-600">{children}</div>;
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
