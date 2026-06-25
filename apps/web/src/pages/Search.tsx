import { useEffect, useMemo, useRef, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  getDocumentFileUrl,
  instantSearch,
  listDocuments,
  searchChunks,
  type DocumentRecord,
  type InstantCounts,
  type SearchHit,
} from "../lib/api";

export function SearchPage() {
  const [q, setQ] = useState("");
  const [docType, setDocType] = useState<string | null>(null);
  const [counts, setCounts] = useState<InstantCounts | null>(null);
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [docs, setDocs] = useState<DocumentRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Resolve hit document_ids to full document records for the detail panel.
  useEffect(() => {
    listDocuments({ onlyActive: true, limit: 500 }).then(setDocs);
  }, []);

  // Live counts on every keystroke (debounced). Keyword-only on the server →
  // sub-50ms, the Typesense "search-as-you-type" show-off.
  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current);
    if (!q.trim()) {
      setCounts(null);
      return;
    }
    debounce.current = setTimeout(() => {
      instantSearch(q).then(setCounts);
    }, 150);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [q]);

  async function runFull() {
    const query = q.trim();
    if (!query || running) return;
    setRunning(true);
    setSelectedId(null);
    try {
      const result = await searchChunks(query, { k: 20 });
      setHits(result?.hits ?? []);
      setLatencyMs(result?.latency_ms ?? null);
    } finally {
      setRunning(false);
    }
  }

  const docsById = useMemo(() => {
    const m = new Map<string, DocumentRecord>();
    for (const d of docs) m.set(d.id, d);
    return m;
  }, [docs]);

  // Group hits by document, preserving best-rank order.
  const hitsByDoc = useMemo(() => {
    const groups: { doc: DocumentRecord | null; docId: string; hits: SearchHit[] }[] = [];
    const seen = new Map<string, number>();
    for (const h of hits) {
      const at = seen.get(h.document_id);
      if (at === undefined) {
        seen.set(h.document_id, groups.length);
        groups.push({ doc: docsById.get(h.document_id) ?? null, docId: h.document_id, hits: [h] });
      } else {
        groups[at].hits.push(h);
      }
    }
    return groups;
  }, [hits, docsById]);

  // Click a doc_type chip → narrow the grouped results to that type.
  const visibleGroups = useMemo(
    () =>
      docType === null
        ? hitsByDoc
        : hitsByDoc.filter((g) => g.doc?.doc_type === docType),
    [hitsByDoc, docType],
  );

  const selectedDoc = selectedId ? docsById.get(selectedId) ?? null : null;

  // Chip facet counts. Once a full (semantic) search has run, count DOCUMENTS
  // per doc_type from the ACTUAL results so the chips match "N across M
  // documents" and filter correctly. Before any results, fall back to the live
  // keyword facet counts from instantSearch (the as-you-type preview).
  const resultFacets = useMemo(() => {
    const m: Record<string, number> = {};
    for (const g of hitsByDoc) {
      const t = g.doc?.doc_type;
      if (t) m[t] = (m[t] ?? 0) + 1;
    }
    return m;
  }, [hitsByDoc]);
  const docTypeFacets =
    hits.length > 0 ? resultFacets : counts?.facets?.doc_type ?? {};
  const facetEntries = Object.entries(docTypeFacets).sort((a, b) => b[1] - a[1]);

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <h1 className="text-lg font-semibold">Search</h1>
          <p className="text-xs text-ink-500">
            Instant keyword + semantic search over your corpus. Match counts update
            as you type; press Enter for grouped results with citations.
          </p>

          {/* Search bar with the live count on the right */}
          <div className="relative mt-3">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runFull()}
              autoFocus
              placeholder="Search your documents…"
              className="w-full rounded-lg border border-slate-300 pl-4 pr-32 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ink-300"
            />
            {counts && (
              <div className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-ink-500">
                {counts.supported ? (
                  <span>
                    <span className="font-semibold text-ink-800">
                      {counts.found.toLocaleString()}
                    </span>{" "}
                    keyword match{counts.found === 1 ? "" : "es"}
                  </span>
                ) : (
                  <span className="text-ink-400" title="Enable RETRIEVER=typesense">
                    live count off
                  </span>
                )}
              </div>
            )}
          </div>

          {/* doc_type facet chips with live counts */}
          {facetEntries.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                onClick={() => setDocType(null)}
                className={`text-xs rounded-full px-3 py-1 border ${
                  docType === null
                    ? "border-ink-900 bg-ink-900 text-white"
                    : "border-slate-300 bg-white text-ink-600 hover:bg-slate-100"
                }`}
              >
                All
              </button>
              {facetEntries.map(([type, n]) => (
                <button
                  key={type}
                  onClick={() => setDocType(docType === type ? null : type)}
                  className={`text-xs rounded-full px-3 py-1 border ${
                    docType === type
                      ? "border-ink-900 bg-ink-900 text-white"
                      : "border-slate-300 bg-white text-ink-600 hover:bg-slate-100"
                  }`}
                >
                  {type}{" "}
                  <span className={docType === type ? "text-slate-300" : "text-ink-400"}>
                    {n.toLocaleString()}
                  </span>
                </button>
              ))}
              <button
                onClick={runFull}
                disabled={running || !q.trim()}
                className="ml-auto rounded bg-ink-900 text-white text-xs px-4 py-1.5 hover:bg-ink-700 disabled:opacity-50"
              >
                {running ? "Searching…" : "Search"}
              </button>
            </div>
          )}
          {hits.length > 0 && latencyMs != null && (
            <div className="mt-2 text-xs text-ink-500">
              {hits.length} match{hits.length === 1 ? "" : "es"} across{" "}
              {hitsByDoc.length} document{hitsByDoc.length === 1 ? "" : "s"} ·{" "}
              {latencyMs.toFixed(0)} ms
            </div>
          )}
        </header>

        {/* Grouped master / detail */}
        <div className="flex-1 flex min-h-0">
          <div className="w-2/5 max-w-md border-r border-slate-200 overflow-y-auto">
            {hits.length === 0 ? (
              <div className="p-6 text-sm text-ink-500">
                Type a query and press Enter (or click Search) to see results grouped
                by document.
              </div>
            ) : (
              <SearchList
                groups={visibleGroups}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            )}
          </div>
          <div className="flex-1 overflow-y-auto bg-slate-50">
            {selectedDoc ? (
              <DocumentDetail
                doc={selectedDoc}
                searchHits={hits.filter((h) => h.document_id === selectedDoc.id)}
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
              <span className="text-ink-400">top score {g.hits[0].score.toFixed(3)}</span>
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
  const [viewBusy, setViewBusy] = useState(false);
  const [viewError, setViewError] = useState<string | null>(null);

  async function openInternalCopy() {
    if (viewBusy) return;
    setViewBusy(true);
    setViewError(null);
    try {
      const url = await getDocumentFileUrl(doc.id);
      if (!url) {
        setViewError("Could not generate a download link — try logging in again.");
        return;
      }
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
          <span title="Original file size">{formatBytes(doc.size_bytes)}</span>
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
      {viewError && <p className="mt-2 text-xs text-red-700">{viewError}</p>}

      {searchHits.length > 0 && (
        <section className="mt-6">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
            Matches in this document
          </h3>
          <ol className="mt-2 space-y-3">
            {searchHits.map((h, i) => (
              <li key={h.id} className="rounded-md border border-slate-200 bg-white p-3">
                <div className="flex items-center justify-between text-xs text-ink-500">
                  <span>
                    [{i + 1}]
                    {h.page_number != null && ` · p.${h.page_number}`}
                    {h.section_path && ` · ${h.section_path}`}
                  </span>
                  <span>score {h.score.toFixed(3)}</span>
                </div>
                <p className="mt-2 text-sm text-ink-800 whitespace-pre-wrap">{h.content}</p>
              </li>
            ))}
          </ol>
        </section>
      )}

      {doc.summary && (
        <section className="mt-6">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-500">
            Summary
          </h3>
          <p className="mt-2 text-sm text-ink-800 whitespace-pre-wrap">{doc.summary}</p>
        </section>
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

function EmptyDetail() {
  return (
    <div className="h-full flex items-center justify-center text-sm text-ink-500 p-6 text-center">
      <div>
        <div className="text-2xl mb-2">📄</div>
        <div>
          Select a document on the left to view its source links, citations, summary
          and key phrases.
        </div>
      </div>
    </div>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}
