import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation } from "../lib/api";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  pending?: boolean;
};

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

export function Message({ message }: { message: ChatMessage }) {
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
      </div>
    </div>
  );
}
