import { useEffect, useRef, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  createFolderSource,
  deleteIndexer,
  enablePreset,
  getEnrichment,
  getEnrichmentStatus,
  getIndexerRuns,
  listIndexers,
  listPresets,
  runIndexer,
  setEnrichment,
  summariseMissing,
  uploadToSource,
  type EnrichmentStatus,
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
  const [showNew, setShowNew] = useState(false);
  // Per-indexer hidden <input type=file> refs, so each folder card's "Upload"
  // button can open its own picker.
  const uploadRefs = useRef<Record<string, HTMLInputElement | null>>({});

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

  // Create a custom folder data source (+ its indexer). The new indexer then
  // shows in "Your indexers" with an Upload button.
  async function onCreateFolder(name: string, intervalMinutes: number | null) {
    setBusy("new");
    setToast(null);
    try {
      const res = await createFolderSource({
        name,
        schedule_interval_minutes: intervalMinutes,
      });
      if (!res) {
        setToast("Could not create the data source.");
        return;
      }
      setShowNew(false);
      setToast(
        intervalMinutes
          ? `Created "${name}". Upload files into it — it auto-indexes every ${intervalMinutes} min (or hit Run now).`
          : `Created "${name}". Upload files into it, then click Run now to index them.`,
      );
      await refresh();
    } finally {
      setBusy(null);
    }
  }

  // Upload files into a folder source's prefix. They index on the next run
  // (scheduled or "Run now") — we nudge a refresh so the run history updates.
  async function onUpload(ix: IngestIndexer, files: FileList | null) {
    if (!files || files.length === 0 || !ix.source_id) return;
    setBusy(ix.id);
    setToast(null);
    try {
      const res = await uploadToSource(ix.source_id, files);
      if (!res) {
        setToast("Upload failed.");
        return;
      }
      setToast(
        `Uploaded ${res.uploaded} file(s) to "${ix.name}". They'll be indexed on the next run — click Run now to do it immediately.`,
      );
    } finally {
      setBusy(null);
    }
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
        <header className="border-b border-slate-200 bg-white px-6 py-3 flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h1 className="text-lg font-semibold">Data sources</h1>
            <p className="text-xs text-ink-500">
              Create a folder, upload documents, and an indexer ingests them on a
              schedule — then search and ask with citations. Or turn on a regulator
              preset.
            </p>
          </div>
          <button
            onClick={() => setShowNew(true)}
            className="rounded-md bg-ink-900 px-3 py-2 text-sm text-white hover:bg-ink-700"
          >
            + New data source
          </button>
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
              {/* Enrichment — auto summaries + keyphrases */}
              <EnrichmentPanel />

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
                    None yet. Click <strong>+ New data source</strong> to create a
                    folder and upload documents, or enable a regulator preset above.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {indexers.map((ix) => (
                      <div key={ix.id} className="rounded-lg border border-slate-200 bg-white">
                        <div className="flex items-center gap-3 px-4 py-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-ink-900 truncate">{ix.name}</span>
                              {ix.kind === "folder" ? (
                                <span className="rounded bg-indigo-100 text-indigo-900 px-1.5 py-0.5 text-[10px] uppercase">
                                  Folder
                                </span>
                              ) : ix.category ? (
                                <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] uppercase">
                                  {CATEGORY_LABEL[ix.category] ?? ix.category}
                                </span>
                              ) : null}
                              {ix.schedule?.interval_minutes ? (
                                <span className="rounded bg-emerald-50 text-emerald-800 border border-emerald-200 px-1.5 py-0.5 text-[10px]">
                                  every {ix.schedule.interval_minutes}m
                                </span>
                              ) : (
                                <span className="rounded bg-slate-100 text-ink-500 px-1.5 py-0.5 text-[10px]">
                                  manual
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
                            {/* Upload is only meaningful for folder sources —
                                you drop files in, the indexer ingests them. */}
                            {ix.kind === "folder" && (
                              <>
                                <button
                                  onClick={() => uploadRefs.current[ix.id]?.click()}
                                  disabled={busy === ix.id}
                                  className="rounded bg-ink-900 px-2.5 py-1.5 text-xs text-white hover:bg-ink-700 disabled:opacity-50"
                                >
                                  Upload
                                </button>
                                <input
                                  ref={(el) => {
                                    uploadRefs.current[ix.id] = el;
                                  }}
                                  type="file"
                                  multiple
                                  className="hidden"
                                  onChange={(e) => {
                                    onUpload(ix, e.target.files);
                                    e.target.value = "";
                                  }}
                                />
                              </>
                            )}
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

      {showNew && (
        <NewSourceForm
          busy={busy === "new"}
          onCancel={() => setShowNew(false)}
          onCreate={onCreateFolder}
        />
      )}
    </div>
  );
}

function NewSourceForm({
  busy,
  onCancel,
  onCreate,
}: {
  busy: boolean;
  onCancel: () => void;
  onCreate: (name: string, intervalMinutes: number | null) => void;
}) {
  const [name, setName] = useState("");
  // Schedule choices in minutes; 0 = manual only. Short intervals make the live
  // demo snappy (the worker picks it up within a minute).
  const [interval, setInterval] = useState<number>(5);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onCancel}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-slate-200">
          <h2 className="text-sm font-semibold">New folder data source</h2>
        </div>
        <div className="p-5 space-y-4 text-sm">
          <div>
            <label className="block text-xs text-ink-500 mb-1">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Indian Railway standards"
              className="w-full rounded border border-slate-300 px-3 py-2"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs text-ink-500 mb-1">
              Auto-index schedule
            </label>
            <select
              value={interval}
              onChange={(e) => setInterval(Number(e.target.value))}
              className="w-full rounded border border-slate-300 px-3 py-2"
            >
              <option value={0}>Manual only (Run now)</option>
              <option value={5}>Every 5 minutes</option>
              <option value={15}>Every 15 minutes</option>
              <option value={60}>Every hour</option>
              <option value={1440}>Every day</option>
            </select>
            <p className="mt-1 text-[11px] text-ink-400">
              The indexer parses + chunks + embeds every file you upload into this
              folder. Pick a short interval for the demo, or use Run now.
            </p>
          </div>
          {/* The skillset that will run — shown so the setup story is complete. */}
          <div className="rounded-md bg-slate-50 border border-slate-200 px-3 py-2 text-[11px] text-ink-500">
            <span className="font-medium text-ink-700">Skillset:</span> Standard —
            parse → clean → chunk → extract metadata → embed.
          </div>
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-200">
          <button onClick={onCancel} className="rounded px-3 py-2 text-sm text-ink-600 hover:bg-slate-100">
            Cancel
          </button>
          <button
            onClick={() => name.trim() && onCreate(name.trim(), interval || null)}
            disabled={busy || !name.trim()}
            className="rounded bg-ink-900 px-3 py-2 text-sm text-white hover:bg-ink-700 disabled:opacity-50"
          >
            {busy ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

function EnrichmentPanel() {
  // Self-contained: loads the toggle + the enriched/total status, lets the
  // owner flip auto-enrichment and kick a one-off backfill of the remainder.
  const [auto, setAuto] = useState<boolean | null>(null);
  const [status, setStatus] = useState<EnrichmentStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function refresh() {
    const [s, st] = await Promise.all([getEnrichment(), getEnrichmentStatus()]);
    if (s) setAuto(s.auto);
    setStatus(st);
  }
  useEffect(() => {
    refresh();
  }, []);

  async function toggle() {
    setBusy(true);
    const res = await setEnrichment(!auto);
    if (res) setAuto(res.auto);
    setBusy(false);
  }

  async function enrichRemaining() {
    setBusy(true);
    setNote(null);
    const queued = await summariseMissing();
    setNote(`Queued ${queued} document(s) — summaries appear as they finish.`);
    setBusy(false);
    setTimeout(refresh, 4000);
  }

  const pct =
    status && status.total > 0
      ? Math.round((status.enriched / status.total) * 100)
      : 0;

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-sm font-semibold text-ink-900">Document enrichment</h2>
          <p className="text-xs text-ink-500 mt-0.5 max-w-xl">
            Auto-generate a summary &amp; keyphrases for every document, using your
            configured model. ~1 model call per document.
          </p>
        </div>
        {/* Toggle */}
        <button
          onClick={toggle}
          disabled={busy || auto === null}
          className={
            "shrink-0 rounded-full px-3 py-1.5 text-xs font-medium border transition-colors " +
            (auto
              ? "bg-emerald-50 border-emerald-300 text-emerald-800"
              : "bg-slate-50 border-slate-300 text-ink-600")
          }
        >
          {auto === null ? "…" : auto ? "Auto-enrich: ON" : "Auto-enrich: OFF"}
        </button>
      </div>

      {status && status.total > 0 && (
        <div className="mt-3">
          <div className="flex items-center justify-between text-xs text-ink-500">
            <span>
              {status.enriched} / {status.total} enriched
            </span>
            {status.pending > 0 && (
              <button
                onClick={enrichRemaining}
                disabled={busy}
                className="rounded-md bg-ink-900 px-2.5 py-1 text-xs text-white hover:bg-ink-700 disabled:opacity-50"
              >
                Enrich remaining ({status.pending})
              </button>
            )}
          </div>
          <div className="mt-1 h-2 rounded-full bg-slate-100 overflow-hidden">
            <div className="h-full bg-emerald-500" style={{ width: `${pct}%` }} />
          </div>
        </div>
      )}
      {note && <p className="mt-2 text-xs text-blue-700">{note}</p>}
    </section>
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
