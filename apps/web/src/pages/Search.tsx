import { useEffect, useRef, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  instantSearch,
  searchChunks,
  type InstantCounts,
  type SearchResult,
} from "../lib/api";

export function SearchPage() {
  const [q, setQ] = useState("");
  const [docType, setDocType] = useState<string | null>(null);
  const [counts, setCounts] = useState<InstantCounts | null>(null);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [running, setRunning] = useState(false);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Live counts on every keystroke (debounced ~150ms). Keyword-only on the
  // server, so it stays sub-50ms even on a big corpus.
  useEffect(() => {
    if (debounce.current) clearTimeout(debounce.current);
    if (!q.trim()) {
      setCounts(null);
      return;
    }
    debounce.current = setTimeout(() => {
      instantSearch(q, docType ?? undefined).then(setCounts);
    }, 150);
    return () => {
      if (debounce.current) clearTimeout(debounce.current);
    };
  }, [q, docType]);

  async function runFull() {
    const query = q.trim();
    if (!query || running) return;
    setRunning(true);
    setResult(null);
    try {
      setResult(await searchChunks(query, { k: 20, docType: docType ?? undefined }));
    } finally {
      setRunning(false);
    }
  }

  const docTypeFacets = counts?.facets?.doc_type ?? {};
  const facetEntries = Object.entries(docTypeFacets).sort((a, b) => b[1] - a[1]);

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <h1 className="text-lg font-semibold">Search</h1>
          <p className="text-xs text-ink-500">
            Instant keyword + semantic search over your corpus. Match counts update
            as you type; press Enter for ranked results.
          </p>
        </header>

        <div className="flex-1 overflow-y-auto p-6 bg-slate-50">
          <div className="max-w-3xl mx-auto">
            {/* Search bar with the live count on the right */}
            <div className="relative">
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && runFull()}
                autoFocus
                placeholder="Search your documents…"
                className="w-full rounded-lg border border-slate-300 pl-4 pr-32 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-ink-300"
              />
              {/* Live match count — the Typesense show-off */}
              {counts && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-ink-500">
                  {counts.supported ? (
                    <span>
                      <span className="font-semibold text-ink-800">
                        {counts.found.toLocaleString()}
                      </span>{" "}
                      match{counts.found === 1 ? "" : "es"}
                    </span>
                  ) : (
                    <span className="text-ink-400" title="Enable RETRIEVER=typesense">
                      live count off
                    </span>
                  )}
                </div>
              )}
            </div>

            {/* doc_type facet chips with counts */}
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
                    <span
                      className={docType === type ? "text-slate-300" : "text-ink-400"}
                    >
                      {n.toLocaleString()}
                    </span>
                  </button>
                ))}
              </div>
            )}

            <div className="mt-3">
              <button
                onClick={runFull}
                disabled={running || !q.trim()}
                className="rounded bg-ink-900 text-white text-sm px-4 py-1.5 hover:bg-ink-700 disabled:opacity-50"
              >
                {running ? "Searching…" : "Search"}
              </button>
            </div>

            {/* Ranked results */}
            {result && (
              <div className="mt-5 space-y-2">
                <div className="text-xs text-ink-500">
                  {result.hits.length} ranked result
                  {result.hits.length === 1 ? "" : "s"} · {result.latency_ms}ms
                </div>
                {result.hits.map((h) => (
                  <div
                    key={h.id}
                    className="rounded-lg border border-slate-200 bg-white p-3"
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      {/* Document title → click through to the document */}
                      <a
                        href={`/documents/${h.document_id}`}
                        className="text-sm font-medium text-ink-900 hover:underline truncate"
                        title={h.document_title || "Untitled document"}
                      >
                        {h.document_title || "Untitled document"}
                      </a>
                      <span className="text-xs text-ink-400 shrink-0">
                        score {h.score.toFixed(3)}
                      </span>
                    </div>
                    <div className="text-[11px] text-ink-500 mb-1">
                      {h.section_path ? `${h.section_path} · ` : ""}
                      {h.page_number ? `p.${h.page_number}` : ""}
                    </div>
                    <div className="text-sm text-ink-700 line-clamp-4">{h.content}</div>
                  </div>
                ))}
                {result.hits.length === 0 && (
                  <div className="text-sm text-ink-500">No results.</div>
                )}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
