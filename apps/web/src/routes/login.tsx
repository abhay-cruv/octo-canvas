import { createFileRoute } from '@tanstack/react-router';
import { startGithubLogin } from '../lib/auth';

export const Route = createFileRoute('/login')({
  component: LoginPage,
});

function LoginPage() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="p-8 border rounded-lg space-y-4">
        <h1 className="text-2xl font-semibold">Sign in</h1>
        <button
          onClick={startGithubLogin}
          className="px-4 py-2 bg-black text-white rounded hover:bg-gray-800"
        >
          Sign in with GitHub
        </button>
      </div>
    </div>
  );
}
