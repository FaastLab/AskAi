import { useEffect, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  getGovernanceEvents,
  getPolicy,
  listTenantUsers,
  updatePolicy,
  type GatewayPolicy,
  type GovernanceEvent,
  type TenantUser,
} from "../lib/api";
import { loadAuth } from "../lib/auth";

// Static RBAC capability matrix — what each role can do.
const RBAC: { capability: string; owner: boolean; admin: boolean; member: boolean }[] = [
  { capability: "Ask / search the corpus", owner: true, admin: true, member: true },
  { capability: "Upload & manage documents", owner: true, admin: true, member: true },
  { capability: "View audit trail", owner: true, admin: true, member: false },
  { capability: "Usage & observability", owner: true, admin: true, member: false },
  { capability: "Invite / manage users", owner: true, admin: false, member: false },
  { capability: "Edit prompts", owner: true, admin: false, member: false },
  { capability: "Set security policy", owner: true, admin: false, member: false },
];

const ROLE_BADGE: Record<string, string> = {
  owner: "bg-violet-100 text-violet-900",
  admin: "bg-sky-100 text-sky-900",
  member: "bg-slate-200 text-ink-700",
};

function Check({ on }: { on: boolean }) {
  return <span className={on ? "text-emerald-600" : "text-slate-300"}>{on ? "✓" : "—"}</span>;
}

export function SecurityPage() {
  const auth = loadAuth();
  const isOwner = auth?.user.role === "owner";

  const [policy, setPolicy] = useState<GatewayPolicy | null>(null);
  const [users, setUsers] = useState<TenantUser[]>([]);
  const [events, setEvents] = useState<GovernanceEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // editable draft
  const [enabled, setEnabled] = useState(true);
  const [allowed, setAllowed] = useState<string[]>([]);
  const [maxTokens, setMaxTokens] = useState(0);

  async function refresh() {
    setLoading(true);
    const [p, u, e] = await Promise.all([
      getPolicy(),
      listTenantUsers().catch(() => []),
      getGovernanceEvents(),
    ]);
    if (p) {
      setPolicy(p);
      setEnabled(p.enabled);
      setAllowed(p.allowed_models);
      setMaxTokens(p.max_tokens_per_request);
    }
    setUsers(u ?? []);
    setEvents(e ?? []);
    setLoading(false);
  }

  useEffect(() => {
    if (isOwner) void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOwner]);

  function toggleModel(m: string) {
    setAllowed((cur) => (cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m]));
  }

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      const p = await updatePolicy({
        enabled,
        allowed_models: allowed,
        max_tokens_per_request: maxTokens,
      });
      setPolicy(p);
      setMsg("Policy saved — enforced on the next request.");
      await refresh();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!isOwner) {
    return (
      <div className="flex h-dvh">
        <Sidebar />
        <main className="flex-1 p-6">
          <div className="rounded bg-amber-50 border border-amber-300 p-4 text-sm text-amber-900 max-w-2xl">
            Only the tenant owner can view security &amp; governance.
          </div>
        </main>
      </div>
    );
  }

  const dirty =
    !!policy &&
    (enabled !== policy.enabled ||
      maxTokens !== policy.max_tokens_per_request ||
      allowed.slice().sort().join() !== policy.allowed_models.slice().sort().join());

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <h1 className="text-lg font-semibold">Security &amp; governance</h1>
          <p className="text-xs text-ink-500">
            Control what the AI may do for <strong>{auth?.user.tenant_name}</strong>,
            review who can do what, and see every governance change. Enforced at the
            gateway on every request.
          </p>
        </header>

        {loading ? (
          <div className="p-6 text-sm text-ink-500">Loading…</div>
        ) : (
          <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-slate-50">
            {/* Policy engine */}
            <section className="rounded-lg border border-slate-200 bg-white p-4 max-w-3xl">
              <h2 className="text-sm font-semibold">AI policy</h2>
              <p className="text-xs text-ink-500 mb-3">
                Enforced before every model call — suspend AI, restrict which models
                may run, and cap response length.
              </p>

              <label className="flex items-center gap-2 text-sm mb-3">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                />
                <span>
                  AI enabled for this tenant{" "}
                  {!enabled && (
                    <span className="text-rose-700">(all requests will be blocked)</span>
                  )}
                </span>
              </label>

              <div className="mb-3">
                <div className="text-xs font-medium text-ink-700 mb-1">
                  Allowed models{" "}
                  <span className="text-ink-400">
                    (none selected = any model allowed)
                  </span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {policy?.available_models.map((m) => (
                    <label
                      key={m}
                      className={`flex items-center gap-1.5 text-xs rounded border px-2 py-1 cursor-pointer ${
                        allowed.includes(m)
                          ? "border-ink-700 bg-slate-100"
                          : "border-slate-300"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={allowed.includes(m)}
                        onChange={() => toggleModel(m)}
                      />
                      <span className="font-mono">{m}</span>
                    </label>
                  ))}
                  {allowed
                    .filter((m) => !(policy?.available_models ?? []).includes(m))
                    .map((m) => (
                      <span
                        key={m}
                        className="text-xs rounded border border-ink-700 bg-slate-100 px-2 py-1 font-mono"
                      >
                        {m}
                      </span>
                    ))}
                </div>
              </div>

              <div className="mb-3">
                <label className="text-xs font-medium text-ink-700">
                  Max tokens per request{" "}
                  <span className="text-ink-400">(0 = no cap)</span>
                </label>
                <input
                  type="number"
                  min={0}
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(Math.max(0, Number(e.target.value)))}
                  className="ml-2 w-28 rounded border border-slate-300 px-2 py-1 text-sm"
                />
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={save}
                  disabled={!dirty || saving}
                  className="text-sm rounded bg-ink-900 text-white px-3 py-1.5 hover:bg-ink-700 disabled:opacity-50"
                >
                  {saving ? "Saving…" : "Save policy"}
                </button>
                {dirty && <span className="text-xs text-amber-700">unsaved changes</span>}
                {msg && <span className="text-xs text-ink-600">{msg}</span>}
              </div>
            </section>

            {/* RBAC */}
            <section className="rounded-lg border border-slate-200 bg-white p-4 max-w-3xl">
              <h2 className="text-sm font-semibold mb-2">Roles &amp; access (RBAC)</h2>
              <table className="w-full text-sm mb-4">
                <thead className="text-xs text-ink-500 text-left border-b border-slate-200">
                  <tr>
                    <th className="py-1.5 font-medium">Capability</th>
                    <th className="py-1.5 font-medium text-center">Owner</th>
                    <th className="py-1.5 font-medium text-center">Admin</th>
                    <th className="py-1.5 font-medium text-center">Member</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {RBAC.map((r) => (
                    <tr key={r.capability}>
                      <td className="py-1.5">{r.capability}</td>
                      <td className="py-1.5 text-center"><Check on={r.owner} /></td>
                      <td className="py-1.5 text-center"><Check on={r.admin} /></td>
                      <td className="py-1.5 text-center"><Check on={r.member} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="text-xs font-medium text-ink-700 mb-1">
                Members ({users.length})
              </div>
              <ul className="space-y-1">
                {users.map((u) => (
                  <li key={u.id} className="flex items-center gap-2 text-xs">
                    <span
                      className={
                        "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase " +
                        (ROLE_BADGE[u.role] ?? "bg-slate-200 text-ink-700")
                      }
                    >
                      {u.role}
                    </span>
                    <span>{u.email}</span>
                    {!u.is_active && <span className="text-rose-600">(inactive)</span>}
                  </li>
                ))}
              </ul>
            </section>

            {/* Governance events */}
            <section className="rounded-lg border border-slate-200 bg-white p-4 max-w-3xl">
              <h2 className="text-sm font-semibold mb-2">
                Governance activity ({events.length})
              </h2>
              {events.length === 0 ? (
                <div className="text-xs text-ink-500">
                  No policy/prompt changes recorded yet.
                </div>
              ) : (
                <ul className="divide-y divide-slate-100">
                  {events.map((e, i) => (
                    <li key={i} className="py-2 text-xs flex items-center gap-2 flex-wrap">
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px]">
                        {e.action}
                      </span>
                      <span className="text-ink-500">
                        {new Date(e.created_at).toLocaleString()}
                      </span>
                      <span className="text-ink-600">{e.user_id.slice(0, 8)}</span>
                      {Object.keys(e.extra).length > 0 && (
                        <span className="text-ink-400 font-mono truncate max-w-md">
                          {JSON.stringify(e.extra)}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
