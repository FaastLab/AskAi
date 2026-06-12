import { useEffect, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  createConnector,
  deleteConnector,
  listConnectors,
  runConnector,
  updateConnector,
  type ConnectorInput,
  type WebConnector,
} from "../lib/api";
import { loadAuth } from "../lib/auth";

const STATUS_BADGE: Record<string, string> = {
  ok: "bg-emerald-100 text-emerald-900",
  error: "bg-rose-100 text-rose-900",
  running: "bg-blue-100 text-blue-900",
};

const EMPTY: ConnectorInput = {
  name: "",
  mode: "crawl",
  start_urls: [],
  url_prefix: null,
  include: [],
  exclude: [],
  max_pages: 50,
  max_depth: 2,
  doc_type: null,
  enabled: true,
  schedule_interval_minutes: null,
};

function fmtWhen(iso?: string | null): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString();
}

export function ConnectorsPage() {
  const auth = loadAuth();
  const isOwner = auth?.user.role === "owner";

  const [connectors, setConnectors] = useState<WebConnector[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<WebConnector | "new" | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      setConnectors(await listConnectors());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (isOwner) refresh();
  }, [isOwner]);

  async function onRun(c: WebConnector) {
    setToast(null);
    try {
      await runConnector(c.id);
      setToast(`Crawl queued for "${c.name}". Results appear in its run history shortly.`);
      // Give the worker a moment, then refresh to surface the new run.
      setTimeout(refresh, 4000);
    } catch (err) {
      setToast((err as Error).message);
    }
  }

  async function onDelete(c: WebConnector) {
    if (!window.confirm(`Delete connector "${c.name}"? Its run history is removed too.`)) return;
    await deleteConnector(c.id);
    await refresh();
  }

  if (!isOwner) {
    return (
      <div className="flex h-dvh">
        <Sidebar />
        <main className="flex-1 p-6">
          <div className="rounded bg-amber-50 border border-amber-300 p-4 text-sm text-amber-900 max-w-2xl">
            Only owners can manage web connectors.
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
            <h1 className="text-lg font-semibold">Web connectors</h1>
            <p className="text-xs text-ink-500">
              Crawl websites, sitemaps, and manual child-pages into your corpus on a
              schedule — no CLI needed.
            </p>
          </div>
          <button
            onClick={() => setEditing("new")}
            className="rounded-md bg-ink-900 px-3 py-2 text-sm text-white hover:bg-ink-700"
          >
            + New connector
          </button>
        </header>

        {toast && (
          <div className="bg-blue-50 border-b border-blue-200 px-6 py-2 text-sm text-blue-900 flex items-center gap-3">
            <span className="flex-1">{toast}</span>
            <button onClick={() => setToast(null)} className="text-blue-700 hover:text-blue-900">×</button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-6 bg-slate-50 space-y-4">
          {loading ? (
            <div className="text-sm text-ink-500">Loading…</div>
          ) : connectors.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-ink-500">
              No connectors yet. Create one to crawl e.g. an HMRC manual's child pages
              into your knowledge base.
            </div>
          ) : (
            <div className="max-w-4xl mx-auto space-y-3">
              {connectors.map((c) => {
                const lastRun = c.runs?.[0];
                return (
                  <div key={c.id} className="rounded-lg border border-slate-200 bg-white">
                    <div className="flex items-center gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-ink-900 truncate">{c.name}</span>
                          <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
                            {c.mode}
                          </span>
                          {!c.enabled && (
                            <span className="rounded bg-slate-100 text-ink-500 px-1.5 py-0.5 text-[10px]">
                              disabled
                            </span>
                          )}
                          {c.schedule_interval_minutes && (
                            <span className="rounded bg-indigo-100 text-indigo-900 px-1.5 py-0.5 text-[10px]">
                              every {c.schedule_interval_minutes}m
                            </span>
                          )}
                        </div>
                        <div className="mt-0.5 text-xs text-ink-500 truncate">
                          {c.start_urls[0] ?? "(no start URL)"}
                          {c.start_urls.length > 1 && ` +${c.start_urls.length - 1} more`}
                          {" · last run "}
                          {fmtWhen(c.last_run_at)}
                        </div>
                      </div>
                      {lastRun && (
                        <span
                          className={
                            "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide " +
                            (STATUS_BADGE[lastRun.status] ?? "bg-slate-200 text-ink-700")
                          }
                        >
                          {lastRun.status} · {lastRun.ingested}/{lastRun.pages}
                        </span>
                      )}
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => onRun(c)}
                          className="rounded bg-emerald-600 px-2.5 py-1.5 text-xs text-white hover:bg-emerald-700"
                          title="Run crawl now"
                        >
                          Run now
                        </button>
                        <button
                          onClick={() => setExpanded(expanded === c.id ? null : c.id)}
                          className="rounded px-2 py-1.5 text-xs text-ink-600 hover:bg-slate-100"
                        >
                          {expanded === c.id ? "Hide" : "History"}
                        </button>
                        <button
                          onClick={() => setEditing(c)}
                          className="rounded px-2 py-1.5 text-xs text-ink-600 hover:bg-slate-100"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => onDelete(c)}
                          className="rounded px-2 py-1.5 text-xs text-rose-600 hover:bg-rose-50"
                        >
                          Delete
                        </button>
                      </div>
                    </div>

                    {expanded === c.id && (
                      <div className="border-t border-slate-100 px-4 py-3">
                        <RunHistory runs={c.runs ?? []} />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>

      {editing && (
        <ConnectorModal
          connector={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await refresh();
          }}
        />
      )}
    </div>
  );
}

function RunHistory({ runs }: { runs: WebConnector["runs"] }) {
  if (!runs || runs.length === 0) {
    return <div className="text-sm text-ink-500">No runs yet. Click "Run now" to crawl.</div>;
  }
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
            <td className="py-1.5 text-ink-700">{fmtWhen(r.finished_at)}</td>
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
            <td className="py-1.5 text-right tabular-nums">{(r.duration_ms / 1000).toFixed(1)}s</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ConnectorModal({
  connector,
  onClose,
  onSaved,
}: {
  connector: WebConnector | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<ConnectorInput>(
    connector
      ? {
          name: connector.name,
          mode: connector.mode,
          start_urls: connector.start_urls,
          url_prefix: connector.url_prefix,
          include: connector.include,
          exclude: connector.exclude,
          max_pages: connector.max_pages,
          max_depth: connector.max_depth,
          doc_type: connector.doc_type,
          enabled: connector.enabled,
          schedule_interval_minutes: connector.schedule_interval_minutes,
        }
      : EMPTY,
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof ConnectorInput>(key: K, value: ConnectorInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }
  const linesToList = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

  async function save() {
    if (!form.name.trim() || form.start_urls.length === 0) {
      setError("A name and at least one start URL are required.");
      return;
    }
    setSaving(true);
    setError(null);
    const result = connector
      ? await updateConnector(connector.id, form)
      : await createConnector(form);
    setSaving(false);
    if (!result) {
      setError("Save failed. Check the fields and try again.");
      return;
    }
    onSaved();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-slate-200">
          <h2 className="text-sm font-semibold">
            {connector ? "Edit connector" : "New connector"}
          </h2>
        </div>
        <div className="p-5 space-y-3 text-sm">
          <Field label="Name">
            <input
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              className="w-full rounded border border-slate-300 px-3 py-2"
              placeholder="HMRC Capital Gains Manual"
            />
          </Field>
          <Field label="Mode">
            <select
              value={form.mode}
              onChange={(e) => set("mode", e.target.value as ConnectorInput["mode"])}
              className="w-full rounded border border-slate-300 px-3 py-2"
            >
              <option value="crawl">Crawl — follow child links under a prefix</option>
              <option value="sitemap">Sitemap — expand a sitemap.xml</option>
              <option value="page">Page — fetch only the start URLs</option>
            </select>
          </Field>
          <Field label="Start URLs (one per line)">
            <textarea
              value={form.start_urls.join("\n")}
              onChange={(e) => set("start_urls", linesToList(e.target.value))}
              rows={2}
              className="w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
              placeholder="https://www.gov.uk/hmrc-internal-manuals/capital-gains-manual"
            />
          </Field>
          {form.mode === "crawl" && (
            <Field label="URL prefix (crawl scope — defaults to start URL's folder)">
              <input
                value={form.url_prefix ?? ""}
                onChange={(e) => set("url_prefix", e.target.value || null)}
                className="w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
                placeholder="https://www.gov.uk/hmrc-internal-manuals/capital-gains-manual"
              />
            </Field>
          )}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Max pages">
              <input
                type="number"
                value={form.max_pages}
                onChange={(e) => set("max_pages", Number(e.target.value))}
                className="w-full rounded border border-slate-300 px-3 py-2"
              />
            </Field>
            <Field label="Max depth (crawl)">
              <input
                type="number"
                value={form.max_depth}
                onChange={(e) => set("max_depth", Number(e.target.value))}
                className="w-full rounded border border-slate-300 px-3 py-2"
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Include (substrings, one per line)">
              <textarea
                value={form.include.join("\n")}
                onChange={(e) => set("include", linesToList(e.target.value))}
                rows={2}
                className="w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
                placeholder="/capital-gains-manual/"
              />
            </Field>
            <Field label="Exclude (substrings)">
              <textarea
                value={form.exclude.join("\n")}
                onChange={(e) => set("exclude", linesToList(e.target.value))}
                rows={2}
                className="w-full rounded border border-slate-300 px-3 py-2 font-mono text-xs"
                placeholder="/print"
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Doc type label (optional)">
              <input
                value={form.doc_type ?? ""}
                onChange={(e) => set("doc_type", e.target.value || null)}
                className="w-full rounded border border-slate-300 px-3 py-2"
                placeholder="hmrc"
              />
            </Field>
            <Field label="Schedule every (minutes, blank = manual)">
              <input
                type="number"
                value={form.schedule_interval_minutes ?? ""}
                onChange={(e) =>
                  set(
                    "schedule_interval_minutes",
                    e.target.value ? Number(e.target.value) : null,
                  )
                }
                className="w-full rounded border border-slate-300 px-3 py-2"
                placeholder="1440"
              />
            </Field>
          </div>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(e) => set("enabled", e.target.checked)}
            />
            <span>Enabled (scheduled runs only fire when enabled)</span>
          </label>
          {error && <div className="rounded bg-rose-50 border border-rose-200 px-3 py-2 text-rose-800">{error}</div>}
        </div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-slate-200">
          <button onClick={onClose} className="rounded px-3 py-2 text-sm text-ink-600 hover:bg-slate-100">
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="rounded bg-ink-900 px-3 py-2 text-sm text-white hover:bg-ink-700 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs text-ink-500 mb-1">{label}</label>
      {children}
    </div>
  );
}
