import { useEffect, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  auditCsvUrl,
  getAuditEntry,
  listAudit,
  type AuditEntry,
  type AuditEntryDetail,
} from "../lib/api";
import { loadAuth } from "../lib/auth";

const ACTION_FILTERS = [
  { key: "", label: "All actions" },
  { key: "ask", label: "Asked AI" },
  { key: "search", label: "Searched" },
  { key: "validate", label: "Validated" },
  { key: "upload", label: "Uploaded" },
  { key: "login", label: "Login" },
  { key: "signup", label: "Signup" },
];

const ACTION_BADGE: Record<string, string> = {
  ask: "bg-indigo-100 text-indigo-900",
  search: "bg-sky-100 text-sky-900",
  validate: "bg-emerald-100 text-emerald-900",
  upload: "bg-amber-100 text-amber-900",
  login: "bg-slate-200 text-ink-700",
  signup: "bg-violet-100 text-violet-900",
};

export function AuditPage() {
  const auth = loadAuth();
  const isOwnerOrAdmin =
    auth?.user.role === "owner" || auth?.user.role === "admin";

  const [items, setItems] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState("");
  const [q, setQ] = useState("");
  const [days, setDays] = useState(30);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<AuditEntryDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const limit = 50;

  useEffect(() => {
    if (!isOwnerOrAdmin) return;
    let cancelled = false;
    setLoading(true);
    listAudit({
      action: action || undefined,
      q: q || undefined,
      days,
      limit,
      offset: page * limit,
    })
      .then((p) => {
        if (cancelled) return;
        setItems(p.items);
        setTotal(p.total);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [action, q, days, page, isOwnerOrAdmin]);

  async function openDetail(id: number) {
    setLoadingDetail(true);
    setSelected(null);
    try {
      const d = await getAuditEntry(id);
      setSelected(d);
    } finally {
      setLoadingDetail(false);
    }
  }

  if (!isOwnerOrAdmin) {
    return (
      <div className="flex h-dvh">
        <Sidebar />
        <main className="flex-1 p-6">
          <div className="rounded bg-amber-50 border border-amber-300 p-4 text-sm text-amber-900 max-w-2xl">
            Only owners and admins can view the audit trail.
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div>
              <h1 className="text-lg font-semibold">Audit trail</h1>
              <p className="text-xs text-ink-500">
                Every question asked, validation run, document uploaded, and
                login event in <strong>{auth?.user.tenant_name}</strong>.
                Suitable for FCA / internal audit packs.
              </p>
            </div>
            <a
              href={auditCsvUrl(days)}
              className="rounded-md bg-ink-900 text-white text-sm px-3 py-2 hover:bg-ink-700"
            >
              Export CSV
            </a>
          </div>
          <div className="mt-3 flex items-center gap-2 flex-wrap">
            <select
              value={action}
              onChange={(e) => { setAction(e.target.value); setPage(0); }}
              className="rounded-md border border-slate-300 px-2 py-1 text-sm"
            >
              {ACTION_FILTERS.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </select>
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") setPage(0); }}
              placeholder="Search query/response text…"
              className="rounded-md border border-slate-300 px-3 py-1 text-sm flex-1 max-w-md"
            />
            <select
              value={days}
              onChange={(e) => { setDays(Number(e.target.value)); setPage(0); }}
              className="rounded-md border border-slate-300 px-2 py-1 text-sm"
            >
              <option value={1}>Last 24h</option>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
              <option value={365}>Last year</option>
            </select>
            <span className="text-xs text-ink-500 ml-auto">
              {total} event{total === 1 ? "" : "s"}
            </span>
          </div>
        </header>

        <div className="flex-1 flex min-h-0">
          {/* List */}
          <div className="w-3/5 border-r border-slate-200 overflow-y-auto">
            {loading ? (
              <div className="p-6 text-sm text-ink-500">Loading…</div>
            ) : items.length === 0 ? (
              <div className="p-6 text-sm text-ink-500">
                No events match these filters. Try widening the date range.
              </div>
            ) : (
              <ul className="divide-y divide-slate-200">
                {items.map((it) => (
                  <li key={it.id}>
                    <button
                      onClick={() => openDetail(it.id)}
                      className={`w-full text-left px-4 py-3 hover:bg-slate-50 ${
                        selected?.id === it.id ? "bg-slate-100" : ""
                      }`}
                    >
                      <div className="flex items-center gap-2 flex-wrap text-xs text-ink-500">
                        <span className="text-ink-700 font-medium">
                          {new Date(it.created_at).toLocaleString()}
                        </span>
                        <span
                          className={
                            "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide " +
                            (ACTION_BADGE[it.action] ?? "bg-slate-200 text-ink-700")
                          }
                        >
                          {it.action}
                        </span>
                        <span>{it.user_email || it.user_id.slice(0, 8)}</span>
                        {it.latency_ms != null && (
                          <span className="text-ink-400">
                            {(it.latency_ms / 1000).toFixed(1)}s
                          </span>
                        )}
                        {it.source_count > 0 && (
                          <span className="text-ink-500">
                            {it.source_count} source{it.source_count === 1 ? "" : "s"}
                          </span>
                        )}
                      </div>
                      {it.query && (
                        <div className="mt-1 text-sm text-ink-900 line-clamp-2">
                          {it.query}
                        </div>
                      )}
                      {it.response_summary && (
                        <div className="mt-0.5 text-xs text-ink-600 line-clamp-2 italic">
                          → {it.response_summary}
                        </div>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {(total > limit || page > 0) && (
              <div className="p-4 flex items-center justify-between text-xs">
                <button
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  className="rounded px-3 py-1 border border-slate-300 disabled:opacity-50"
                >
                  ← Prev
                </button>
                <span>
                  Page {page + 1} of {Math.max(1, Math.ceil(total / limit))}
                </span>
                <button
                  disabled={(page + 1) * limit >= total}
                  onClick={() => setPage((p) => p + 1)}
                  className="rounded px-3 py-1 border border-slate-300 disabled:opacity-50"
                >
                  Next →
                </button>
              </div>
            )}
          </div>

          {/* Detail */}
          <div className="flex-1 overflow-y-auto bg-slate-50">
            {loadingDetail ? (
              <div className="p-6 text-sm text-ink-500">Loading…</div>
            ) : !selected ? (
              <div className="h-full flex items-center justify-center text-sm text-ink-500 p-6 text-center">
                Select an event to see its full detail.
              </div>
            ) : (
              <DetailView entry={selected} />
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

function DetailView({ entry }: { entry: AuditEntryDetail }) {
  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center gap-2 flex-wrap text-xs">
        <span
          className={
            "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide " +
            (ACTION_BADGE[entry.action] ?? "bg-slate-200 text-ink-700")
          }
        >
          {entry.action}
        </span>
        <span className="text-ink-700 font-medium">
          {new Date(entry.created_at).toLocaleString()}
        </span>
        <span className="text-ink-500">·</span>
        <span className="text-ink-500">
          {entry.user_email || entry.user_id}
        </span>
        {entry.latency_ms != null && (
          <>
            <span className="text-ink-500">·</span>
            <span className="text-ink-500">
              {(entry.latency_ms / 1000).toFixed(2)}s
            </span>
          </>
        )}
      </div>

      {entry.resource && (
        <div className="mt-2 text-xs text-ink-500 font-mono">{entry.resource}</div>
      )}

      {entry.query && (
        <section className="mt-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
            Query
          </h3>
          <p className="mt-1 rounded bg-white border border-slate-200 px-3 py-2 text-sm whitespace-pre-wrap">
            {entry.query}
          </p>
        </section>
      )}

      {entry.response_summary && (
        <section className="mt-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
            Response summary
          </h3>
          <p className="mt-1 rounded bg-white border border-slate-200 px-3 py-2 text-sm whitespace-pre-wrap">
            {entry.response_summary}
          </p>
        </section>
      )}

      {entry.sources.length > 0 && (
        <section className="mt-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
            Sources / citations ({entry.sources.length})
          </h3>
          <ol className="mt-1 space-y-1">
            {entry.sources.map((s, i) => (
              <li
                key={i}
                className="rounded bg-white border border-slate-200 px-3 py-2 text-xs font-mono"
              >
                {JSON.stringify(s)}
              </li>
            ))}
          </ol>
        </section>
      )}

      {Object.keys(entry.extra).length > 0 && (
        <section className="mt-4">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
            Metadata
          </h3>
          <pre className="mt-1 rounded bg-white border border-slate-200 p-3 text-xs font-mono overflow-x-auto">
            {JSON.stringify(entry.extra, null, 2)}
          </pre>
        </section>
      )}
    </div>
  );
}
