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
  | { event: "done"; session_id: string; citations: Citation[]; request_id?: string | null };

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
// Agent (#4) — multi-step tool-calling over the sovereign tools
// ----------------------------------------------------------------------------

export type AgentStep = {
  tool: string;
  arguments: Record<string, unknown>;
  result_preview: string;
};

export type AgentResponse = {
  answer: string;
  iterations: number;
  steps: AgentStep[];
};

export async function runAgent(goal: string): Promise<AgentResponse> {
  const r = await fetch("/v1/agent", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify({ goal }),
  });
  const raw = await r.text();
  if (!r.ok) {
    let detail = raw;
    try {
      detail = JSON.parse(raw)?.detail ?? raw;
    } catch {
      /* keep raw */
    }
    throw new Error(detail || `Agent failed (HTTP ${r.status})`);
  }
  return JSON.parse(raw) as AgentResponse;
}

// ----------------------------------------------------------------------------
// Compliance training (#7) — grounded generation, assignment, grading, records
// ----------------------------------------------------------------------------

export type TrainingKind =
  | "blended"
  | "lesson"
  | "revision_guide"
  | "quiz"
  | "exam"
  | "flashcards"
  | "slides"
  | "scenario";

export type TrainingGenerateRequest = {
  topic: string;
  kind: TrainingKind;
  num_questions?: number;
  style?: string;
  difficulty?: string;
  example_questions?: string | null;
  objectives?: string[] | null;
  role?: string | null;
  include_scenario?: boolean;
};

// The generated payload is shape-varied by kind, so we keep it loose and let
// the page render the bits it knows about.
export type TrainingGenerateResponse = {
  kind: TrainingKind;
  result: Record<string, unknown>;
};

export type TrainingModule = {
  id: string;
  title: string;
  topic: string;
  kind: string;
  content: Record<string, unknown>;
  rubric: Record<string, unknown>;
  grounding: Record<string, unknown>;
  source_document_ids: string[];
  pass_mark_pct: number;
  created_by: string | null;
  created_at: string;
};

export type TrainingAssignment = {
  id: string;
  module_id: string;
  user_id: string;
  assigned_by: string | null;
  status: string;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
};

export type TrainingRecord = {
  id: string;
  module_id: string;
  assignment_id: string | null;
  user_id: string;
  topic: string;
  score: number | null;
  max_score: number | null;
  score_pct: number | null;
  passed: boolean | null;
  grade_detail: Record<string, unknown>;
  completed_at: string;
};

/** Turn a FastAPI error body into a readable string.
 *
 * `detail` can be a plain string (our HTTPExceptions) OR — for 422 validation
 * errors — an array of `{loc, msg, ...}` objects. Rendering that array directly
 * gives "[object Object]", so flatten it to "field: message" lines. */
function errorMessage(raw: string, status: number): string {
  try {
    const detail = JSON.parse(raw)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d: { loc?: unknown[]; msg?: string }) => {
          const field = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : "";
          return field ? `${field}: ${d.msg}` : d.msg;
        })
        .join("; ");
    }
    if (detail) return JSON.stringify(detail);
  } catch {
    /* fall through to raw */
  }
  return raw || `Request failed (HTTP ${status})`;
}

async function trainingPost<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify(body),
  });
  const raw = await r.text();
  if (!r.ok) {
    throw new Error(errorMessage(raw, r.status));
  }
  return JSON.parse(raw) as T;
}

export function generateTraining(
  body: TrainingGenerateRequest,
): Promise<TrainingGenerateResponse> {
  return trainingPost<TrainingGenerateResponse>("/v1/training/generate", body);
}

export function saveTrainingModule(body: {
  title: string;
  topic: string;
  kind: string;
  content: Record<string, unknown>;
  rubric?: Record<string, unknown>;
  grounding?: Record<string, unknown>;
  source_document_ids?: string[];
  pass_mark_pct?: number;
}): Promise<TrainingModule> {
  return trainingPost<TrainingModule>("/v1/training/modules", body);
}

export async function listTrainingModules(): Promise<TrainingModule[]> {
  const r = await fetch("/v1/training/modules", { headers: allAuthHeaders() });
  if (!r.ok) return [];
  return (await r.json()) as TrainingModule[];
}

export function assignTraining(body: {
  module_id: string;
  user_ids: string[];
  due_at?: string | null;
}): Promise<TrainingAssignment[]> {
  return trainingPost<TrainingAssignment[]>("/v1/training/assignments", body);
}

export async function listTrainingAssignments(opts?: {
  module_id?: string;
  mine?: boolean;
}): Promise<TrainingAssignment[]> {
  const qs = new URLSearchParams();
  if (opts?.module_id) qs.set("module_id", opts.module_id);
  if (opts?.mine) qs.set("mine", "true");
  const suffix = qs.toString() ? `?${qs}` : "";
  const r = await fetch(`/v1/training/assignments${suffix}`, {
    headers: allAuthHeaders(),
  });
  if (!r.ok) return [];
  return (await r.json()) as TrainingAssignment[];
}

export function submitTraining(body: {
  module_id: string;
  assignment_id?: string | null;
  answers?: number[] | null;
  content?: string | null;
}): Promise<TrainingRecord> {
  return trainingPost<TrainingRecord>("/v1/training/submit", body);
}

export async function listTrainingRecords(opts?: {
  user_id?: string;
  module_id?: string;
}): Promise<TrainingRecord[]> {
  const qs = new URLSearchParams();
  if (opts?.user_id) qs.set("user_id", opts.user_id);
  if (opts?.module_id) qs.set("module_id", opts.module_id);
  const suffix = qs.toString() ? `?${qs}` : "";
  const r = await fetch(`/v1/training/records${suffix}`, {
    headers: allAuthHeaders(),
  });
  if (!r.ok) return [];
  return (await r.json()) as TrainingRecord[];
}

// ----------------------------------------------------------------------------
// AI Gateway observability (owner-only): usage + per-request feed
// ----------------------------------------------------------------------------

export type GatewayQuota = {
  requests_per_day: number; // 0 = unlimited
  tokens_per_day: number;
  requests_remaining: number | null; // null = unlimited
  tokens_remaining: number | null;
};

export type GatewayUsage = {
  window_hours: number;
  requests: number;
  ok: number;
  errors: number;
  denied: number;
  tokens: number;
  cost_usd: number;
  by_purpose: Record<string, number>;
  quota: GatewayQuota;
};

export type GatewayRequestRow = {
  request_id: string | null;
  created_at: string;
  purpose: string;
  model: string | null;
  total_tokens: number;
  cost_usd: number;
  latency_ms: number | null;
  status: string;
  error: string | null;
};

export type GatewayTraceCall = {
  created_at: string;
  purpose: string;
  provider: string | null;
  model: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  latency_ms: number | null;
  status: string;
  error: string | null;
};

export type GatewayTrace = {
  request_id: string;
  query: string | null;
  response_summary: string | null;
  sources: Record<string, unknown>[];
  calls: GatewayTraceCall[];
};

export type GatewayRequests = {
  window_hours: number;
  stats: {
    count: number;
    p50_ms: number | null;
    p95_ms: number | null;
    error_rate: number;
  };
  requests: GatewayRequestRow[];
};

export async function getGatewayUsage(windowHours = 24): Promise<GatewayUsage | null> {
  const r = await fetch(`/v1/gateway/usage?window_hours=${windowHours}`, {
    headers: allAuthHeaders(),
  });
  if (!r.ok) return null;
  return (await r.json()) as GatewayUsage;
}

export async function getGatewayRequests(
  windowHours = 24,
  limit = 100,
): Promise<GatewayRequests | null> {
  const r = await fetch(
    `/v1/gateway/requests?window_hours=${windowHours}&limit=${limit}`,
    { headers: allAuthHeaders() },
  );
  if (!r.ok) return null;
  return (await r.json()) as GatewayRequests;
}

export async function getGatewayTrace(
  requestId: string,
): Promise<GatewayTrace | null> {
  const r = await fetch(`/v1/gateway/requests/${encodeURIComponent(requestId)}`, {
    headers: allAuthHeaders(),
  });
  if (!r.ok) return null;
  return (await r.json()) as GatewayTrace;
}

// ---- Prompt engineering (owner-only): live, versioned system prompts -------

export type GatewayPromptVersion = {
  version: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
};

export type GatewayPrompt = {
  name: string;
  active_template: string;
  active_version: string;
  source: string; // "db" | "default"
  default_template: string | null;
  versions: GatewayPromptVersion[];
};

export async function listPrompts(): Promise<GatewayPrompt[] | null> {
  const r = await fetch("/v1/gateway/prompts", { headers: allAuthHeaders() });
  if (!r.ok) return null;
  return (await r.json()) as GatewayPrompt[];
}

export async function savePromptVersion(
  name: string,
  template: string,
  description?: string,
): Promise<{ name: string; version: string }> {
  const r = await fetch(
    `/v1/gateway/prompts/${encodeURIComponent(name)}/versions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...allAuthHeaders() },
      body: JSON.stringify({ template, description, activate: true }),
    },
  );
  if (!r.ok) throw new Error(`Save failed (HTTP ${r.status})`);
  return (await r.json()) as { name: string; version: string };
}

export async function activatePromptVersion(
  name: string,
  version: string,
): Promise<void> {
  const r = await fetch(
    `/v1/gateway/prompts/${encodeURIComponent(name)}/activate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...allAuthHeaders() },
      body: JSON.stringify({ version }),
    },
  );
  if (!r.ok) throw new Error(`Activate failed (HTTP ${r.status})`);
}

// ---- #6 Security & governance (owner-only) ---------------------------------

export type GatewayPolicy = {
  enabled: boolean;
  allowed_models: string[]; // empty = any
  max_tokens_per_request: number; // 0 = no cap
  allow_cloud: boolean; // false = sovereign lock (no cloud egress)
  jailbreak_guard: boolean; // screen prompts for jailbreak / injection
  available_models: string[];
};

export async function getPolicy(): Promise<GatewayPolicy | null> {
  const r = await fetch("/v1/gateway/policy", { headers: allAuthHeaders() });
  if (!r.ok) return null;
  return (await r.json()) as GatewayPolicy;
}

export async function updatePolicy(body: {
  enabled: boolean;
  allowed_models: string[];
  max_tokens_per_request: number;
  allow_cloud: boolean;
  jailbreak_guard: boolean;
}): Promise<GatewayPolicy> {
  const r = await fetch("/v1/gateway/policy", {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`Save failed (HTTP ${r.status})`);
  return (await r.json()) as GatewayPolicy;
}

// ---- Model routing + failover (owner-only) ---------------------------------

export type RoutingTarget = {
  name: string; // "qwen" | "openai"
  label: string;
  model: string;
  configured: boolean; // endpoint/key present — usable
};

export type GatewayRouting = {
  order: string[]; // selection, primary first; 1 entry = no failover
  available: RoutingTarget[];
};

export async function getRouting(): Promise<GatewayRouting | null> {
  const r = await fetch("/v1/gateway/routing", { headers: allAuthHeaders() });
  if (!r.ok) return null;
  return (await r.json()) as GatewayRouting;
}

export async function updateRouting(order: string[]): Promise<GatewayRouting> {
  const r = await fetch("/v1/gateway/routing", {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify({ order }),
  });
  if (!r.ok) throw new Error(`Save failed (HTTP ${r.status})`);
  return (await r.json()) as GatewayRouting;
}

export type GovernanceEvent = {
  created_at: string;
  action: string;
  user_id: string;
  resource: string | null;
  extra: Record<string, unknown>;
};

export async function getGovernanceEvents(): Promise<GovernanceEvent[] | null> {
  const r = await fetch("/v1/gateway/governance-events", {
    headers: allAuthHeaders(),
  });
  if (!r.ok) return null;
  return (await r.json()) as GovernanceEvent[];
}

// ----------------------------------------------------------------------------
// #8 Web connectors — config-driven crawling + indexer dashboard (owner-only)
// ----------------------------------------------------------------------------

export type ConnectorRun = {
  run_id: string;
  started_at: string;
  finished_at: string;
  status: "ok" | "error" | "running";
  pages: number;
  ingested: number;
  skipped: number;
  failed: number;
  error: string | null;
  duration_ms: number;
};

export type WebConnector = {
  id: string;
  name: string;
  mode: "page" | "sitemap" | "crawl";
  start_urls: string[];
  url_prefix: string | null;
  include: string[];
  exclude: string[];
  max_pages: number;
  max_depth: number;
  doc_type: string | null;
  enabled: boolean;
  schedule_interval_minutes: number | null;
  created_at?: string;
  last_run_at?: string | null;
  runs?: ConnectorRun[];
};

export type ConnectorInput = Omit<WebConnector, "id" | "created_at" | "last_run_at" | "runs">;

export async function listConnectors(): Promise<WebConnector[]> {
  const r = await fetch("/v1/connectors", { headers: allAuthHeaders() });
  if (!r.ok) return [];
  return (await r.json()) as WebConnector[];
}

export async function createConnector(body: ConnectorInput): Promise<WebConnector | null> {
  const r = await fetch("/v1/connectors", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify(body),
  });
  if (!r.ok) return null;
  return (await r.json()) as WebConnector;
}

export async function updateConnector(
  id: string,
  body: ConnectorInput,
): Promise<WebConnector | null> {
  const r = await fetch(`/v1/connectors/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify(body),
  });
  if (!r.ok) return null;
  return (await r.json()) as WebConnector;
}

export async function deleteConnector(id: string): Promise<boolean> {
  const r = await fetch(`/v1/connectors/${id}`, {
    method: "DELETE",
    headers: allAuthHeaders(),
  });
  return r.ok;
}

/** Enqueue an immediate crawl. Returns the task id, or throws with the
 *  server's message if the worker/broker is unreachable. */
export async function runConnector(id: string): Promise<{ status: string; task_id: string }> {
  const r = await fetch(`/v1/connectors/${id}/run`, {
    method: "POST",
    headers: allAuthHeaders(),
  });
  const raw = await r.text();
  if (!r.ok) {
    let detail = raw;
    try { detail = JSON.parse(raw)?.detail ?? raw; } catch { /* keep raw */ }
    throw new Error(detail || `Run failed (HTTP ${r.status})`);
  }
  return JSON.parse(raw) as { status: string; task_id: string };
}

// ----------------------------------------------------------------------------
// #7 Feedback loop — rate answers (any member) + owner-only summary
// ----------------------------------------------------------------------------

/** Record a thumbs up/down (+optional correction) on an answer. The signal
 *  nudges retrieval ranking for the same/similar question over time. */
export async function submitFeedback(body: {
  rating: 1 | -1;
  query: string;
  request_id?: string | null;
  session_id?: string | null;
  correction?: string | null;
  document_ids?: string[];
  chunk_ids?: string[];
}): Promise<{ status: string; id: number } | null> {
  const r = await fetch("/v1/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify(body),
  });
  if (!r.ok) return null;
  return (await r.json()) as { status: string; id: number };
}

export type FeedbackCorrection = {
  created_at: string;
  query: string;
  rating: number;
  correction: string | null;
};

export type FeedbackSummary = {
  window_hours: number;
  up: number;
  down: number;
  corrections: number;
  helpful_rate: number; // 0..1
  recent_corrections: FeedbackCorrection[];
};

export async function getFeedbackSummary(
  windowHours = 720,
): Promise<FeedbackSummary | null> {
  const r = await fetch(`/v1/gateway/feedback?window_hours=${windowHours}`, {
    headers: allAuthHeaders(),
  });
  if (!r.ok) return null;
  return (await r.json()) as FeedbackSummary;
}

// ----------------------------------------------------------------------------
// #8 Ingestion pipeline — regulator presets + indexers + runs (owner-only)
// ----------------------------------------------------------------------------

export type IngestPreset = {
  key: string;
  name: string;
  category: string;
  description: string;
  license: string;
  kind: string;
  start_url_count: number;
  enabled: boolean;
};

export type IngestRun = {
  run_id: number;
  status: "ok" | "error" | "running";
  pages: number;
  ingested: number;
  skipped: number;
  failed: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
};

export type IngestIndexer = {
  id: string;
  name: string;
  enabled: boolean;
  source_id: string | null;
  kind: string | null; // "folder" => uploadable; "web" => crawl preset
  category: string | null;
  license: string | null;
  preset_key: string | null;
  schedule: { interval_minutes?: number } & Record<string, unknown>;
  last_run_at: string | null;
  last_run: IngestRun | null;
};

export async function listPresets(): Promise<IngestPreset[]> {
  const r = await fetch("/v1/ingestion/presets", { headers: allAuthHeaders() });
  if (!r.ok) return [];
  return (await r.json()) as IngestPreset[];
}

export async function enablePreset(key: string): Promise<{ id: string } | null> {
  const r = await fetch(`/v1/ingestion/presets/${encodeURIComponent(key)}/enable`, {
    method: "POST",
    headers: allAuthHeaders(),
  });
  if (!r.ok) return null;
  return (await r.json()) as { id: string };
}

export async function listIndexers(): Promise<IngestIndexer[]> {
  const r = await fetch("/v1/ingestion/indexers", { headers: allAuthHeaders() });
  if (!r.ok) return [];
  return (await r.json()) as IngestIndexer[];
}

export async function runIndexer(id: string): Promise<{ status: string } | null> {
  const r = await fetch(`/v1/ingestion/indexers/${id}/run`, {
    method: "POST",
    headers: allAuthHeaders(),
  });
  if (!r.ok) {
    const raw = await r.text();
    let detail = raw;
    try { detail = JSON.parse(raw)?.detail ?? raw; } catch { /* keep raw */ }
    throw new Error(detail || `Run failed (HTTP ${r.status})`);
  }
  return (await r.json()) as { status: string };
}

export async function getIndexerRuns(id: string): Promise<IngestRun[]> {
  const r = await fetch(`/v1/ingestion/indexers/${id}/runs`, { headers: allAuthHeaders() });
  if (!r.ok) return [];
  return (await r.json()) as IngestRun[];
}

export async function deleteIndexer(id: string): Promise<boolean> {
  const r = await fetch(`/v1/ingestion/indexers/${id}`, {
    method: "DELETE",
    headers: allAuthHeaders(),
  });
  return r.ok;
}

/** Create a custom folder data source (+ its indexer). schedule_interval_minutes
 *  null/0 = manual ("Run now") only. Returns the ids for upload + tracking. */
export async function createFolderSource(body: {
  name: string;
  schedule_interval_minutes: number | null;
}): Promise<{ source_id: string; indexer_id: string } | null> {
  const r = await fetch("/v1/ingestion/sources/folder", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify(body),
  });
  if (!r.ok) return null;
  return (await r.json()) as { source_id: string; indexer_id: string };
}

/** Upload files into a folder source's storage prefix. They get indexed when
 *  the indexer next runs (scheduled or "Run now") — not on upload. */
export async function uploadToSource(
  sourceId: string,
  files: File[] | FileList,
): Promise<{ uploaded: number } | null> {
  const form = new FormData();
  for (const f of Array.from(files)) form.append("files", f);
  const r = await fetch(`/v1/ingestion/sources/${sourceId}/upload`, {
    method: "POST",
    headers: allAuthHeaders(), // no Content-Type — browser sets the multipart boundary
    body: form,
  });
  if (!r.ok) return null;
  return (await r.json()) as { uploaded: number };
}

// ----------------------------------------------------------------------------
// MCP — connection settings + tool inspector (owner-only)
// ----------------------------------------------------------------------------

export type McpTool = {
  name: string;
  description: string;
  inputSchema: { properties?: Record<string, unknown>; required?: string[] };
};

export type McpInfo = {
  enabled: boolean;
  transport: string;
  endpoint_path: string; // "/mcp"
  tenant: string;
  shared_token: string | null;
  tools: McpTool[];
};

export async function getMcpInfo(): Promise<McpInfo | null> {
  const r = await fetch("/v1/mcp/info", { headers: allAuthHeaders() });
  if (!r.ok) return null;
  return (await r.json()) as McpInfo;
}

/** Run one MCP tool against your own corpus — the in-app inspector test. */
export async function callMcpTool(
  tool: string,
  args: Record<string, unknown>,
): Promise<{ tool: string; result: string; latency_ms: number } | null> {
  const r = await fetch("/v1/mcp/call", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify({ tool, arguments: args }),
  });
  if (!r.ok) return null;
  return (await r.json()) as { tool: string; result: string; latency_ms: number };
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

// ---- Voice (OpenAI Whisper STT + OpenAI TTS) --------------------------------

/** Send recorded mic audio to Whisper; returns the transcript text. */
export async function transcribeAudio(blob: Blob): Promise<string> {
  const form = new FormData();
  form.append("file", blob, "audio.webm");
  const r = await fetch("/v1/voice/transcribe", {
    method: "POST",
    // No Content-Type — the browser sets the multipart boundary itself.
    headers: allAuthHeaders(),
    body: form,
  });
  if (!r.ok) throw new Error(`Transcription failed (HTTP ${r.status})`);
  return ((await r.json()) as { text: string }).text;
}

/** Mint an OpenAI Realtime ephemeral session (GA: ephemeral key is `value`). */
export async function getRealtimeSession(
  role: string | null,
): Promise<{ value?: string } | null> {
  const r = await fetch("/v1/voice/realtime-session", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify({ role }),
  });
  if (!r.ok) return null;
  return await r.json();
}

/** Synthesize `text` with OpenAI TTS; returns an object-URL for an <audio> src. */
export async function speakText(text: string): Promise<string | null> {
  const r = await fetch("/v1/voice/speak", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) return null;
  return URL.createObjectURL(await r.blob());
}

// ---- Assistant roles (each a named system prompt) --------------------------

export type Role = { slug: string; label: string };
export type RolesResponse = { roles: Role[]; default_role: string | null };

export async function listRoles(): Promise<RolesResponse> {
  const r = await fetch("/v1/roles", { headers: allAuthHeaders() });
  if (!r.ok) return { roles: [], default_role: null };
  return (await r.json()) as RolesResponse;
}

export async function createRole(
  name: string,
  prompt: string,
): Promise<RolesResponse> {
  const r = await fetch("/v1/roles", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify({ name, prompt }),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => null);
    throw new Error(
      (detail && (detail.detail as string)) || `Create failed (HTTP ${r.status})`,
    );
  }
  return (await r.json()) as RolesResponse;
}

export async function setDefaultRole(role: string | null): Promise<RolesResponse | null> {
  const r = await fetch("/v1/roles/default", {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify({ role }),
  });
  if (!r.ok) return null;
  return (await r.json()) as RolesResponse;
}

export async function* streamAsk(
  question: string,
  opts?: { sessionId?: string | null; includeSuperseded?: boolean; signal?: AbortSignal; rerank?: boolean; role?: string | null }
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
      role: opts?.role ?? null,
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
  folder: string | null;
  created_at: string;
  updated_at: string;
};

/** Move (set folder) and/or rename a document the caller's tenant owns.
 *  Send folder: "" to move to root; omit a field to leave it unchanged. */
export async function updateDocument(
  id: string,
  patch: { folder?: string; title?: string },
): Promise<DocumentRecord | null> {
  const r = await fetch(`/v1/documents/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify(patch),
  });
  if (!r.ok) return null;
  return (await r.json()) as DocumentRecord;
}

/** Permanently delete a document the caller's tenant owns (chunks + stored
 *  original go too). Returns true on success. */
export async function deleteDocument(id: string): Promise<boolean> {
  const r = await fetch(`/v1/documents/${id}`, {
    method: "DELETE",
    headers: allAuthHeaders(),
  });
  return r.ok;
}

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

/** Queue summary + keyphrases generation for one document (runs on the worker
 *  via the deployment's default LLM). Returns true if it was queued. */
export async function summariseDocument(id: string): Promise<boolean> {
  const r = await fetch(`/v1/documents/${id}/summarise`, {
    method: "POST",
    headers: allAuthHeaders(),
  });
  return r.ok;
}

/** Backfill: queue summaries for all of the tenant's documents that don't have
 *  one yet. Returns how many were queued. */
export async function summariseMissing(): Promise<number> {
  const r = await fetch("/v1/documents/summarise-missing", {
    method: "POST",
    headers: allAuthHeaders(),
  });
  if (!r.ok) return 0;
  return ((await r.json()) as { queued: number }).queued;
}

// ---- Document enrichment (owner-only): auto-summary toggle + status ---------

export type EnrichmentSettings = { auto: boolean; default: boolean };
export type EnrichmentStatus = { total: number; enriched: number; pending: number };

export async function getEnrichment(): Promise<EnrichmentSettings | null> {
  const r = await fetch("/v1/enrichment", { headers: allAuthHeaders() });
  if (!r.ok) return null;
  return (await r.json()) as EnrichmentSettings;
}

export async function setEnrichment(auto: boolean): Promise<EnrichmentSettings | null> {
  const r = await fetch("/v1/enrichment", {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
    body: JSON.stringify({ auto }),
  });
  if (!r.ok) return null;
  return (await r.json()) as EnrichmentSettings;
}

export async function getEnrichmentStatus(): Promise<EnrichmentStatus | null> {
  const r = await fetch("/v1/enrichment/status", { headers: allAuthHeaders() });
  if (!r.ok) return null;
  return (await r.json()) as EnrichmentStatus;
}

/**
 * Get a short-lived signed URL for downloading the original document file.
 *
 * The browser opens this URL as an anchor / new-tab navigation, so it
 * cannot attach an Authorization header. We exchange our bearer token
 * for a 5-minute single-doc-scoped token via the signed-url endpoint,
 * then embed that token in the URL query string. Tokens are audience-
 * pinned to "askai-file" so a leak can't be replayed against
 * /v1/ask, /v1/search etc.
 *
 * Returns null if the token can't be minted (auth expired, doc gone) —
 * callers should show an error and prompt re-login.
 */
export async function getDocumentFileUrl(id: string): Promise<string | null> {
  const r = await fetch(`/v1/documents/${id}/file/signed-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...allAuthHeaders() },
  });
  if (!r.ok) return null;
  const body = (await r.json()) as { url: string; expires_in: number };
  return body.url;
}

export type SearchHit = {
  id: string;            // chunk id
  document_id: string;
  document_title: string | null;
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
  opts?: { k?: number; onlyActive?: boolean; rerank?: boolean; docType?: string }
): Promise<SearchResult | null> {
  const filters: Record<string, unknown> = {
    only_active: opts?.onlyActive ?? true,
  };
  if (opts?.docType) filters.doc_types = [opts.docType];
  const r = await fetch("/v1/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...allAuthHeaders(),
    },
    body: JSON.stringify({
      query,
      k: opts?.k ?? 10,
      filters,
      rerank: opts?.rerank ?? true,
    }),
  });
  if (!r.ok) return null;
  return (await r.json()) as SearchResult;
}

// ---- Search-as-you-type counts (Typesense) ---------------------------------

export type InstantCounts = {
  found: number;
  facets: Record<string, Record<string, number>>;
  supported: boolean; // false on pgvector — hide the live counter
};

/** Live match-count + doc_type facet counts for the search bar. Cheap
 * (keyword-only, no documents) — safe to call on every keystroke. */
export async function instantSearch(
  q: string,
  docType?: string,
): Promise<InstantCounts> {
  const qs = new URLSearchParams({ q });
  if (docType) qs.set("doc_type", docType);
  const r = await fetch(`/v1/search/instant?${qs}`, { headers: allAuthHeaders() });
  if (!r.ok) return { found: 0, facets: {}, supported: false };
  return (await r.json()) as InstantCounts;
}
