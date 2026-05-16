import { useEffect, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  createInvite,
  listTenantUsers,
  type InviteResponse,
  type TenantUser,
} from "../lib/api";
import { loadAuth } from "../lib/auth";

export function AdminPage() {
  const auth = loadAuth();
  const [users, setUsers] = useState<TenantUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [role, setRole] = useState<"member" | "admin">("member");
  const [ttlHours, setTtlHours] = useState<number>(168);
  const [invite, setInvite] = useState<InviteResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listTenantUsers()
      .then((u) => {
        if (!cancelled) setUsers(u);
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function onGenerate() {
    setBusy(true);
    setError(null);
    setInvite(null);
    setCopied(false);
    try {
      const r = await createInvite({ role, ttl_hours: ttlHours });
      setInvite(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function fullInviteUrl(path: string): string {
    return `${window.location.origin}${path}`;
  }

  async function copyLink() {
    if (!invite) return;
    try {
      await navigator.clipboard.writeText(fullInviteUrl(invite.accept_url));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked — user can copy manually */
    }
  }

  const isOwner = auth?.user.role === "owner";

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <h1 className="text-lg font-semibold">Workspace admin</h1>
          <p className="text-xs text-ink-500">
            Tenant: {auth?.user.tenant_name ?? "—"} · {users.length} member
            {users.length === 1 ? "" : "s"}
          </p>
        </header>

        <div className="p-6 max-w-3xl space-y-8">
          {!isOwner && (
            <div className="rounded bg-amber-50 border border-amber-300 p-4 text-sm text-amber-900">
              You're not signed in as the workspace owner. Only owners can
              invite team-mates.
            </div>
          )}

          {/* ---- Invites ---- */}
          {isOwner && (
            <section>
              <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
                Invite a team-mate
              </h2>
              <div className="mt-3 flex items-end gap-3 flex-wrap">
                <label className="block">
                  <span className="block text-xs text-ink-700">Role</span>
                  <select
                    value={role}
                    onChange={(e) => setRole(e.target.value as "member" | "admin")}
                    className="mt-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
                  >
                    <option value="member">Member</option>
                    <option value="admin">Admin</option>
                  </select>
                </label>
                <label className="block">
                  <span className="block text-xs text-ink-700">Link valid for</span>
                  <select
                    value={ttlHours}
                    onChange={(e) => setTtlHours(Number(e.target.value))}
                    className="mt-1 rounded-md border border-slate-300 px-3 py-2 text-sm"
                  >
                    <option value={24}>1 day</option>
                    <option value={72}>3 days</option>
                    <option value={168}>7 days (default)</option>
                    <option value={720}>30 days</option>
                  </select>
                </label>
                <button
                  type="button"
                  disabled={busy}
                  onClick={onGenerate}
                  className="rounded-md bg-ink-900 text-white text-sm px-4 py-2 hover:bg-ink-700 disabled:opacity-50"
                >
                  {busy ? "Generating…" : "Generate invite link"}
                </button>
              </div>

              {invite && (
                <div className="mt-4 rounded border border-emerald-200 bg-emerald-50 p-4 text-sm text-ink-800">
                  <div className="font-medium text-emerald-900">
                    Invite link created — copy now, we won't show it again.
                  </div>
                  <div className="mt-2 flex items-stretch gap-2">
                    <input
                      readOnly
                      value={fullInviteUrl(invite.accept_url)}
                      onFocus={(e) => e.currentTarget.select()}
                      className="flex-1 rounded border border-slate-300 px-3 py-2 text-xs font-mono bg-white"
                    />
                    <button
                      type="button"
                      onClick={copyLink}
                      className="rounded bg-ink-900 text-white text-xs px-3 hover:bg-ink-700"
                    >
                      {copied ? "Copied!" : "Copy"}
                    </button>
                  </div>
                  <div className="mt-2 text-xs text-ink-500">
                    Role: <strong>{invite.role}</strong> · Expires:{" "}
                    {new Date(invite.expires_at).toLocaleString()}
                  </div>
                </div>
              )}

              {error && (
                <div className="mt-3 rounded bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
                  {error}
                </div>
              )}
            </section>
          )}

          {/* ---- Users ---- */}
          <section>
            <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
              Members
            </h2>
            {loading ? (
              <div className="mt-3 text-sm text-ink-500">Loading…</div>
            ) : users.length === 0 ? (
              <div className="mt-3 text-sm text-ink-500">No members yet.</div>
            ) : (
              <table className="mt-3 w-full text-sm">
                <thead className="text-xs text-ink-500">
                  <tr>
                    <th className="text-left py-2">Email</th>
                    <th className="text-left py-2">Name</th>
                    <th className="text-left py-2">Role</th>
                    <th className="text-left py-2">Last login</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr
                      key={u.id}
                      className="border-t border-slate-200 hover:bg-slate-50"
                    >
                      <td className="py-2">{u.email}</td>
                      <td className="py-2">{u.full_name || "—"}</td>
                      <td className="py-2">
                        <span className="inline-block rounded bg-slate-200 px-2 py-0.5 text-xs uppercase tracking-wide">
                          {u.role}
                        </span>
                      </td>
                      <td className="py-2 text-ink-500">
                        {u.last_login_at
                          ? new Date(u.last_login_at).toLocaleString()
                          : "never"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
