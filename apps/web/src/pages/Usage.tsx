import { useEffect, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  getGatewayRequests,
  getGatewayUsage,
  type GatewayRequests,
  type GatewayUsage,
} from "../lib/api";
import { loadAuth } from "../lib/auth";

const WINDOWS = [
  { hours: 24, label: "Last 24h" },
  { hours: 24 * 7, label: "Last 7 days" },
  { hours: 24 * 30, label: "Last 30 days" },
];

const STATUS_BADGE: Record<string, string> = {
  ok: "bg-emerald-100 text-emerald-900",
  error: "bg-rose-100 text-rose-900",
  quota_denied: "bg-amber-100 text-amber-900",
};

function fmtInt(n: number): string {
  return n.toLocaleString();
}

function fmtCost(n: number): string {
  return n === 0 ? "$0 (sovereign)" : `$${n.toFixed(4)}`;
}

function fmtMs(n: number | null): string {
  if (n == null) return "—";
  return n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${Math.round(n)}ms`;
}

export function UsagePage() {
  const auth = loadAuth();
  const isOwnerOrAdmin =
    auth?.user.role === "owner" || auth?.user.role === "admin";

  const [windowHours, setWindowHours] = useState(24);
  const [usage, setUsage] = useState<GatewayUsage | null>(null);
  const [feed, setFeed] = useState<GatewayRequests | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isOwnerOrAdmin) return;
    let cancelled = false;
    setLoading(true);
    Promise.all([
      getGatewayUsage(windowHours),
      getGatewayRequests(windowHours, 100),
    ])
      .then(([u, f]) => {
        if (cancelled) return;
        setUsage(u);
        setFeed(f);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [windowHours, isOwnerOrAdmin]);

  if (!isOwnerOrAdmin) {
    return (
      <div className="flex h-dvh">
        <Sidebar />
        <main className="flex-1 p-6">
          <div className="rounded bg-amber-50 border border-amber-300 p-4 text-sm text-amber-900 max-w-2xl">
            Only owners and admins can view usage &amp; observability.
          </div>
        </main>
      </div>
    );
  }

  const quotaLabel = (limit: number, remaining: number | null) =>
    limit <= 0 ? "Unlimited" : `${fmtInt(remaining ?? 0)} left of ${fmtInt(limit)}/day`;

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <h1 className="text-lg font-semibold">Usage &amp; observability</h1>
              <p className="text-xs text-ink-500">
                Per-tenant AI gateway activity for{" "}
                <strong>{auth?.user.tenant_name}</strong> — requests, tokens,
                cost, latency, and failures.
              </p>
            </div>
            <select
              value={windowHours}
              onChange={(e) => setWindowHours(Number(e.target.value))}
              className="rounded-md border border-slate-300 px-2 py-1 text-sm"
            >
              {WINDOWS.map((w) => (
                <option key={w.hours} value={w.hours}>
                  {w.label}
                </option>
              ))}
            </select>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-slate-50">
          {loading ? (
            <div className="text-sm text-ink-500">Loading…</div>
          ) : (
            <>
              {/* Stat cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Stat label="Requests" value={fmtInt(usage?.requests ?? 0)} sub={`${usage?.ok ?? 0} ok`} />
                <Stat label="Tokens" value={fmtInt(usage?.tokens ?? 0)} sub="prompt + completion" />
                <Stat label="Cost" value={fmtCost(usage?.cost_usd ?? 0)} sub="this window" />
                <Stat
                  label="Failures"
                  value={fmtInt((usage?.errors ?? 0) + (usage?.denied ?? 0))}
                  sub={`${usage?.errors ?? 0} errors · ${usage?.denied ?? 0} quota-blocked`}
                  alert={(usage?.errors ?? 0) + (usage?.denied ?? 0) > 0}
                />
              </div>

              {/* Latency + quota */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="rounded-lg border border-slate-200 bg-white p-4">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                    Latency &amp; reliability
                  </h3>
                  <div className="mt-2 flex gap-6">
                    <Metric label="p50" value={fmtMs(feed?.stats.p50_ms ?? null)} />
                    <Metric label="p95" value={fmtMs(feed?.stats.p95_ms ?? null)} />
                    <Metric
                      label="error rate"
                      value={`${((feed?.stats.error_rate ?? 0) * 100).toFixed(1)}%`}
                    />
                  </div>
                </div>
                <div className="rounded-lg border border-slate-200 bg-white p-4">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                    Quota
                  </h3>
                  <div className="mt-2 space-y-1 text-sm text-ink-700">
                    <div>
                      Requests:{" "}
                      <strong>
                        {quotaLabel(
                          usage?.quota.requests_per_day ?? 0,
                          usage?.quota.requests_remaining ?? null,
                        )}
                      </strong>
                    </div>
                    <div>
                      Tokens:{" "}
                      <strong>
                        {quotaLabel(
                          usage?.quota.tokens_per_day ?? 0,
                          usage?.quota.tokens_remaining ?? null,
                        )}
                      </strong>
                    </div>
                  </div>
                </div>
              </div>

              {/* Request feed */}
              <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
                <div className="px-4 py-2 border-b border-slate-200 text-xs font-semibold uppercase tracking-wide text-ink-500">
                  Recent requests ({feed?.requests.length ?? 0})
                </div>
                {feed && feed.requests.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="text-left text-xs text-ink-500 border-b border-slate-200">
                        <tr>
                          <th className="px-4 py-2 font-medium">When</th>
                          <th className="px-4 py-2 font-medium">Purpose</th>
                          <th className="px-4 py-2 font-medium">Model</th>
                          <th className="px-4 py-2 font-medium text-right">Tokens</th>
                          <th className="px-4 py-2 font-medium text-right">Latency</th>
                          <th className="px-4 py-2 font-medium">Status</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {feed.requests.map((r, i) => (
                          <tr key={i} className="hover:bg-slate-50">
                            <td className="px-4 py-2 text-ink-700 whitespace-nowrap">
                              {new Date(r.created_at).toLocaleString()}
                            </td>
                            <td className="px-4 py-2 text-ink-600">{r.purpose}</td>
                            <td className="px-4 py-2 text-ink-600 font-mono text-xs">
                              {r.model ?? "—"}
                            </td>
                            <td className="px-4 py-2 text-right tabular-nums">
                              {fmtInt(r.total_tokens)}
                            </td>
                            <td className="px-4 py-2 text-right tabular-nums">
                              {fmtMs(r.latency_ms)}
                            </td>
                            <td className="px-4 py-2">
                              <span
                                className={
                                  "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide " +
                                  (STATUS_BADGE[r.status] ?? "bg-slate-200 text-ink-700")
                                }
                                title={r.error ?? undefined}
                              >
                                {r.status}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="p-6 text-sm text-ink-500">
                    No requests in this window yet. Ask a question to see activity here.
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  alert,
}: {
  label: string;
  value: string;
  sub?: string;
  alert?: boolean;
}) {
  return (
    <div
      className={
        "rounded-lg border bg-white p-4 " +
        (alert ? "border-rose-300" : "border-slate-200")
      }
    >
      <div className="text-xs font-medium uppercase tracking-wide text-ink-500">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold text-ink-900">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-500">{sub}</div>}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-2xl font-semibold text-ink-900">{value}</div>
      <div className="text-xs text-ink-500">{label}</div>
    </div>
  );
}
