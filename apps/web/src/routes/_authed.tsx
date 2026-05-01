import { createFileRoute, Outlet, redirect } from '@tanstack/react-router';
import { meQueryOptions } from '../lib/queries';

export const Route = createFileRoute('/_authed')({
  beforeLoad: async ({ context }) => {
    const me = await context.queryClient.ensureQueryData(meQueryOptions);
    if (!me) throw redirect({ to: '/login' });
  },
  component: () => <Outlet />,
});
