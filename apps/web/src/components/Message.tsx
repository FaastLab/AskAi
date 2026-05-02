import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation } from "../lib/api";

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  pending?: boolean;
};

export function Message({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-2xl px-4 py-3 rounded-lg text-sm ${
          isUser ? "bg-ink-900 text-white" : "bg-white border border-slate-200"
        }`}
      >
        {isUser ? (
          <span className="whitespace-pre-wrap">{message.content}</span>
        ) : (
          <div className="prose prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {message.content || (message.pending ? "Thinking…" : "")}
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
