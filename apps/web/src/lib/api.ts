/** Tiny client wrapper over /v1/ — uses Vite proxy in dev. */
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { bearerHeader, saveAuth, type AuthUser } from "./auth";
import { authHeaders, loadSettings } from "./settings";

/** Merge BYOK headers + bearer auth so every API call carries both. */
function allAuthHeaders(): Record<string, string> {
  return { ...authHeaders(loadSettings()), ...bearerHeader() };
}

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

// ----------------------------------------------------------------------------
// Auth — signup / login / me
// ----------------------------------------------------------------------------

export type AuthResponse = {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
};

export async function signup(body: {
  email: string;
  password: string;
  full_name?: string;
  organisation: string;
}): Promise<AuthResponse> {
  const r = await fetch("/v1/auth/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const raw = await r.text();
  if (!r.ok) {
    let detail = raw;
    try { detail = JSON.parse(raw)?.detail ?? raw; } catch { /* keep raw */ }
    throw new Error(`Sign-up failed (HTTP ${r.status}): ${detail}`);
  }
  const data = JSON.parse(raw) as AuthResponse;
  saveAuth({
    access_token: data.access_token,
    expires_in: data.expires_in,
    user: data.user,
  });
  return data;
}

export async function login(body: {
  email: string;
  password: string;
}): Promise<AuthResponse> {
  const r = await fetch("/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const raw = await r.text();
  if (!r.ok) {
    let detail = raw;
    try { detail = JSON.parse(raw)?.detail ?? raw; } catch { /* keep raw */ }
    throw new Error(detail || `Login failed (HTTP ${r.status})`);
  }
  const data = JSON.parse(raw) as AuthResponse;
  saveAuth({
    access_token: data.access_token,
    expires_in: data.expires_in,
    user: data.user,
  });
  return data;
}

export async function fetchMe(): Promise<AuthUser | null> {
  const r = await fetch("/v1/auth/me", { headers: allAuthHeaders() });
  if (!r.ok) return null;
  return (await r.json()) as AuthUser;
}

// ----------------------------------------------------------------------------
// Validators — multi-regulator rule-pack scoring
// ----------------------------------------------------------------------------

export type RuleRequirementOut = {
  id: string;
  title: string;
  description: string;
  citation: string;
  severity: string;
};

export type RulePackOut = {
  id: string;
  regulator: string;
  name: string;
  version: string;
  summary: string;
  requirements: RuleRequirementOut[];
};

export type RequirementResultOut = {
  requirement_id: string;
  title: string;
  citation: string;
  severity: string;
  verdict: "green" | "amber" | "red" | "n/a";
  rationale: string;
  evidence_excerpts: Array<{ text: string; section_path: string | null; page: number | null }>;
};

export type ValidateReportOut = {
  pack_id: string;
  pack_name: string;
  pack_version: string;
  document_id: string;
  document_title: string;
  overall: "green" | "amber" | "red";
  score: number;
  counts: Record<string, number>;
  requirements: RequirementResultOut[];
  generated_at: string;
  latency_ms: number;
};

export async function listRulePacks(): Promise<RulePackOut[]> {
  const r = await fetch("/v1/validators/packs", { headers: allAuthHeaders() });
  if (!r.ok) return [];
  return (await r.json()) as RulePackOut[];
}

export async function runValidation(body: {
  document_id: string;
  pack_id: string;
}): Promise<ValidateReportOut> {
  const r = await fetch("/v1/validators/run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...allAuthHeaders(),
    },
    body: JSON.stringify(body),
  });
  const raw = await r.text();
  if (!r.ok) {
    let detail = raw;
    try { detail = JSON.parse(raw)?.detail ?? raw; } catch { /* keep raw */ }
    throw new Error(`Validation failed (HTTP ${r.status}): ${detail}`);
  }
  return JSON.parse(raw) as ValidateReportOut;
}

// ----------------------------------------------------------------------------
// Audit trail (owner/admin only)
// ----------------------------------------------------------------------------

export type AuditEntry = {
  id: number;
  user_id: string;
  user_email: string | null;
  action: string;
  resource: string | null;
  query: string | null;
  response_summary: string | null;
  latency_ms: number | null;
  created_at: string;
  source_count: number;
};

export type AuditEntryDetail = AuditEntry & {
  sources: Array<Record<string, unknown>>;
  extra: Record<string, unknown>;
};

export type AuditPage = {
  total: number;
  items: AuditEntry[];
};

export async function listAudit(opts?: {
  action?: string;
  user_id?: string;
  q?: string;
  days?: number;
  limit?: number;
  offset?: number;
}): Promise<AuditPage> {
  const params = new URLSearchParams();
  if (opts?.action) params.set("action", opts.action);
  if (opts?.user_id) params.set("user_id", opts.user_id);
  if (opts?.q) params.set("q", opts.q);
  if (opts?.days !== undefined) params.set("days", String(opts.days));
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts?.offset !== undefined) params.set("offset", String(opts.offset));
  const qs = params.toString();
  const r = await fetch(`/v1/audit${qs ? "?" + qs : ""}`, {
    headers: allAuthHeaders(),
  });
  if (!r.ok) return { total: 0, items: [] };
  return (await r.json()) as AuditPage;
}

export async function getAuditEntry(id: number): Promise<AuditEntryDetail | null> {
  const r = await fetch(`/v1/audit/${id}`, { headers: allAuthHeaders() });
  if (!r.ok) return null;
  return (await r.json()) as AuditEntryDetail;
}

export function auditCsvUrl(days = 30): string {
  return `/v1/audit.csv?days=${days}`;
}

// ----------------------------------------------------------------------------
// Admin (owner-only): users, invites
// ----------------------------------------------------------------------------

export type TenantUser = {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
};

export type InviteResponse = {
  token: string;
  accept_url: string;
  role: string;
  expires_at: string;
  note: string;
};

export async function listTenantUsers(): Promise<TenantUser[]> {
  const r = await fetch("/v1/admin/users", { headers: allAuthHeaders() });
  if (!r.ok) return [];
  return (await r.json()) as TenantUser[];
}

export async function createInvite(body?: {
  email?: string;
  role?: "member" | "admin";
  ttl_hours?: number;
}): Promise<InviteResponse> {
  const r = await fetch("/v1/admin/invites", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...allAuthHeaders(),
    },
    body: JSON.stringify({
      email: body?.email,
      role: body?.role ?? "member",
      ttl_hours: body?.ttl_hours ?? 168,
    }),
  });
  const raw = await r.text();
  if (!r.ok) {
    let detail = raw;
    try { detail = JSON.parse(raw)?.detail ?? raw; } catch { /* keep raw */ }
    throw new Error(`Invite creation failed (HTTP ${r.status}): ${detail}`);
  }
  return JSON.parse(raw) as InviteResponse;
}

export async function acceptInvite(body: {
  token: string;
  email: string;
  password: string;
  full_name?: string;
}): Promise<{ status: string; tenant_slug: string; tenant_name: string; role: string; next: string }> {
  const r = await fetch("/v1/auth/accept-invite", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const raw = await r.text();
  if (!r.ok) {
    let detail = raw;
    try { detail = JSON.parse(raw)?.detail ?? raw; } catch { /* keep raw */ }
    throw new Error(detail || `Accept failed (HTTP ${r.status})`);
  }
  return JSON.parse(raw);
}

// ----------------------------------------------------------------------------
// Config
// ----------------------------------------------------------------------------

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
  opts?: { sessionId?: string | null; includeSuperseded?: boolean; signal?: AbortSignal; rerank?: boolean }
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
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    signal: opts?.signal,
    body: JSON.stringify({
      query: question,
      session_id: opts?.sessionId ?? null,
      filters: { include_superseded: opts?.includeSuperseded ?? false },
      stream: true,
      rerank: opts?.rerank ?? true,
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
  const r = await fetch("/v1/sessions", { headers: allAuthHeaders() });
  if (!r.ok) return [];
  return (await r.json()) as Array<{ id: string; title: string | null }>;
}

export type SessionMessage = {
  role: "user" | "assistant";
  content: string;
  ts?: string;
  citations?: Citation[];
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
    headers: allAuthHeaders(),
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
    headers: allAuthHeaders(),
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
  docType?: string | null;
}): Promise<DocumentRecord[]> {
  const params = new URLSearchParams();
  if (opts?.onlyActive !== undefined) params.set("only_active", String(opts.onlyActive));
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts?.docType) params.set("doc_type", opts.docType);
  const qs = params.toString();
  const r = await fetch(`/v1/documents${qs ? "?" + qs : ""}`, {
    headers: allAuthHeaders(),
  });
  if (!r.ok) return [];
  return (await r.json()) as DocumentRecord[];
}

/** Counts per category (regulator code) + 'uploads' + 'total' for chip badges. */
export async function listDocumentCounts(): Promise<Record<string, number>> {
  const r = await fetch("/v1/documents/_counts", {
    headers: allAuthHeaders(),
  });
  if (!r.ok) return {};
  return (await r.json()) as Record<string, number>;
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
  opts?: { k?: number; onlyActive?: boolean; rerank?: boolean }
): Promise<SearchResult | null> {
  const r = await fetch("/v1/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...allAuthHeaders(),
    },
    body: JSON.stringify({
      query,
      k: opts?.k ?? 10,
      filters: { only_active: opts?.onlyActive ?? true },
      rerank: opts?.rerank ?? true,
    }),
  });
  if (!r.ok) return null;
  return (await r.json()) as SearchResult;
}
