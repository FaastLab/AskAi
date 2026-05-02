/** Tiny client wrapper over /v1/ — uses Vite proxy in dev. */
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { authHeaders, loadSettings } from "./settings";

export type Citation = {
  chunk_id: string;
  document_id: string;
  document_title: string;
  page_number: number | null;
  section_path: string | null;
  snippet: string;
};

export type AskEvent =
  | { event: "retrieve"; confidence: number; chunks: number }
  | { event: "token"; text: string }
  | { event: "done"; session_id: string; citations: Citation[] };

export type PublicConfig = {
  name: string;
  version: string;
  default_tenant: string;
  llm_model: string;
  summarisation_model: string;
  embeddings_model: string;
  require_byok: boolean;
  reranker_provider: string;
};

export async function getConfig(): Promise<PublicConfig | null> {
  try {
    const r = await fetch("/v1/config");
    if (!r.ok) return null;
    return (await r.json()) as PublicConfig;
  } catch {
    return null;
  }
}

export async function* streamAsk(
  question: string,
  opts?: { sessionId?: string | null; includeSuperseded?: boolean; signal?: AbortSignal }
): AsyncGenerator<AskEvent> {
  const queue: AskEvent[] = [];
  let resolve: ((e: AskEvent | null) => void) | null = null;
  let done = false;

  const promise = (): Promise<AskEvent | null> =>
    new Promise((res) => {
      if (queue.length) res(queue.shift()!);
      else if (done) res(null);
      else resolve = res;
    });

  fetchEventSource("/v1/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(loadSettings()) },
    signal: opts?.signal,
    body: JSON.stringify({
      query: question,
      session_id: opts?.sessionId ?? null,
      filters: { include_superseded: opts?.includeSuperseded ?? false },
      stream: true,
    }),
    onmessage(msg) {
      try {
        const parsed = JSON.parse(msg.data) as AskEvent;
        if (resolve) {
          const r = resolve;
          resolve = null;
          r(parsed);
        } else queue.push(parsed);
      } catch {
        // ignore malformed frames
      }
    },
    onclose() {
      done = true;
      if (resolve) {
        const r = resolve;
        resolve = null;
        r(null);
      }
    },
    onerror(err) {
      done = true;
      if (resolve) {
        const r = resolve;
        resolve = null;
        r(null);
      }
      throw err;
    },
  });

  while (true) {
    const next = await promise();
    if (next === null) return;
    yield next;
  }
}

export async function listSessions() {
  const r = await fetch("/v1/sessions", { headers: authHeaders(loadSettings()) });
  if (!r.ok) return [];
  return (await r.json()) as Array<{ id: string; title: string | null }>;
}
