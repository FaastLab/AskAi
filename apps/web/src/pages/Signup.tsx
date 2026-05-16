import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { signup } from "../lib/api";

export function SignupPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [organisation, setOrganisation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email.trim() || !password || !organisation.trim()) {
      setError("Email, password, and organisation are required.");
      return;
    }
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      await signup({
        email: email.trim().toLowerCase(),
        password,
        full_name: fullName.trim() || undefined,
        organisation: organisation.trim(),
      });
      navigate("/chat", { replace: true });
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
          Start your 14-day trial
        </h1>
        <p className="mt-1 text-sm text-ink-500">
          No card required. Full access to the FCA / BoE / PRA / HMRC / ICO / TPR
          knowledge base, chat, search, and citations.
        </p>

        <form onSubmit={onSubmit} className="mt-5 space-y-3">
          <Field
            label="Organisation"
            value={organisation}
            onChange={setOrganisation}
            placeholder="Acme Fintech Ltd"
            required
            autoFocus
          />
          <Field
            label="Full name (optional)"
            value={fullName}
            onChange={setFullName}
            placeholder="Jane Smith"
          />
          <Field
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            placeholder="jane@acme.co.uk"
            required
          />
          <Field
            label="Password"
            type="password"
            value={password}
            onChange={setPassword}
            placeholder="At least 8 characters"
            required
          />

          {error && (
            <div className="rounded bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md bg-ink-900 px-4 py-2 text-sm font-medium text-white hover:bg-ink-700 disabled:opacity-50"
          >
            {busy ? "Creating your workspace…" : "Create account"}
          </button>
        </form>

        <p className="mt-4 text-xs text-ink-500 text-center">
          Already have an account?{" "}
          <Link to="/login" className="underline text-ink-700 hover:text-ink-900">
            Sign in
          </Link>
        </p>
        <p className="mt-2 text-xs text-ink-400 text-center">
          By signing up you agree that this is a beta service and FaastLab.Ai
          may use anonymised usage data to improve the product.
        </p>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  required,
  autoFocus,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  required?: boolean;
  autoFocus?: boolean;
}) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-ink-700">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        autoFocus={autoFocus}
        className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ink-900/20"
      />
    </label>
  );
}
