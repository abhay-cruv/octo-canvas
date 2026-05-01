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

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="p-8 border rounded-lg space-y-4 text-center">
        <h1 className="text-2xl font-semibold">Welcome, {me.github_username}</h1>
        <button
          onClick={handleSignOut}
          className="px-4 py-2 bg-gray-200 rounded hover:bg-gray-300"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}
