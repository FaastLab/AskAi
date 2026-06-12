import { useEffect, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  deleteIndexer,
  enablePreset,
  getIndexerRuns,
  listIndexers,
  listPresets,
  runIndexer,
  type IngestIndexer,
  type IngestPreset,
  type IngestRun,
} from "../lib/api";
import { loadAuth } from "../lib/auth";

const STATUS_BADGE: Record<string, string> = {
  ok: "bg-emerald-100 text-emerald-900",
  error: "bg-rose-100 text-rose-900",
  running: "bg-blue-100 text-blue-900",
};

const CATEGORY_LABEL: Record<string, string> = {
  fca: "FCA",
  pra: "PRA",
  boe: "Bank of England",
  hmrc: "HMRC",
  ico: "ICO",
  tpr: "TPR",
  fos: "FOS",
};

function fmtWhen(iso?: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "never";
}

export function DataSourcesPage() {
  const isOwner = loadAuth()?.user.role === "owner";
  const [presets, setPresets] = useState<IngestPreset[]>([]);
  const [indexers, setIndexers] = useState<IngestIndexer[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      const [p, ix] = await Promise.all([listPresets(), listIndexers()]);
      setPresets(p);
      setIndexers(ix);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isOwner) refresh();
  }, [isOwner]);

  async function onEnable(p: IngestPreset) {
    setBusy(p.key);
    setToast(null);
    try {
      await enablePreset(p.key);
      setToast(`Enabled "${p.name}". Use "Run now" below to crawl it into your corpus.`);
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  async function onRun(ix: IngestIndexer) {
    setBusy(ix.id);
    setToast(null);
    try {
      await runIndexer(ix.id);
      setToast(`Crawl queued for "${ix.name}". Run history updates when the worker finishes.`);
      setTimeout(refresh, 5000);
    } catch (err) {
      setToast((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function onDelete(ix: IngestIndexer) {
    if (!window.confirm(`Remove indexer "${ix.name}"? Already-ingested documents stay in your corpus.`)) return;
    await deleteIndexer(ix.id);
    await refresh();
  }

  if (!isOwner) {
    return (
      <div className="flex h-dvh">
        <Sidebar />
        <main className="flex-1 p-6">
          <div className="rounded bg-amber-50 border border-amber-300 p-4 text-sm text-amber-900 max-w-2xl">
            Only owners can manage data sources.
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
          <h1 className="text-lg font-semibold">Data sources</h1>
          <p className="text-xs text-ink-500">
            Turn on a regulator and we'll crawl its published rules into your
            corpus — citation-only, Open Government Licence. Your own uploads stay
            private.
          </p>
        </header>

        {toast && (
          <div className="bg-blue-50 border-b border-blue-200 px-6 py-2 text-sm text-blue-900 flex items-center gap-3">
            <span className="flex-1">{toast}</span>
            <button onClick={() => setToast(null)} className="text-blue-700 hover:text-blue-900">×</button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-6 bg-slate-50 space-y-8">
          {loading ? (
            <div className="text-sm text-ink-500">Loading…</div>
          ) : (
            <div className="max-w-4xl mx-auto space-y-8">
              {/* Presets */}
              <section>
                <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500 mb-3">
                  Regulator presets
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {presets.map((p) => (
                    <div
                      key={p.key}
                      className="rounded-lg border border-slate-200 bg-white p-4 flex flex-col"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="font-medium text-ink-900">{p.name}</div>
                          <span className="inline-block mt-0.5 rounded bg-slate-200 px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
                            {CATEGORY_LABEL[p.category] ?? p.category}
                          </span>
                          <span className="ml-1 text-[10px] text-ink-400 uppercase">{p.license}</span>
                        </div>
                        {p.enabled ? (
                          <span className="shrink-0 rounded-full bg-emerald-100 text-emerald-900 px-2 py-0.5 text-[11px] font-medium">
                            ✓ Enabled
                          </span>
                        ) : (
                          <button
                            onClick={() => onEnable(p)}
                            disabled={busy === p.key}
                            className="shrink-0 rounded-md bg-ink-900 px-3 py-1.5 text-xs text-white hover:bg-ink-700 disabled:opacity-50"
                          >
                            {busy === p.key ? "Enabling…" : "Enable"}
                          </button>
                        )}
                      </div>
                      <p className="mt-2 text-xs text-ink-600 flex-1">{p.description}</p>
                      <div className="mt-2 text-[11px] text-ink-400">
                        {p.start_url_count} source URL{p.start_url_count === 1 ? "" : "s"} · {p.kind}
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              {/* Indexers */}
              <section>
                <h2 className="text-sm font-semibold uppercase tracking-wide text-ink-500 mb-3">
                  Your indexers
                </h2>
                {indexers.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-ink-500">
                    None yet. Enable a regulator preset above to create one.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {indexers.map((ix) => (
                      <div key={ix.id} className="rounded-lg border border-slate-200 bg-white">
                        <div className="flex items-center gap-3 px-4 py-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-ink-900 truncate">{ix.name}</span>
                              {ix.category && (
                                <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] uppercase">
                                  {CATEGORY_LABEL[ix.category] ?? ix.category}
                                </span>
                              )}
                            </div>
                            <div className="mt-0.5 text-xs text-ink-500">
                              last run {fmtWhen(ix.last_run_at)}
                            </div>
                          </div>
                          {ix.last_run && (
                            <span
                              className={
                                "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide " +
                                (STATUS_BADGE[ix.last_run.status] ?? "bg-slate-200 text-ink-700")
                              }
                              title={ix.last_run.error ?? undefined}
                            >
                              {ix.last_run.status} · {ix.last_run.ingested}/{ix.last_run.pages}
                            </span>
                          )}
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => onRun(ix)}
                              disabled={busy === ix.id}
                              className="rounded bg-emerald-600 px-2.5 py-1.5 text-xs text-white hover:bg-emerald-700 disabled:opacity-50"
                            >
                              {busy === ix.id ? "…" : "Run now"}
                            </button>
                            <button
                              onClick={() => setExpanded(expanded === ix.id ? null : ix.id)}
                              className="rounded px-2 py-1.5 text-xs text-ink-600 hover:bg-slate-100"
                            >
                              {expanded === ix.id ? "Hide" : "History"}
                            </button>
                            <button
                              onClick={() => onDelete(ix)}
                              className="rounded px-2 py-1.5 text-xs text-rose-600 hover:bg-rose-50"
                            >
                              Remove
                            </button>
                          </div>
                        </div>
                        {expanded === ix.id && (
                          <div className="border-t border-slate-100 px-4 py-3">
                            <RunHistory indexerId={ix.id} />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function RunHistory({ indexerId }: { indexerId: string }) {
  const [runs, setRuns] = useState<IngestRun[] | null>(null);
  useEffect(() => {
    getIndexerRuns(indexerId).then(setRuns);
  }, [indexerId]);

  if (runs === null) return <div className="text-sm text-ink-500">Loading…</div>;
  if (runs.length === 0)
    return <div className="text-sm text-ink-500">No runs yet — click "Run now".</div>;

  return (
    <table className="w-full text-xs">
      <thead className="text-left text-ink-500 border-b border-slate-200">
        <tr>
          <th className="py-1 font-medium">When</th>
          <th className="py-1 font-medium">Status</th>
          <th className="py-1 font-medium text-right">Pages</th>
          <th className="py-1 font-medium text-right">Ingested</th>
          <th className="py-1 font-medium text-right">Skipped</th>
          <th className="py-1 font-medium text-right">Failed</th>
          <th className="py-1 font-medium text-right">Duration</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100">
        {runs.map((r) => (
          <tr key={r.run_id} title={r.error ?? undefined}>
            <td className="py-1.5 text-ink-700">{fmtWhen(r.finished_at ?? r.started_at)}</td>
            <td className="py-1.5">
              <span
                className={
                  "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase " +
                  (STATUS_BADGE[r.status] ?? "bg-slate-200 text-ink-700")
                }
              >
                {r.status}
              </span>
            </td>
            <td className="py-1.5 text-right tabular-nums">{r.pages}</td>
            <td className="py-1.5 text-right tabular-nums text-emerald-700">{r.ingested}</td>
            <td className="py-1.5 text-right tabular-nums">{r.skipped}</td>
            <td className="py-1.5 text-right tabular-nums text-rose-700">{r.failed}</td>
            <td className="py-1.5 text-right tabular-nums">
              {r.duration_ms != null ? (r.duration_ms / 1000).toFixed(1) + "s" : "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
