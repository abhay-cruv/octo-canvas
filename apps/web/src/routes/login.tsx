import { createFileRoute } from '@tanstack/react-router';
import { useState } from 'react';
import { startGithubLogin } from '../lib/auth';

export const Route = createFileRoute('/login')({
  component: LoginPage,
});

function LoginPage() {
  const [loading, setLoading] = useState(false);

  const handleSignIn = () => {
    setLoading(true);
    startGithubLogin();
  };

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className="px-6 py-5">
        <div className="flex items-center gap-2 text-sm font-medium text-gray-900">
          <span className="inline-block h-6 w-6 rounded-md bg-black" aria-hidden />
          octo-canvas
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center px-6">
        <div className="w-full max-w-sm">
          <div className="rounded-2xl bg-white/80 backdrop-blur border border-gray-200 shadow-sm p-8 space-y-6">
            <div className="space-y-2">
              <h1 className="text-2xl font-semibold tracking-tight text-gray-900">
                Welcome back
              </h1>
              <p className="text-sm text-gray-600">
                Sign in to continue to your workspace.
              </p>
            </div>

            <button
              type="button"
              onClick={handleSignIn}
              disabled={loading}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-black text-white text-sm font-medium hover:bg-gray-800 transition disabled:opacity-60 disabled:cursor-not-allowed"
            >
              <GitHubIcon />
              {loading ? 'Redirecting…' : 'Continue with GitHub'}
            </button>

            <div className="flex items-center gap-3 text-xs text-gray-400">
              <div className="flex-1 h-px bg-gray-200" />
              <span>Secure OAuth</span>
              <div className="flex-1 h-px bg-gray-200" />
            </div>

            <p className="text-xs text-gray-600 text-center">
              We only request your public profile and email. No repository access.
            </p>
          </div>

          <p className="mt-6 text-center text-xs text-gray-400">
            By continuing, you agree to our terms of service and privacy policy.
          </p>
        </div>
      </main>

      <footer className="px-6 py-4 text-center text-xs text-gray-400">
        © {new Date().getFullYear()} octo-canvas
      </footer>
    </div>
  );
}

function GitHubIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="currentColor"
      aria-hidden
    >
      <path d="M12 .5C5.73.5.74 5.5.74 11.77c0 4.99 3.23 9.22 7.71 10.71.56.1.77-.24.77-.54 0-.27-.01-1.16-.02-2.1-3.14.68-3.8-1.34-3.8-1.34-.51-1.3-1.25-1.65-1.25-1.65-1.02-.7.08-.69.08-.69 1.13.08 1.72 1.16 1.72 1.16 1 1.72 2.63 1.22 3.27.93.1-.73.39-1.22.71-1.5-2.51-.29-5.15-1.26-5.15-5.59 0-1.24.44-2.25 1.16-3.04-.12-.29-.5-1.43.11-2.99 0 0 .95-.31 3.11 1.16.9-.25 1.86-.37 2.82-.38.96 0 1.92.13 2.82.38 2.16-1.47 3.11-1.16 3.11-1.16.61 1.56.23 2.7.11 2.99.72.79 1.16 1.8 1.16 3.04 0 4.34-2.65 5.3-5.17 5.58.4.35.76 1.03.76 2.08 0 1.5-.01 2.71-.01 3.08 0 .3.2.65.78.54 4.48-1.49 7.7-5.72 7.7-10.71C23.26 5.5 18.27.5 12 .5z" />
    </svg>
  );
}
