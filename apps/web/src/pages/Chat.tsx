import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Sidebar } from "../components/Sidebar";
import { ChatHistory } from "../components/ChatHistory";
import { Composer } from "../components/Composer";
import { Message, type ChatMessage } from "../components/Message";
import { SettingsModal } from "../components/SettingsModal";
import { UploadModal } from "../components/UploadModal";
import { getConfig, getSession, streamAsk, submitFeedback, type Citation, type PublicConfig } from "../lib/api";
import { loadSettings } from "../lib/settings";

export function ChatPage() {
  const { sessionId: sessionParam } = useParams();
  const [sessionId, setSessionId] = useState<string | null>(sessionParam ?? null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [hasKey, setHasKey] = useState<boolean>(!!loadSettings().openaiApiKey);
  // Per-user toggle: rerank ON = higher precision, ~5-15s slower on CPU.
  // Rerank OFF = pure hybrid (vector + keyword), much faster. Persisted in
  // localStorage so the user's choice survives page reloads.
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
  const abortRef = useRef<AbortController | null>(null);

  // Pull server config; if it requires BYOK and the user has no key,
  // open the settings modal automatically on first load.
  useEffect(() => {
    getConfig().then((c) => {
      setConfig(c);
      const stored = !!loadSettings().openaiApiKey;
      setHasKey(stored);
      if (c?.require_byok && !stored) setShowSettings(true);
    });
  }, []);

  // Load session history when the URL session param changes (clicking a
  // session in the sidebar) — or reset to a fresh chat when there's no
  // session in the URL ("+ New chat"). Also aborts any in-flight stream
  // so navigating mid-answer doesn't mix messages.
  useEffect(() => {
    abortRef.current?.abort();
    if (!sessionParam) {
      setSessionId(null);
      setMessages([]);
      return;
    }
    setSessionId(sessionParam);
    let cancelled = false;
    getSession(sessionParam).then((s) => {
      if (cancelled) return;
      if (!s) {
        setMessages([]);
        return;
      }
      setMessages(
        s.history.map((m) => ({
          role: m.role,
          content: m.content,
          citations: m.citations,
        }))
      );
    });
    return () => {
      cancelled = true;
    };
  }, [sessionParam]);

  // Re-read storage when the modal closes (in case the user saved a key).
  const closeSettings = () => {
    setShowSettings(false);
    setHasKey(!!loadSettings().openaiApiKey);
  };

  const blockedByByok = !!config?.require_byok && !hasKey;

  // Submit a thumbs up/down (+optional correction) on the assistant message at
  // `index`. The question is the preceding user turn; document ids come from
  // the answer's citations — together they let the backend attribute the
  // signal and nudge ranking for this question.
  async function handleFeedback(
    index: number,
    rating: 1 | -1,
    correction?: string,
  ) {
    const msg = messages[index];
    if (!msg || msg.feedback) return;
    const question = index > 0 ? messages[index - 1]?.content ?? "" : "";
    // Optimistically reflect the vote so the bar collapses immediately.
    setMessages((prev) => {
      const next = [...prev];
      if (next[index]) {
        next[index] = { ...next[index], feedback: rating === 1 ? "up" : "down" };
      }
      return next;
    });
    await submitFeedback({
      rating,
      query: question,
      request_id: msg.requestId ?? null,
      session_id: sessionId,
      correction: correction ?? null,
      document_ids: (msg.citations ?? []).map((c) => c.document_id),
      chunk_ids: (msg.citations ?? []).map((c) => c.chunk_id),
    });
  }

  async function ask(question: string) {
    if (blockedByByok) {
      setShowSettings(true);
      return;
    }
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
        rerank: useRerank,
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
              requestId: event.request_id ?? null,
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
          content:
            "Error reaching the API. If this deployment requires your own OpenAI key, set it via the gear icon in the top right.",
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
      <ChatHistory />
      <main className="flex-1 flex flex-col">
        <header className="border-b border-slate-200 bg-white px-6 py-3 flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold">FaastLab AskAi</h1>
            <p className="text-xs text-ink-500">
              Tenant: {config?.default_tenant ?? "demo-public"} · model: {config?.llm_model ?? "—"}
              {hasKey ? " · using your key" : config?.require_byok ? " · BYOK required" : ""}
            </p>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={toggleRerank}
              className={
                "rounded px-2 py-1 text-xs font-medium border transition-colors " +
                (useRerank
                  ? "bg-emerald-50 border-emerald-300 text-emerald-800 hover:bg-emerald-100"
                  : "bg-amber-50 border-amber-300 text-amber-800 hover:bg-amber-100")
              }
              title={
                useRerank
                  ? "Reranker ON — best precision, slower on CPU (~15-25s)"
                  : "Reranker OFF — faster (~5-10s), lower precision on tight queries"
              }
              aria-label="Toggle reranker"
            >
              {useRerank ? "Rerank: ON · Quality" : "Rerank: OFF · Fast"}
            </button>
            <button
              onClick={() => setShowUpload(true)}
              className="rounded p-2 text-ink-700 hover:bg-slate-100"
              aria-label="Upload document"
              title="Upload document"
            >
              {/* up-arrow-into-tray glyph */}
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
            </button>
            <button
              onClick={() => setShowSettings(true)}
              className="rounded p-2 text-ink-700 hover:bg-slate-100"
              aria-label="Settings"
              title="Settings"
            >
              {/* simple gear glyph — no extra icon dep */}
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="3" />
                <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3 1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
              </svg>
            </button>
          </div>
        </header>

        {blockedByByok && (
          <div className="bg-amber-50 border-b border-amber-300 px-6 py-3 text-sm text-amber-900 flex items-center gap-3">
            <span className="flex-1">
              This demo runs on your own OpenAI key. Add it via the gear icon to start asking.
            </span>
            <button
              onClick={() => setShowSettings(true)}
              className="rounded bg-amber-900 px-3 py-1 text-xs text-white hover:bg-amber-800"
            >
              Add key
            </button>
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          <div className="max-w-3xl mx-auto w-full space-y-4">
            {messages.length === 0 && (
              <div className="text-center text-ink-500 mt-12 text-sm">
                Try: <em>"Summarise the FCA's Consumer Duty cross-cutting rules."</em>
              </div>
            )}
            {messages.map((m, i) => (
              <Message
                key={i}
                message={m}
                onFeedback={
                  m.role === "assistant"
                    ? (rating, correction) => handleFeedback(i, rating, correction)
                    : undefined
                }
              />
            ))}
          </div>
        </div>
        <Composer onSubmit={ask} disabled={busy} />
      </main>

      <SettingsModal
        open={showSettings}
        onClose={closeSettings}
        requireByok={!!config?.require_byok}
      />
      <UploadModal
        open={showUpload}
        onClose={() => setShowUpload(false)}
      />
    </div>
  );
}
