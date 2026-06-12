import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation } from "../lib/api";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  pending?: boolean;
  requestId?: string | null;
  // Which way the user rated this answer (once submitted), so the UI can
  // show the choice and prevent re-voting.
  feedback?: "up" | "down";
};

export type FeedbackSubmit = (rating: 1 | -1, correction?: string) => void;

function ThinkingIndicator() {
  // Three dots that fade in/out in sequence — looks like a wave/snake.
  // Pure tailwind animation; no extra deps. The custom delay classes are
  // safe-listed via inline style to avoid tailwind purge surprises.
  const dotBase =
    "inline-block h-1.5 w-1.5 rounded-full bg-ink-500 animate-bounce";
  return (
    <span className="inline-flex items-center gap-1 text-ink-500">
      <span>Thinking</span>
      <span className="inline-flex gap-1 ml-1">
        <span className={dotBase} style={{ animationDelay: "0ms" }} />
        <span className={dotBase} style={{ animationDelay: "150ms" }} />
        <span className={dotBase} style={{ animationDelay: "300ms" }} />
      </span>
    </span>
  );
}

function FeedbackBar({
  message,
  onFeedback,
}: {
  message: ChatMessage;
  onFeedback: FeedbackSubmit;
}) {
  const [showCorrection, setShowCorrection] = useState(false);
  const [correction, setCorrection] = useState("");
  const voted = message.feedback;

  if (voted) {
    return (
      <div className="mt-3 flex items-center gap-2 text-xs text-ink-500">
        {voted === "up" ? (
          <span className="text-emerald-700">Thanks — marked helpful 👍</span>
        ) : (
          <span className="text-amber-700">
            Thanks — we'll use this to improve answers 👎
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="mt-3 border-t border-slate-100 pt-2">
      <div className="flex items-center gap-1 text-ink-500">
        <span className="text-xs mr-1">Was this helpful?</span>
        <button
          onClick={() => onFeedback(1)}
          className="rounded p-1 hover:bg-emerald-50 hover:text-emerald-700"
          aria-label="Helpful"
          title="Helpful — float these sources up for this question"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M7 10v12" />
            <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
          </svg>
        </button>
        <button
          onClick={() => setShowCorrection((s) => !s)}
          className="rounded p-1 hover:bg-amber-50 hover:text-amber-700"
          aria-label="Not helpful"
          title="Not helpful — optionally tell us the right answer"
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M17 14V2" />
            <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
          </svg>
        </button>
      </div>
      {showCorrection && (
        <div className="mt-2 space-y-2">
          <textarea
            value={correction}
            onChange={(e) => setCorrection(e.target.value)}
            placeholder="Optional: what's the correct answer or which source should have been used?"
            className="w-full rounded border border-slate-300 px-2 py-1 text-xs focus:border-ink-500 focus:outline-none"
            rows={2}
          />
          <div className="flex gap-2">
            <button
              onClick={() => onFeedback(-1, correction.trim() || undefined)}
              className="rounded bg-amber-700 px-2 py-1 text-xs text-white hover:bg-amber-800"
            >
              Submit feedback
            </button>
            <button
              onClick={() => setShowCorrection(false)}
              className="rounded px-2 py-1 text-xs text-ink-500 hover:bg-slate-100"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function Message({
  message,
  onFeedback,
}: {
  message: ChatMessage;
  onFeedback?: FeedbackSubmit;
}) {
  const isUser = message.role === "user";
  const showThinking = !isUser && message.pending && !message.content;
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-2xl px-4 py-3 rounded-lg text-sm ${
          isUser ? "bg-ink-900 text-white" : "bg-white border border-slate-200"
        }`}
      >
        {isUser ? (
          <span className="whitespace-pre-wrap">{message.content}</span>
        ) : showThinking ? (
          <ThinkingIndicator />
        ) : (
          <div className="prose prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content}
            </ReactMarkdown>
          </div>
        )}
        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="mt-3 border-t border-slate-200 pt-2 space-y-1">
            <div className="text-xs uppercase tracking-wide text-ink-500">
              Citations
            </div>
            <ol className="text-xs space-y-1">
              {message.citations.map((c, i) => (
                <li key={c.chunk_id} className="text-ink-700">
                  <span className="font-medium">[{i + 1}] {c.document_title}</span>
                  {c.page_number != null && <span> · p.{c.page_number}</span>}
                  <div className="text-ink-500 italic">{c.snippet}</div>
                </li>
              ))}
            </ol>
          </div>
        )}
        {!isUser && !message.pending && message.content && onFeedback && (
          <FeedbackBar message={message} onFeedback={onFeedback} />
        )}
      </div>
    </div>
  );
}
