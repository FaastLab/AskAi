import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Sidebar } from "../components/Sidebar";
import {
  getConfig,
  getDocumentFileUrl,
  listDocumentCounts,
  listDocuments,
  searchChunks,
  summariseDocument,
  type DocumentRecord,
  type PublicConfig,
  type SearchHit,
} from "../lib/api";

// Stable ordering for the regulator chips. Anything not listed here falls
// back to "Other". `uploads` is the user's own files; `all` shows everything.
const CHIPS: { key: string; label: string }[] = [
  { key: "all", label: "All" },
  { key: "fca", label: "FCA" },
  { key: "boe", label: "BoE" },
  { key: "pra", label: "PRA" },
  { key: "pra-sol-ii", label: "PRA Solvency II" },
  { key: "hmrc", label: "HMRC" },
  { key: "tpr", label: "TPR" },
  { key: "ico", label: "ICO" },
  { key: "fos-decision", label: "FOS decisions" },
  { key: "uploads", label: "Your uploads" },
];
import { loadSettings } from "../lib/settings";

type Mode = "browse" | "search";

export function DocumentsPage() {
  const navigate = useNavigate();
  const { documentId: selectedFromUrl } = useParams();

  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [docs, setDocs] = useState<DocumentRecord[]>([]);
  const [docsLoading, setDocsLoading] = useState(true);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [activeChip, setActiveChip] = useState<string>("all");

  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState<string | null>(null);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  // Per-user toggle: rerank ON = higher precision, ~5-15s slower on CPU.
  // Shared localStorage key with Chat page so the choice carries across.
  const [useRerank, setUseRerank] = useState<boolean>(
    () => (typeof window !== "undefined"
      ? window.localStorage.getItem("askai.rerank") !== "off"
      : true),
  );
  const toggleRerank = () => {
    setUseRerank((prev) => {
      const next = !prev;
      try { window.localStorage.setItem("askai.rerank", next ? "on" : "off"); } catch { /* ignore */ }
      return next;
    });
  };

  const [selectedId, setSelectedId] = useState<string | null>(
    selectedFromUrl ?? null
  );
  const searchAbortRef = useRef<AbortController | null>(null);

  // Load config + document list on mount.
  useEffect(() => {
    getConfig().then(setConfig);
  }, []);

  // Fetch the full document set once, filter client-side by chip. This
  // keeps `docsById` complete so search hits from other regulators still
  // resolve to a known document — only the browse list is narrowed.
  useEffect(() => {
    let cancelled = false;
    setDocsLoading(true);
    listDocuments({ onlyActive: true, limit: 500 })
      .then((d) => {
        if (!cancelled) setDocs(d);
      })
      .finally(() => {
        if (!cancelled) setDocsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Counts power the chip badges (and tell us which chips to disable).
  useEffect(() => {
    let cancelled = false;
    listDocumentCounts().then((c) => {
      if (!cancelled) setCounts(c);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Keep URL in sync with selection (so users can share /documents/{id}).
  useEffect(() => {
    if (selectedId && selectedId !== selectedFromUrl) {
      navigate(`/documents/${selectedId}`, { replace: true });
    } else if (!selectedId && selectedFromUrl) {
      navigate("/documents", { replace: true });
    }
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reflect URL → state on initial load / back nav.
  useEffect(() => {
    setSelectedId(selectedFromUrl ?? null);
  }, [selectedFromUrl]);

  const blockedByByok =
    !!config?.require_byok && !loadSettings().openaiApiKey;

  const mode: Mode = submittedQuery ? "search" : "browse";

  const docsById = useMemo(() => {
    const map = new Map<string, DocumentRecord>();
    for (const d of docs) map.set(d.id, d);
    return map;
  }, [docs]);

  // Client-side filter applied to the BROWSE list only — search hits
  // still resolve against the full `docsById` map above.
  const filteredDocs = useMemo(() => {
    if (activeChip === "all") return docs;
    if (activeChip === "uploads") {
      return docs.filter((d) => d.source_uri.startsWith("upload://"));
    }
    return docs.filter((d) => d.doc_type === activeChip);
  }, [docs, activeChip]);

  // Group search hits by document, preserving best-rank ordering.
  const hitsByDoc = useMemo(() => {
    const groups: { doc: DocumentRecord | null; docId: string; hits: SearchHit[] }[] = [];
    const seen = new Map<string, number>();
    for (const h of hits) {
      const existing = seen.get(h.document_id);
      if (existing === undefined) {
        seen.set(h.document_id, groups.length);
        groups.push({ doc: docsById.get(h.document_id) ?? null, docId: h.document_id, hits: [h] });
      } else {
        groups[existing].hits.push(h);
      }
    }
    return groups;
  }, [hits, docsById]);

  async function runSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) {
      setSubmittedQuery(null);
      setHits([]);
      setLatencyMs(null);
      setSearchError(null);
      return;
    }
    if (blockedByByok) {
      setSearchError(
        "This deployment requires your own OpenAI key — open the chat tab and paste it via the gear icon."
      );
      return;
    }
    searchAbortRef.current?.abort();
    const ctl = new AbortController();
    searchAbortRef.current = ctl;
    setSearchBusy(true);
    setSearchError(null);
    setSubmittedQuery(q);
    // Clear the previously-selected document so the right pane goes back
    // to the "select a hit" empty state. Users were confused seeing a
    // stale doc's View internal / source / summary while a fresh search
    // was running on the left.
    setSelectedId(null);
    try {
      const result = await searchChunks(q, { k: 12, onlyActive: true, rerank: useRerank });
      if (ctl.signal.aborted) return;
      if (!result) {
        setSearchError("Search failed — check your OpenAI key or try again.");
        setHits([]);
        setLatencyMs(null);
        return;
      }
      setHits(result.hits);
      setLatencyMs(result.latency_ms);
    } catch (err) {
      if (!ctl.signal.aborted) {
        setSearchError(`Search error: ${(err as Error).message}`);
        setHits([]);
      }
    } finally {
      if (!ctl.signal.aborted) setSearchBusy(false);
    }
  }

  function clearSearch() {
    searchAbortRef.current?.abort();
    setQuery("");
    setSubmittedQuery(null);
    setHits([]);
    setLatencyMs(null);
    setSearchError(null);
    setSelectedId(null);
  }

  const selectedDoc = selectedId ? docsById.get(selectedId) ?? null : null;

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-lg font-semibold">Knowledge base</h1>
              <p className="text-xs text-ink-500">
                {docsLoading
                  ? "Loading documents…"
                  : activeChip === "all"
                    ? `${docs.length} document${docs.length === 1 ? "" : "s"} indexed`
                    : `${filteredDocs.length} of ${docs.length} document${
                        docs.length === 1 ? "" : "s"
                      } · filter: ${activeChip.toUpperCase()}`}
                {config?.default_tenant && ` · tenant: ${config.default_tenant}`}
              </p>
            </div>
          </div>
          <form onSubmit={runSearch} className="mt-3 flex items-center gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder='Search across all documents — e.g. "consumer duty cross-cutting rules"'
              className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ink-900/20"
              disabled={searchBusy}
            />
            <button
              type="submit"
              disabled={searchBusy || !query.trim()}
              className="rounded-md bg-ink-900 px-4 py-2 text-sm text-white hover:bg-ink-700 disabled:opacity-50"
            >
              {searchBusy ? "Searching…" : "Search"}
            </button>
            {submittedQuery && (
              <button
                type="button"
                onClick={clearSearch}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-100"
              >
                Clear
              </button>
            )}
            <button
              type="button"
              onClick={toggleRerank}
              disabled={searchBusy}
              className={
                "rounded-md px-3 py-2 text-xs font-medium border transition-colors " +
                (useRerank
                  ? "bg-emerald-50 border-emerald-300 text-emerald-800 hover:bg-emerald-100"
                  : "bg-amber-50 border-amber-300 text-amber-800 hover:bg-amber-100")
              }
              title={
                useRerank
                  ? "Reranker ON — best precision, slower on CPU (~15-25s)"
                  : "Reranker OFF — faster (~5-10s), lower precision on tight queries"
              }
            >
              {useRerank ? "Rerank: ON · Quality" : "Rerank: OFF · Fast"}
            </button>
          </form>
          {searchError && (
            <div className="mt-2 rounded bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
              {searchError}
            </div>
          )}
          {mode === "search" && latencyMs != null && (
            <div className="mt-2 text-xs text-ink-500">
              {hits.length} match{hits.length === 1 ? "" : "es"} across{" "}
              {hitsByDoc.length} document{hitsByDoc.length === 1 ? "" : "s"}
              {" · "}
              {latencyMs.toFixed(0)} ms
            </div>
          )}
        </header>

        {/* Category chips — regulator filter */}
        <div className="border-b border-slate-200 bg-white px-6 py-2 flex items-center gap-2 overflow-x-auto">
          {CHIPS.map((c) => {
            const count =
              c.key === "all" ? counts.total ?? 0 : counts[c.key] ?? 0;
            const active = activeChip === c.key;
            const disabled = c.key !== "all" && count === 0;
            return (
              <button
                key={c.key}
                type="button"
                disabled={disabled}
                onClick={() => setActiveChip(c.key)}
                className={
                  "shrink-0 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition " +
                  (active
                    ? "bg-ink-900 text-white"
                    : disabled
                      ? "bg-slate-100 text-ink-400 cursor-not-allowed"
                      : "bg-white border border-slate-300 text-ink-700 hover:bg-slate-100")
                }
                title={disabled ? "No documents in this category yet" : ""}
              >
                {c.label}
                <span
                  className={
                    "rounded-full px-1.5 py-0.5 text-[10px] tabular-nums " +
                    (active
                      ? "bg-white/20"
                      : "bg-slate-200 text-ink-700")
                  }
                >
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        <div className="flex-1 flex min-h-0">
          {/* Left: list */}
          <div className="w-2/5 max-w-md border-r border-slate-200 overflow-y-auto">
            {mode === "browse" ? (
              <BrowseList
                docs={filteredDocs}
                loading={docsLoading}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            ) : (
              <SearchList
                groups={hitsByDoc}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            )}
          </div>

          {/* Right: detail */}
          <div className="flex-1 overflow-y-auto bg-slate-50">
            {selectedDoc ? (
              <DocumentDetail
                doc={selectedDoc}
                searchHits={
                  mode === "search"
                    ? hits.filter((h) => h.document_id === selectedDoc.id)
                    : []
                }
              />
            ) : (
              <EmptyDetail />
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

// ----------------------------------------------------------------------------

function BrowseList({
  docs,
  loading,
  selectedId,
  onSelect,
}: {
  docs: DocumentRecord[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (loading) {
    return <div className="p-4 text-sm text-ink-500">Loading…</div>;
  }
  if (docs.length === 0) {
    return (
      <div className="p-6 text-sm text-ink-500">
        No documents yet. Use the upload button in the Chat view to ingest one.
      </div>
    );
  }
  return (
    <ul className="divide-y divide-slate-200">
      {docs.map((d) => (
        <li key={d.id}>
          <button
            onClick={() => onSelect(d.id)}
            className={`w-full text-left px-4 py-3 hover:bg-slate-50 ${
              selectedId === d.id ? "bg-slate-100" : ""
            }`}
          >
            <div className="text-sm font-medium text-ink-900 line-clamp-2">
              {d.title}
            </div>
            <div className="mt-1 text-xs text-ink-500 flex items-center gap-2 flex-wrap">
              {sourceBadge(d)}
              {d.doc_type && (
                <span className="rounded bg-slate-200 px-1.5 py-0.5 uppercase tracking-wide text-[10px]">
                  {d.doc_type}
                </span>
              )}
              {d.size_bytes != null && d.size_bytes > 0 && (
                <span className="text-ink-500">{formatBytes(d.size_bytes)}</span>
              )}
              {d.effective_date && (
                <span>
                  effective {new Date(d.effective_date).toLocaleDateString()}
                </span>
              )}
              <span className="text-ink-400">
                added {new Date(d.created_at).toLocaleDateString()}
              </span>
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function sourceBadge(d: DocumentRecord) {
  const isUpload = d.source_uri.startsWith("upload://");
  if (isUpload) {
    return (
      <span className="rounded bg-indigo-100 text-indigo-900 px-1.5 py-0.5 text-[10px] font-medium">
        Your firm
      </span>
    );
  }
  return (
    <span className="rounded bg-emerald-100 text-emerald-900 px-1.5 py-0.5 text-[10px] font-medium">
      Regulator
    </span>
  );
}

function SearchList({
  groups,
  selectedId,
  onSelect,
}: {
  groups: { doc: DocumentRecord | null; docId: string; hits: SearchHit[] }[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  if (groups.length === 0) {
    return (
      <div className="p-6 text-sm text-ink-500">
        No matches. Try shorter or more general terms.
      </div>
    );
  }
  return (
    <ul className="divide-y divide-slate-200">
      {groups.map((g) => (
        <li key={g.docId}>
          <button
            onClick={() => onSelect(g.docId)}
            className={`w-full text-left px-4 py-3 hover:bg-slate-50 ${
              selectedId === g.docId ? "bg-slate-100" : ""
            }`}
          >
            <div className="text-sm font-medium text-ink-900 line-clamp-2">
              {g.doc?.title ?? "(unknown document)"}
            </div>
            <div className="mt-1 text-xs text-ink-500 flex items-center gap-2 flex-wrap">
              <span className="rounded bg-emerald-100 text-emerald-900 px-1.5 py-0.5 text-[10px] font-medium">
                {g.hits.length} hit{g.hits.length === 1 ? "" : "s"}
              </span>
              {g.doc?.doc_type && (
                <span className="rounded bg-slate-200 px-1.5 py-0.5 uppercase tracking-wide text-[10px]">
                  {g.doc.doc_type}
                </span>
              )}
              <span className="text-ink-400">
                top score {g.hits[0].score.toFixed(3)}
              </span>
            </div>
            <div className="mt-2 text-xs text-ink-600 line-clamp-2 italic">
              "{g.hits[0].content.slice(0, 180)}…"
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function DocumentDetail({
  doc,
  searchHits,
}: {
  doc: DocumentRecord;
  searchHits: SearchHit[];
}) {
  const sourceIsHttp =
    doc.source_uri.startsWith("http://") || doc.source_uri.startsWith("https://");

  // "View internal copy" mints a fresh signed URL on click rather than
  // pre-fetching on render. The signed token is short-lived (5 min) and
  // single-doc-scoped, so it's safe to embed in the new-tab URL.
  const [viewBusy, setViewBusy] = useState(false);
  const [viewError, setViewError] = useState<string | null>(null);

  async function openInternalCopy() {
    if (viewBusy) return;
    setViewBusy(true);
    setViewError(null);
    try {
      const url = await getDocumentFileUrl(doc.id);
      if (!url) {
        setViewError(
          "Could not generate a download link — your session may have expired. Try logging in again."
        );
        return;
      }
      // Open in a new tab so the user keeps the Documents page open.
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (err) {
      setViewError((err as Error).message || "Failed to open document.");
    } finally {
      setViewBusy(false);
    }
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <h2 className="text-xl font-semibold text-ink-900">{doc.title}</h2>
      <div className="mt-2 text-xs text-ink-500 flex items-center gap-3 flex-wrap">
        {doc.doc_type && (
          <span className="rounded bg-slate-200 px-2 py-0.5 uppercase tracking-wide">
            {doc.doc_type}
          </span>
        )}
        {doc.version && <span>v{doc.version}</span>}
        {doc.effective_date && (
          <span>effective {new Date(doc.effective_date).toLocaleDateString()}</span>
        )}
        {doc.size_bytes != null && doc.size_bytes > 0 && (
          <span title="Original file size">
            {formatBytes(doc.size_bytes)}
          </span>
        )}
        <span className="text-ink-400">
          indexed {new Date(doc.created_at).toLocaleDateString()}
        </span>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={openInternalCopy}
          disabled={viewBusy}
          className={
            "inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm text-white " +
            (viewBusy ? "bg-ink-700 opacity-70 cursor-wait" : "bg-ink-900 hover:bg-ink-700")
          }
          title="Open the original file the indexer parsed"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
          </svg>
          {viewBusy ? "Opening…" : "View internal copy"}
        </button>
        {sourceIsHttp && (
          <a
            href={doc.source_uri}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-100"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" />
              <line x1="10" y1="14" x2="21" y2="3" />
            </svg>
            View on source site
          </a>
        )}
        <span
          className="inline-flex items-center text-xs text-ink-500 px-2"
          title="Source URI recorded at ingest time"
        >
          source: {doc.source_uri.length > 60 ? doc.source_uri.slice(0, 57) + "…" : doc.source_uri}
        </span>
      </div>
      {viewError && (
        <p className="mt-2 text-xs text-red-700">{viewError}</p>
      )}

      {searchHits.length > 0 && (
        <section className="mt-6">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
            Matches in this document
          </h3>
          <ol className="mt-2 space-y-3">
            {searchHits.map((h, i) => (
              <li
                key={h.id}
                className="rounded-md border border-slate-200 bg-white p-3"
              >
                <div className="flex items-center justify-between text-xs text-ink-500">
                  <span>
                    [{i + 1}]
                    {h.page_number != null && ` · p.${h.page_number}`}
                    {h.section_path && ` · ${h.section_path}`}
                  </span>
                  <span>score {h.score.toFixed(3)}</span>
                </div>
                <p className="mt-2 text-sm text-ink-800 whitespace-pre-wrap">
                  {h.content}
                </p>
              </li>
            ))}
          </ol>
        </section>
      )}

      {doc.summary ? (
        <section className="mt-6">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
            Summary
          </h3>
          <p className="mt-2 text-sm text-ink-800 whitespace-pre-wrap">
            {doc.summary}
          </p>
        </section>
      ) : (
        // No summary yet — offer to generate it (runs on the worker via the
        // deployment's default LLM). New uploads auto-summarise; this covers
        // older docs ingested before that was enabled.
        <SummariseButton documentId={doc.id} />
      )}

      {doc.keyphrases && doc.keyphrases.length > 0 && (
        <section className="mt-6">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
            Key phrases
          </h3>
          <ul className="mt-2 flex flex-wrap gap-2">
            {doc.keyphrases.map((k) => (
              <li
                key={k}
                className="rounded-full bg-white border border-slate-200 px-3 py-1 text-xs text-ink-700"
              >
                {k}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function SummariseButton({ documentId }: { documentId: string }) {
  // idle → click → queued. The job runs async on the worker, so we just confirm
  // it's queued and tell the user to refresh; we don't poll.
  const [state, setState] = useState<"idle" | "working" | "queued">("idle");
  return (
    <section className="mt-6">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
        Summary
      </h3>
      {state === "queued" ? (
        <p className="mt-2 text-sm text-ink-600">
          Generating summary &amp; keyphrases on the server — refresh in ~30s.
        </p>
      ) : (
        <button
          onClick={async () => {
            setState("working");
            const ok = await summariseDocument(documentId);
            setState(ok ? "queued" : "idle");
          }}
          disabled={state === "working"}
          className="mt-2 rounded-md bg-ink-900 px-3 py-2 text-sm text-white hover:bg-ink-700 disabled:opacity-50"
        >
          {state === "working" ? "Queuing…" : "Generate summary & keyphrases"}
        </button>
      )}
    </section>
  );
}

function EmptyDetail() {
  return (
    <div className="h-full flex items-center justify-center text-sm text-ink-500 p-6 text-center">
      <div>
        <div className="text-2xl mb-2">📄</div>
        <div>
          Select a document on the left to view its summary, key phrases,
          source link, and a preview of the original file.
        </div>
      </div>
    </div>
  );
}
