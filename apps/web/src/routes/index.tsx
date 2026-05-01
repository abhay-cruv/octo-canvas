import { createFileRoute, redirect } from '@tanstack/react-router';
import { meQueryOptions } from '../lib/queries';

export const Route = createFileRoute('/')({
  beforeLoad: async ({ context }) => {
    const me = await context.queryClient.ensureQueryData(meQueryOptions);
    if (me) throw redirect({ to: '/dashboard' });
    throw redirect({ to: '/login' });
  },
});
