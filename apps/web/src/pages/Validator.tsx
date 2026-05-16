import { useEffect, useMemo, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  listDocuments,
  listRulePacks,
  runValidation,
  type DocumentRecord,
  type RulePackOut,
  type ValidateReportOut,
} from "../lib/api";

export function ValidatorPage() {
  const [docs, setDocs] = useState<DocumentRecord[]>([]);
  const [packs, setPacks] = useState<RulePackOut[]>([]);
  const [docId, setDocId] = useState<string>("");
  const [packId, setPackId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<ValidateReportOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRulePacks().then((p) => {
      setPacks(p);
      if (p[0]) setPackId(p[0].id);
    });
    listDocuments({ onlyActive: true, limit: 200, docType: "uploads" }).then((d) => {
      setDocs(d);
      if (d[0]) setDocId(d[0].id);
    });
  }, []);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!docId || !packId) {
      setError("Pick both a document and a rule pack.");
      return;
    }
    setBusy(true);
    setReport(null);
    try {
      const r = await runValidation({ document_id: docId, pack_id: packId });
      setReport(r);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const selectedPack = useMemo(
    () => packs.find((p) => p.id === packId),
    [packs, packId]
  );

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <h1 className="text-lg font-semibold">Compliance validator</h1>
          <p className="text-xs text-ink-500">
            Score a document against FCA Consumer Duty, HMRC AML, or UK GDPR
            requirements. Returns a traffic-light verdict per rule with cited
            evidence from your document.
          </p>
        </header>

        <div className="p-6 max-w-4xl">
          <form onSubmit={run} className="space-y-3">
            <label className="block">
              <span className="block text-xs font-medium text-ink-700">
                Document to validate
              </span>
              <select
                value={docId}
                onChange={(e) => setDocId(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              >
                <option value="">— pick a document —</option>
                {docs.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.title}
                  </option>
                ))}
              </select>
              {docs.length === 0 && (
                <span className="block text-xs text-ink-500 mt-1">
                  No uploaded documents yet. Use the upload button on the Chat
                  tab to add a policy / promotion / report to validate.
                </span>
              )}
            </label>

            <label className="block">
              <span className="block text-xs font-medium text-ink-700">
                Rule pack
              </span>
              <select
                value={packId}
                onChange={(e) => setPackId(e.target.value)}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              >
                {packs.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} — {p.version}
                  </option>
                ))}
              </select>
              {selectedPack && (
                <span className="block text-xs text-ink-500 mt-1">
                  {selectedPack.summary} · {selectedPack.requirements.length} requirements
                </span>
              )}
            </label>

            <button
              type="submit"
              disabled={busy || !docId || !packId}
              className="rounded-md bg-ink-900 px-4 py-2 text-sm font-medium text-white hover:bg-ink-700 disabled:opacity-50"
            >
              {busy ? `Scoring (${selectedPack?.requirements.length ?? 0} requirements)…` : "Run validation"}
            </button>
          </form>

          {error && (
            <div className="mt-4 rounded bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-800">
              {error}
            </div>
          )}

          {report && <ReportView report={report} />}
        </div>
      </main>
    </div>
  );
}

function ReportView({ report }: { report: ValidateReportOut }) {
  const verdictColor: Record<string, string> = {
    green: "bg-emerald-100 text-emerald-900 border-emerald-200",
    amber: "bg-amber-100 text-amber-900 border-amber-200",
    red: "bg-red-100 text-red-900 border-red-200",
    "n/a": "bg-slate-100 text-ink-500 border-slate-200",
  };
  const overallLabel: Record<string, string> = {
    green: "🟢 GREEN — meets requirements",
    amber: "🟡 AMBER — partial / weak coverage",
    red: "🔴 RED — material gaps",
  };

  return (
    <section className="mt-8">
      <div
        className={
          "rounded-lg border p-4 " +
          (verdictColor[report.overall] ?? verdictColor.amber)
        }
      >
        <div className="text-base font-semibold">
          {overallLabel[report.overall] ?? "Result"}
        </div>
        <div className="mt-1 text-sm">
          {report.document_title} · {report.pack_name} · {report.pack_version}
        </div>
        <div className="mt-2 text-xs">
          Score {(report.score * 100).toFixed(0)}% · Green {report.counts.green}{" "}
          · Amber {report.counts.amber} · Red {report.counts.red}
          {report.counts["n/a"] > 0 && ` · N/A ${report.counts["n/a"]}`} · Took{" "}
          {(report.latency_ms / 1000).toFixed(1)}s
        </div>
      </div>

      <ol className="mt-4 space-y-3">
        {report.requirements.map((r) => (
          <li
            key={r.requirement_id}
            className={
              "rounded-md border p-3 " +
              (verdictColor[r.verdict] ?? verdictColor.amber)
            }
          >
            <div className="flex items-start gap-2">
              <span
                className={
                  "inline-block rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide " +
                  (r.verdict === "green"
                    ? "bg-emerald-700 text-white"
                    : r.verdict === "amber"
                      ? "bg-amber-700 text-white"
                      : r.verdict === "red"
                        ? "bg-red-700 text-white"
                        : "bg-slate-400 text-white")
                }
              >
                {r.verdict}
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-ink-900">
                  [{r.requirement_id}] {r.title}
                </div>
                <div className="text-xs text-ink-600">
                  {r.citation} · severity: {r.severity}
                </div>
                <p className="mt-1 text-sm text-ink-800">{r.rationale}</p>
                {r.evidence_excerpts.length > 0 && (
                  <details className="mt-2">
                    <summary className="text-xs underline cursor-pointer text-ink-700">
                      Cited evidence ({r.evidence_excerpts.length})
                    </summary>
                    <ul className="mt-1 space-y-1">
                      {r.evidence_excerpts.map((ex, i) => (
                        <li
                          key={i}
                          className="text-xs italic bg-white/60 rounded p-2 text-ink-800"
                        >
                          "{ex.text}"
                          {(ex.page != null || ex.section_path) && (
                            <span className="not-italic text-ink-500 ml-2">
                              {ex.page != null && `· p.${ex.page}`}
                              {ex.section_path && ` · ${ex.section_path}`}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
