import { createFileRoute, useNavigate } from '@tanstack/react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { meQueryOptions } from '../../lib/queries';
import { logout } from '../../lib/auth';

export const Route = createFileRoute('/_authed/dashboard')({
  component: DashboardPage,
});

function DashboardPage() {
  const { data: me } = useQuery(meQueryOptions);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  if (!me) return null;

  async function handleSignOut() {
    await logout();
    queryClient.setQueryData(meQueryOptions.queryKey, null);
    void navigate({ to: '/login' });
  }

  const displayName = me.display_name ?? me.github_username;

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className="px-6 py-5 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-medium text-gray-900">
          <span className="inline-block h-6 w-6 rounded-md bg-black" aria-hidden />
          vibe-platform
        </div>
        <button
          type="button"
          onClick={handleSignOut}
          className="px-3 py-1.5 text-sm rounded-lg bg-white border border-gray-300 text-gray-900 hover:bg-gray-100 transition"
        >
          Sign out
        </button>
      </header>

      <main className="flex-1 px-6 pb-12">
        <div className="mx-auto max-w-2xl space-y-6">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-gray-900">
              Profile
            </h1>
            <p className="text-sm text-gray-600 mt-1">
              Your account details from GitHub.
            </p>
          </div>

          <section className="rounded-2xl bg-white border border-gray-200 shadow-sm p-6">
            <div className="flex items-start gap-5">
              {me.github_avatar_url ? (
                <img
                  src={me.github_avatar_url}
                  alt=""
                  className="h-16 w-16 rounded-full border border-gray-200"
                />
              ) : (
                <div className="h-16 w-16 rounded-full bg-gray-200" aria-hidden />
              )}

              <div className="min-w-0 flex-1">
                <div className="text-lg font-semibold text-gray-900 truncate">
                  {displayName}
                </div>
                <a
                  href={`https://github.com/${me.github_username}`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-gray-600 hover:text-black hover:underline"
                >
                  @{me.github_username}
                </a>
                <div className="text-sm text-gray-600 mt-1 truncate">
                  {me.email}
                </div>
              </div>
            </div>

            <dl className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm border-t border-gray-200 pt-6">
              <Field label="Member since" value={formatDate(me.created_at)} />
              <Field label="Last signed in" value={formatRelative(me.last_signed_in_at)} />
              <Field label="GitHub user ID" value={String(me.github_user_id)} mono />
              <Field label="Account ID" value={me.id} mono />
            </dl>
          </section>
        </div>
      </main>
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-gray-400">{label}</dt>
      <dd
        className={`mt-1 text-gray-900 truncate ${mono ? 'font-mono text-xs' : ''}`}
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const diffMs = Date.now() - then;
  const min = Math.floor(diffMs / 60_000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min} minute${min === 1 ? '' : 's'} ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} hour${hr === 1 ? '' : 's'} ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} day${day === 1 ? '' : 's'} ago`;
  return new Date(iso).toLocaleDateString();
}
