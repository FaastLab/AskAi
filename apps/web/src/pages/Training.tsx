import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Sidebar } from "../components/Sidebar";
import {
  generateTraining,
  listTrainingRecords,
  saveTrainingModule,
  type TrainingGenerateResponse,
  type TrainingKind,
  type TrainingRecord,
} from "../lib/api";

const KINDS: { value: TrainingKind; label: string; hint: string }[] = [
  { value: "blended", label: "Blended module", hint: "Lesson + quiz + scenario" },
  { value: "lesson", label: "Lesson", hint: "Grounded training material" },
  { value: "scenario", label: "Scenario", hint: "Story → conversation → report" },
  { value: "exam", label: "Exam", hint: "Q&A with model answers + marks" },
  { value: "quiz", label: "Quiz", hint: "Auto-gradable MCQs" },
  { value: "revision_guide", label: "Revision guide", hint: "Concise recap" },
  { value: "flashcards", label: "Flashcards", hint: "Front/back cards" },
  { value: "slides", label: "Slides", hint: "Deck outline" },
];

const EXAMPLES = [
  "Anti-money laundering: identifying and reporting suspicious activity",
  "Consumer Duty: acting to deliver good outcomes for retail customers",
  "Conflicts of interest and personal account dealing",
];

// A sensible default rubric so free-text exam/scenario submissions can be graded
// out of the box. The user can refine criteria later via the module record.
const DEFAULT_RUBRIC = {
  items: [
    {
      key: "identification",
      description: "Correctly identifies the issue / warning signs",
      max_points: 10,
      weight: 1,
    },
    {
      key: "action",
      description: "Follows the correct reporting / escalation procedure",
      max_points: 10,
      weight: 1,
    },
    {
      key: "accuracy",
      description: "Answer is accurate and grounded in the relevant rules",
      max_points: 10,
      weight: 1,
    },
  ],
};

export function TrainingPage() {
  const [tab, setTab] = useState<"generate" | "records">("generate");
  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-200 bg-white px-6 py-3 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">Compliance training</h1>
            <p className="text-xs text-ink-500">
              Generate corpus-grounded training, exams and scenarios from your
              ingested rules — then assess staff and keep an audit-grade record.
              Runs on your sovereign model.
            </p>
          </div>
          <div className="flex gap-1 text-sm">
            <button
              onClick={() => setTab("generate")}
              className={`rounded px-3 py-1 ${tab === "generate" ? "bg-ink-900 text-white" : "text-ink-600 hover:bg-slate-100"}`}
            >
              Generate
            </button>
            <button
              onClick={() => setTab("records")}
              className={`rounded px-3 py-1 ${tab === "records" ? "bg-ink-900 text-white" : "text-ink-600 hover:bg-slate-100"}`}
            >
              Records
            </button>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-6 bg-slate-50">
          <div className="max-w-3xl mx-auto">
            {tab === "generate" ? <GenerateView /> : <RecordsView />}
          </div>
        </div>
      </main>
    </div>
  );
}

function GenerateView() {
  const [topic, setTopic] = useState("");
  const [kind, setKind] = useState<TrainingKind>("blended");
  const [numQuestions, setNumQuestions] = useState(5);
  const [difficulty, setDifficulty] = useState("mixed");
  const [examples, setExamples] = useState("");
  const [role, setRole] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<TrainingGenerateResponse | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function go(t: string) {
    const q = t.trim();
    if (!q || running) return;
    setRunning(true);
    setError(null);
    setResult(null);
    setSaved(null);
    try {
      setResult(
        await generateTraining({
          topic: q,
          kind,
          num_questions: numQuestions,
          difficulty,
          example_questions: kind === "exam" ? examples || null : null,
          role: kind === "scenario" ? role || null : null,
          include_scenario: true,
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  async function save() {
    if (!result) return;
    setSaved(null);
    setError(null);
    try {
      const r = result.result as Record<string, unknown>;
      // Title: blended modules nest under .lesson; single artefacts carry .title.
      const title =
        (r.title as string) ||
        ((r.lesson as Record<string, unknown>)?.title as string) ||
        topic;
      const grounding =
        (r.grounding as Record<string, unknown>) ||
        ((r.lesson as Record<string, unknown>)?.grounding as Record<string, unknown>) ||
        {};
      const m = await saveTrainingModule({
        title,
        topic,
        kind: result.kind,
        content: r,
        rubric: DEFAULT_RUBRIC,
        grounding,
        pass_mark_pct: 70,
      });
      setSaved(m.id);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <div className="rounded-lg border border-slate-200 bg-white p-4 space-y-3">
        <div className="flex gap-2">
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && go(topic)}
            placeholder="Training topic — e.g. money laundering red flags"
            className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ink-300"
          />
          <button
            onClick={() => go(topic)}
            disabled={running || !topic.trim()}
            className="rounded bg-ink-900 text-white text-sm px-4 hover:bg-ink-700 disabled:opacity-50"
          >
            {running ? "Generating…" : "Generate"}
          </button>
        </div>

        <div className="flex flex-wrap gap-3 items-center text-sm">
          <label className="flex items-center gap-1">
            <span className="text-ink-500">Type</span>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as TrainingKind)}
              className="rounded border border-slate-300 px-2 py-1"
            >
              {KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
          {(kind === "quiz" || kind === "exam" || kind === "blended" || kind === "scenario") && (
            <label className="flex items-center gap-1">
              <span className="text-ink-500">Questions</span>
              <input
                type="number"
                min={1}
                max={50}
                value={numQuestions}
                onChange={(e) => setNumQuestions(Number(e.target.value))}
                className="w-16 rounded border border-slate-300 px-2 py-1"
              />
            </label>
          )}
          {kind === "exam" && (
            <label className="flex items-center gap-1">
              <span className="text-ink-500">Difficulty</span>
              <select
                value={difficulty}
                onChange={(e) => setDifficulty(e.target.value)}
                className="rounded border border-slate-300 px-2 py-1"
              >
                <option value="mixed">Mixed</option>
                <option value="easy">Easy</option>
                <option value="medium">Medium</option>
                <option value="hard">Hard</option>
              </select>
            </label>
          )}
          {kind === "scenario" && (
            <input
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="Staff role (optional) — e.g. cashier"
              className="rounded border border-slate-300 px-2 py-1 text-sm"
            />
          )}
        </div>
        {kind === "exam" && (
          <textarea
            value={examples}
            onChange={(e) => setExamples(e.target.value)}
            rows={2}
            placeholder="Optional: paste a past paper to mimic its style and difficulty"
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm resize-none"
          />
        )}
        <p className="text-xs text-ink-500">{KINDS.find((k) => k.value === kind)?.hint}</p>
      </div>

      {!result && !running && (
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => {
                setTopic(ex);
                go(ex);
              }}
              className="text-xs rounded-full border border-slate-300 bg-white px-3 py-1 text-ink-600 hover:bg-slate-100"
            >
              {ex.length > 56 ? ex.slice(0, 56) + "…" : ex}
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
          Grounding on your corpus and generating…
        </div>
      )}

      {result && (
        <div className="mt-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="text-xs uppercase tracking-wide text-ink-500">
              Generated {result.kind}
            </div>
            <div className="flex items-center gap-2">
              {saved && (
                <span className="text-xs text-emerald-700">
                  Saved · module {saved.slice(0, 8)}
                </span>
              )}
              <button
                onClick={save}
                className="rounded border border-ink-900 text-ink-900 text-xs px-3 py-1 hover:bg-ink-900 hover:text-white"
              >
                Save as module
              </button>
            </div>
          </div>
          <ResultBody payload={result.result} />
        </div>
      )}
    </>
  );
}

/** Render whatever the generator returned, by the bits we recognise. */
function ResultBody({ payload }: { payload: Record<string, unknown> }) {
  const p = payload;
  // Blended module: { lesson, quiz, scenario }
  if (p.lesson || p.quiz) {
    return (
      <div className="space-y-4">
        {p.lesson ? <Artefact a={p.lesson as Record<string, unknown>} /> : null}
        {p.quiz ? <Artefact a={p.quiz as Record<string, unknown>} /> : null}
        {p.scenario ? <Artefact a={p.scenario as Record<string, unknown>} /> : null}
      </div>
    );
  }
  return <Artefact a={p} />;
}

function Artefact({ a }: { a: Record<string, unknown> }) {
  const kind = a.kind as string;
  const data = (a.data as Record<string, unknown>) || {};
  const grounding = (a.grounding as Record<string, unknown>) || {};
  const citations = (grounding.citations as Record<string, unknown>[]) || [];

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      {a.title ? <h3 className="font-semibold text-ink-900 mb-2">{a.title as string}</h3> : null}

      {/* Prose artefacts (lesson, revision guide) */}
      {a.body ? (
        <div className="prose prose-sm max-w-none text-ink-900">
          <ReactMarkdown>{a.body as string}</ReactMarkdown>
        </div>
      ) : null}

      {/* Scenario */}
      {kind === "scenario" && (
        <div className="space-y-3 text-sm">
          {data.narrative ? <p className="text-ink-800">{data.narrative as string}</p> : null}
          {data.situation ? (
            <p className="text-ink-600 italic">{data.situation as string}</p>
          ) : null}
          {Array.isArray(data.conversation) && (
            <div className="rounded border border-slate-100 divide-y">
              {(data.conversation as Record<string, unknown>[]).map((line, i) => (
                <div key={i} className="px-3 py-2">
                  <span className="font-medium">{line.speaker as string}: </span>
                  <span>{line.line as string}</span>
                  {line.red_flag ? (
                    <span className="ml-2 rounded bg-amber-100 text-amber-900 px-1.5 py-0.5 text-[11px]">
                      ⚑ {(line.note as string) || "red flag"}
                    </span>
                  ) : null}
                </div>
              ))}
            </div>
          )}
          {Array.isArray(data.reporting_steps) && (data.reporting_steps as unknown[]).length > 0 && (
            <div>
              <div className="text-xs font-semibold uppercase text-ink-500 mb-1">
                Correct reporting procedure
              </div>
              <ol className="list-decimal list-inside text-ink-800">
                {(data.reporting_steps as string[]).map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
            </div>
          )}
          <QuestionList questions={(data.questions as Record<string, unknown>[]) || []} />
        </div>
      )}

      {/* Quiz / exam questions */}
      {(kind === "quiz" || kind === "exam") && (
        <QuestionList questions={(data.questions as Record<string, unknown>[]) || []} />
      )}

      {/* Flashcards */}
      {kind === "flashcards" && Array.isArray(data.cards) && (
        <div className="grid grid-cols-2 gap-2 text-sm">
          {(data.cards as Record<string, unknown>[]).map((c, i) => (
            <div key={i} className="rounded border border-slate-200 p-2">
              <div className="font-medium">{c.front as string}</div>
              <div className="text-ink-600">{c.back as string}</div>
            </div>
          ))}
        </div>
      )}

      {/* Slides */}
      {kind === "slides" && Array.isArray(data.slides) && (
        <ol className="space-y-2 text-sm">
          {(data.slides as Record<string, unknown>[]).map((s, i) => (
            <li key={i} className="rounded border border-slate-200 p-2">
              <div className="font-medium">{s.title as string}</div>
              {Array.isArray(s.bullets) && (
                <ul className="list-disc list-inside text-ink-700">
                  {(s.bullets as string[]).map((b, j) => (
                    <li key={j}>{b}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      )}

      {/* Grounding — the audit trail */}
      {citations.length > 0 && (
        <div className="mt-3 border-t border-slate-100 pt-2">
          <div className="text-[11px] uppercase tracking-wide text-ink-400 mb-1">
            Grounded in {citations.length} source{citations.length === 1 ? "" : "s"}
          </div>
          <div className="flex flex-wrap gap-1">
            {citations.map((c, i) => (
              <span
                key={i}
                className="text-[11px] rounded bg-slate-100 px-1.5 py-0.5 text-ink-600"
              >
                {(c.document_title as string) || "source"}
                {c.page_number ? ` p.${c.page_number}` : ""}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function QuestionList({ questions }: { questions: Record<string, unknown>[] }) {
  if (!questions.length) return null;
  return (
    <ol className="space-y-3 text-sm mt-2">
      {questions.map((q, i) => (
        <li key={i} className="rounded border border-slate-100 p-3">
          <div className="font-medium text-ink-900">
            {i + 1}. {q.question as string}
            {q.marks ? (
              <span className="ml-2 text-xs text-ink-500">({q.marks as number} marks)</span>
            ) : null}
          </div>
          {Array.isArray(q.options) && (
            <ul className="mt-1 space-y-0.5">
              {(q.options as string[]).map((o, j) => (
                <li
                  key={j}
                  className={
                    j === (q.answer_index as number)
                      ? "text-emerald-700 font-medium"
                      : "text-ink-700"
                  }
                >
                  {String.fromCharCode(65 + j)}. {o}
                  {j === (q.answer_index as number) ? " ✓" : ""}
                </li>
              ))}
            </ul>
          )}
          {q.model_answer ? (
            <div className="mt-1 text-ink-600">
              <span className="font-medium">Model answer: </span>
              {q.model_answer as string}
            </div>
          ) : null}
          {q.rationale ? (
            <div className="mt-1 text-xs text-ink-500">{q.rationale as string}</div>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function RecordsView() {
  const [records, setRecords] = useState<TrainingRecord[] | null>(null);

  useEffect(() => {
    listTrainingRecords().then(setRecords);
  }, []);

  if (records === null) {
    return <div className="text-sm text-ink-500">Loading records…</div>;
  }
  if (records.length === 0) {
    return (
      <div className="text-sm text-ink-500">
        No training records yet. Generate a module, assign it to staff, and their
        completions will appear here as an audit trail.
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-ink-500 text-xs uppercase tracking-wide">
          <tr>
            <th className="text-left px-3 py-2">Staff</th>
            <th className="text-left px-3 py-2">Topic</th>
            <th className="text-left px-3 py-2">Score</th>
            <th className="text-left px-3 py-2">Result</th>
            <th className="text-left px-3 py-2">Completed</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {records.map((r) => (
            <tr key={r.id}>
              <td className="px-3 py-2 font-mono text-xs">{r.user_id}</td>
              <td className="px-3 py-2">{r.topic}</td>
              <td className="px-3 py-2">
                {r.score_pct != null ? `${r.score_pct}%` : "—"}
              </td>
              <td className="px-3 py-2">
                {r.passed == null ? (
                  <span className="text-ink-500">—</span>
                ) : r.passed ? (
                  <span className="rounded bg-emerald-100 text-emerald-900 px-1.5 py-0.5 text-xs">
                    Passed
                  </span>
                ) : (
                  <span className="rounded bg-rose-100 text-rose-900 px-1.5 py-0.5 text-xs">
                    Failed
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-ink-500 text-xs">
                {new Date(r.completed_at).toLocaleString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
