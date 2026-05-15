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

export type SessionMessage = {
  role: "user" | "assistant";
  content: string;
  ts?: string;
};

export type SessionDetail = {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  history: SessionMessage[];
};

export async function getSession(id: string): Promise<SessionDetail | null> {
  const r = await fetch(`/v1/sessions/${id}`, {
    headers: authHeaders(loadSettings()),
  });
  if (!r.ok) return null;
  return (await r.json()) as SessionDetail;
}

export type UploadResult = {
  status: "ok" | "skipped" | "failed";
  document_id: string;
  job_id: string;
  chunks_written: number;
  note: string;
};

export type DocumentRecord = {
  id: string;
  tenant_id: string;
  title: string;
  source_uri: string;
  doc_type: string | null;
  version: string | null;
  effective_date: string | null;
  summary: string | null;
  keyphrases: string[] | null;
  size_bytes: number | null;
  created_at: string;
  updated_at: string;
};

/** Upload one document; the api ingests synchronously (parse + chunk +
 *  embed + store). Returns when ingestion finishes. */
export async function uploadDocument(
  file: File,
  opts?: { title?: string; signal?: AbortSignal }
): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  if (opts?.title) form.append("title", opts.title);
  const r = await fetch("/v1/ingest/upload", {
    method: "POST",
    headers: authHeaders(loadSettings()),
    body: form,
    signal: opts?.signal,
  });
  // Read the body once as text, then try to parse JSON from that.
  // Doing r.json() with a fallback to r.text() throws 'body stream
  // already read' because the first read consumes the stream.
  const raw = await r.text();
  if (!r.ok) {
    let detail = raw;
    try {
      detail = JSON.parse(raw)?.detail ?? raw;
    } catch {
      /* raw isn't JSON — keep as-is */
    }
    throw new Error(
      `Upload failed (HTTP ${r.status}): ${detail || r.statusText}`
    );
  }
  try {
    return JSON.parse(raw) as UploadResult;
  } catch {
    throw new Error(
      `Upload succeeded but response wasn't JSON: ${raw.slice(0, 200)}`
    );
  }
}

export async function listDocuments(opts?: {
  onlyActive?: boolean;
  limit?: number;
}): Promise<DocumentRecord[]> {
  const params = new URLSearchParams();
  if (opts?.onlyActive !== undefined) params.set("only_active", String(opts.onlyActive));
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  const r = await fetch(`/v1/documents${qs ? "?" + qs : ""}`, {
    headers: authHeaders(loadSettings()),
  });
  if (!r.ok) return [];
  return (await r.json()) as DocumentRecord[];
}

/** URL for downloading / previewing the original document file. */
export function documentFileUrl(id: string): string {
  return `/v1/documents/${id}/file`;
}

export type SearchHit = {
  id: string;            // chunk id
  document_id: string;
  content: string;
  section_path: string | null;
  page_number: number | null;
  score: number;
  rank: number;
};

export type SearchResult = {
  query: string;
  latency_ms: number;
  hits: SearchHit[];
};

/** Hybrid search (vector + BM25 + rerank) — same engine the chat uses. */
export async function searchChunks(
  query: string,
  opts?: { k?: number; onlyActive?: boolean }
): Promise<SearchResult | null> {
  const r = await fetch("/v1/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(loadSettings()),
    },
    body: JSON.stringify({
      query,
      k: opts?.k ?? 10,
      filters: { only_active: opts?.onlyActive ?? true },
    }),
  });
  if (!r.ok) return null;
  return (await r.json()) as SearchResult;
}
