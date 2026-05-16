import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { acceptInvite } from "../lib/api";

export function AcceptInvitePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || "";

  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<{
    tenant_name: string;
    role: string;
  } | null>(null);

  useEffect(() => {
    if (!token) {
      setError("Missing invite token. Ask your workspace admin for a new link.");
    }
  }, [token]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!token) return;
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      const r = await acceptInvite({
        token,
        email: email.trim().toLowerCase(),
        password,
        full_name: fullName.trim() || undefined,
      });
      setSuccess({ tenant_name: r.tenant_name, role: r.role });
      // Auto-redirect to login after 2s — they need to sign in to mint a JWT.
      setTimeout(() => navigate("/login", { replace: true }), 2000);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-dvh flex items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-md bg-white rounded-lg shadow-sm border border-slate-200 p-6">
        <h1 className="text-xl font-semibold text-ink-900">
          Join the workspace
        </h1>
        <p className="mt-1 text-sm text-ink-500">
          Set your password to accept the invite.
        </p>

        {success ? (
          <div className="mt-5 rounded bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-ink-800">
            <div className="font-medium text-emerald-900">
              Welcome to {success.tenant_name}!
            </div>
            <div className="mt-1 text-ink-600">
              Role: {success.role}. Redirecting to sign-in…
            </div>
          </div>
        ) : (
          <form onSubmit={onSubmit} className="mt-5 space-y-3">
            <label className="block">
              <span className="block text-xs font-medium text-ink-700">Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ink-900/20"
              />
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-ink-700">
                Full name (optional)
              </span>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ink-900/20"
              />
            </label>
            <label className="block">
              <span className="block text-xs font-medium text-ink-700">
                Password
              </span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                placeholder="At least 8 characters"
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ink-900/20"
              />
            </label>

            {error && (
              <div className="rounded bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy || !token}
              className="w-full rounded-md bg-ink-900 px-4 py-2 text-sm font-medium text-white hover:bg-ink-700 disabled:opacity-50"
            >
              {busy ? "Joining…" : "Accept invite"}
            </button>
          </form>
        )}

        <p className="mt-4 text-xs text-ink-500 text-center">
          Already have an account?{" "}
          <Link to="/login" className="underline text-ink-700 hover:text-ink-900">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
