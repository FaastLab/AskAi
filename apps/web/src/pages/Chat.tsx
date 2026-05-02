import { useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Sidebar } from "../components/Sidebar";
import { Composer } from "../components/Composer";
import { Message, type ChatMessage } from "../components/Message";
import { streamAsk, type Citation } from "../lib/api";

export function ChatPage() {
  const { sessionId: sessionParam } = useParams();
  const [sessionId, setSessionId] = useState<string | null>(sessionParam ?? null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  async function ask(question: string) {
    setBusy(true);
    const userMsg: ChatMessage = { role: "user", content: question };
    const assistantMsg: ChatMessage = { role: "assistant", content: "", pending: true };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);

    abortRef.current?.abort();
    const ctl = new AbortController();
    abortRef.current = ctl;

    let collected = "";
    let citations: Citation[] = [];
    try {
      for await (const event of streamAsk(question, {
        sessionId,
        signal: ctl.signal,
      })) {
        if (event.event === "token") {
          collected += event.text;
          setMessages((prev) => {
            const next = [...prev];
            next[next.length - 1] = {
              ...next[next.length - 1],
              content: collected,
              pending: true,
            };
            return next;
          });
        } else if (event.event === "done") {
          citations = event.citations;
          setSessionId(event.session_id);
          setMessages((prev) => {
            const next = [...prev];
            next[next.length - 1] = {
              ...next[next.length - 1],
              content: collected,
              citations,
              pending: false,
            };
            return next;
          });
        }
      }
    } catch (err) {
      console.error(err);
      setMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          ...next[next.length - 1],
          content: "Error reaching the API.",
          pending: false,
        };
        return next;
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 flex flex-col">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <h1 className="text-lg font-semibold">FaastLab AskAi</h1>
          <p className="text-xs text-ink-500">
            Tenant: demo-public · ask anything about indexed UK financial regulation
          </p>
        </header>
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          <div className="max-w-3xl mx-auto w-full space-y-4">
            {messages.length === 0 && (
              <div className="text-center text-ink-500 mt-12 text-sm">
                Try: <em>"Summarise the FCA's Consumer Duty cross-cutting rules."</em>
              </div>
            )}
            {messages.map((m, i) => (
              <Message key={i} message={m} />
            ))}
          </div>
        </div>
        <Composer onSubmit={ask} disabled={busy} />
      </main>
    </div>
  );
}
