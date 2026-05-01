import { createFileRoute, Link } from '@tanstack/react-router';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { availableReposQueryOptions } from '../../../lib/queries';
import { startGithubLogin } from '../../../lib/auth';
import { connectRepo, GithubReauthRequiredError } from '../../../lib/repos';

const PER_PAGE = 30;

export const Route = createFileRoute('/_authed/repos/connect')({
  component: ConnectPage,
});

function ConnectPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [scopeMine, setScopeMine] = useState(true);
  const available = useQuery(
    availableReposQueryOptions(page, PER_PAGE, debouncedQuery, scopeMine),
  );
  const [pendingId, setPendingId] = useState<number | null>(null);
  const topRef = useRef<HTMLDivElement>(null);

  // Debounce search input → query value, and reset to page 1 when query changes.
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQuery((prev) => {
        if (prev !== searchInput.trim()) {
          setPage(1);
          return searchInput.trim();
        }
        return prev;
      });
    }, 350);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Reset to page 1 when scope toggle flips.
  useEffect(() => {
    setPage(1);
  }, [scopeMine]);

  useEffect(() => {
    topRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [page]);

  const connectMutation = useMutation({
    mutationFn: connectRepo,
    onMutate: (input) => setPendingId(input.github_repo_id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['repos', 'available'] });
      void queryClient.invalidateQueries({ queryKey: ['repos', 'connected'] });
    },
    onError: (err) => {
      if (err instanceof GithubReauthRequiredError) {
        void queryClient.invalidateQueries({ queryKey: ['me'] });
        void queryClient.invalidateQueries({ queryKey: ['repos', 'available'] });
      }
    },
    onSettled: () => setPendingId(null),
  });

  const data = available.data;
  const reauth = data?.reauth === true;
  const repos = data && !data.reauth ? data.repos : [];
  const hasMore = data && !data.reauth ? data.has_more : false;
  const isSearching = debouncedQuery.length > 0;

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="px-6 py-5 border-b border-gray-200 bg-white">
        <div className="mx-auto max-w-3xl flex items-center justify-between">
          <Link
            to="/dashboard"
            className="text-sm font-medium text-gray-900 flex items-center gap-2 hover:text-black"
          >
            <span className="inline-block h-6 w-6 rounded-md bg-black" aria-hidden />
            octo-canvas
          </Link>
          <Link to="/dashboard" className="text-sm text-gray-600 hover:text-black">
            ← Dashboard
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-10 space-y-6">
        <div ref={topRef} aria-hidden />
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-gray-900">
            Connect a repository
          </h1>
          <p className="text-sm text-gray-600 mt-1">
            {isSearching
              ? `Search results for “${debouncedQuery}” — across every repository your token can read.`
              : 'Browsing the repositories your GitHub OAuth token can read, sorted by most recently pushed. Org repos appear here once you’ve authorized this OAuth app for that org on GitHub.'}
          </p>
        </div>

        {reauth ? (
          <ReconnectCard />
        ) : (
          <>
            <div className="space-y-2">
              <div className="relative">
                <input
                  type="search"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  placeholder="Search all your repositories on GitHub…"
                  className="w-full px-3 py-2 rounded-lg bg-white border border-gray-300 text-sm focus:outline-none focus:border-black"
                />
                {available.isFetching && (
                  <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">
                    …
                  </span>
                )}
              </div>
              <label className="flex items-center gap-2 text-xs text-gray-600 select-none">
                <input
                  type="checkbox"
                  checked={scopeMine}
                  onChange={(e) => setScopeMine(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-gray-300 text-black focus:ring-black"
                />
                Limit to my repos and orgs
                <span className="text-gray-400">
                  {isSearching
                    ? '(uncheck to search all of GitHub)'
                    : '(applies when searching)'}
                </span>
              </label>
            </div>

            <div className="rounded-2xl bg-white border border-gray-200 shadow-sm">
              {available.isLoading && repos.length === 0 ? (
                <div className="p-6 text-sm text-gray-600">Loading…</div>
              ) : repos.length === 0 ? (
                <div className="p-6 text-sm text-gray-600">
                  {isSearching
                    ? `No repositories match "${debouncedQuery}". Try a different query.`
                    : 'No repositories on this page. Try a previous page or authorize more orgs on GitHub.'}
                </div>
              ) : (
                <ul className="divide-y divide-gray-200">
                  {repos.map((repo) => {
                    const pending = pendingId === repo.github_repo_id;
                    return (
                      <li
                        key={repo.github_repo_id}
                        className="flex items-center justify-between px-5 py-3"
                      >
                        <div className="min-w-0">
                          <div className="font-medium text-gray-900 truncate">
                            {repo.full_name}
                          </div>
                          <div className="text-xs text-gray-600 truncate">
                            {repo.private ? 'Private' : 'Public'} ·{' '}
                            {repo.default_branch}
                            {repo.description ? ` · ${repo.description}` : ''}
                          </div>
                        </div>
                        {repo.is_connected ? (
                          <span className="ml-4 px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 text-sm">
                            Connected
                          </span>
                        ) : (
                          <button
                            type="button"
                            onClick={() =>
                              connectMutation.mutate({
                                github_repo_id: repo.github_repo_id,
                                full_name: repo.full_name,
                              })
                            }
                            disabled={pending || connectMutation.isPending}
                            className="ml-4 px-3 py-1.5 rounded-lg bg-black text-white text-sm hover:bg-gray-800 disabled:opacity-60"
                          >
                            {pending ? 'Connecting…' : 'Connect'}
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <div className="flex items-center justify-between text-sm">
              <button
                type="button"
                disabled={page <= 1 || available.isFetching}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-900 hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                ← Previous
              </button>
              <span className="text-gray-600">Page {page}</span>
              <button
                type="button"
                disabled={!hasMore || available.isFetching}
                onClick={() => setPage((p) => p + 1)}
                className="px-3 py-1.5 rounded-lg bg-white border border-gray-300 text-gray-900 hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Next →
              </button>
            </div>
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
          Your GitHub access has expired or been revoked.
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
