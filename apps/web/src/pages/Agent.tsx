import { useState } from "react";
import ReactMarkdown from "react-markdown";
import { Sidebar } from "../components/Sidebar";
import { runAgent, type AgentResponse } from "../lib/api";

const EXAMPLES = [
  "Find the capital requirements that apply to a small investment firm and summarise them.",
  "What does the FCA say about consumer duty? Pull the relevant guidance.",
  "List the most recently ingested documents and tell me what they cover.",
];

export function AgentPage() {
  const [goal, setGoal] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<AgentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function go(g: string) {
    const q = g.trim();
    if (!q || running) return;
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      setResult(await runAgent(q));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <h1 className="text-lg font-semibold">Agent</h1>
          <p className="text-xs text-ink-500">
            Give it a goal — it plans, calls tools over your corpus (search, fetch
            docs, summaries), and returns a grounded answer with its steps. Runs on
            your sovereign model.
          </p>
        </header>

        <div className="flex-1 overflow-y-auto p-6 bg-slate-50">
          <div className="max-w-3xl mx-auto">
            <div className="flex gap-2">
              <textarea
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) go(goal);
                }}
                rows={2}
                placeholder="What do you want the agent to do? (⌘/Ctrl+Enter to run)"
                className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ink-300"
              />
              <button
                onClick={() => go(goal)}
                disabled={running || !goal.trim()}
                className="rounded bg-ink-900 text-white text-sm px-4 hover:bg-ink-700 disabled:opacity-50"
              >
                {running ? "Working…" : "Run"}
              </button>
            </div>

            {!result && !running && !error && (
              <div className="mt-3 flex flex-wrap gap-2">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    onClick={() => {
                      setGoal(ex);
                      go(ex);
                    }}
                    className="text-xs rounded-full border border-slate-300 bg-white px-3 py-1 text-ink-600 hover:bg-slate-100"
                  >
                    {ex.length > 60 ? ex.slice(0, 60) + "…" : ex}
                  </button>
                ))}
              </div>
            )}

            {error && (
              <div className="mt-4 rounded bg-rose-50 border border-rose-200 p-3 text-sm text-rose-900">
                {error}
              </div>
            )}

            {running && (
              <div className="mt-4 text-sm text-ink-500">
                The agent is reasoning and calling tools…
              </div>
            )}

            {result && (
              <div className="mt-5 space-y-4">
                {/* Step trace */}
                <div className="rounded-lg border border-slate-200 bg-white">
                  <div className="px-4 py-2 border-b border-slate-200 text-xs font-semibold uppercase tracking-wide text-ink-500">
                    Reasoning — {result.steps.length} tool call
                    {result.steps.length === 1 ? "" : "s"} ·{" "}
                    {result.iterations} step{result.iterations === 1 ? "" : "s"}
                  </div>
                  {result.steps.length === 0 ? (
                    <div className="px-4 py-3 text-sm text-ink-500">
                      Answered directly (no tools needed).
                    </div>
                  ) : (
                    <ol className="divide-y divide-slate-100">
                      {result.steps.map((s, i) => (
                        <li key={i} className="px-4 py-3">
                          <div className="flex items-center gap-2 text-xs">
                            <span className="rounded bg-indigo-100 text-indigo-900 px-1.5 py-0.5 font-mono">
                              {s.tool}
                            </span>
                            <span className="text-ink-500 font-mono truncate">
                              {JSON.stringify(s.arguments)}
                            </span>
                          </div>
                          <div className="mt-1 text-xs text-ink-600 whitespace-pre-wrap line-clamp-4">
                            {s.result_preview}
                          </div>
                        </li>
                      ))}
                    </ol>
                  )}
                </div>

                {/* Final answer */}
                <div className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="text-xs font-semibold uppercase tracking-wide text-ink-500 mb-2">
                    Answer
                  </div>
                  <div className="prose prose-sm max-w-none text-ink-900">
                    <ReactMarkdown>{result.answer}</ReactMarkdown>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
