import { useEffect, useMemo, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import { callMcpTool, getMcpInfo, type McpInfo, type McpTool } from "../lib/api";
import { loadAuth } from "../lib/auth";

// The single text argument each tool's inspector form drives. Keeps the demo
// one-field-simple instead of rendering a full JSON-schema form.
const PRIMARY_ARG: Record<string, { key: string; label: string; placeholder: string }> = {
  ask: { key: "question", label: "Question", placeholder: "What does the signalling standard require for level crossings?" },
  search_documents: { key: "query", label: "Search query", placeholder: "level crossing signalling" },
  get_document: { key: "document_id", label: "Document ID (UUID)", placeholder: "00000000-…" },
  get_summary: { key: "document_id", label: "Document ID (UUID)", placeholder: "00000000-…" },
  list_recent: { key: "limit", label: "How many", placeholder: "10" },
};

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
      className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100"
    >
      {done ? "Copied ✓" : "Copy"}
    </button>
  );
}

export function McpPage() {
  const isOwner = loadAuth()?.user.role === "owner";
  const [info, setInfo] = useState<McpInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [revealToken, setRevealToken] = useState(false);

  // Inspector state.
  const [tool, setTool] = useState("ask");
  const [argValue, setArgValue] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [latency, setLatency] = useState<number | null>(null);

  useEffect(() => {
    if (isOwner) getMcpInfo().then(setInfo).finally(() => setLoading(false));
  }, [isOwner]);

  // Full endpoint URL = this site's origin + the mounted path (e.g. /mcp).
  const endpointUrl = useMemo(
    () => (info ? `${window.location.origin}${info.endpoint_path}` : ""),
    [info],
  );
  const token = info?.shared_token ?? "<MCP_SHARED_TOKEN — set it in your deployment .env>";

  // Copy-paste config for a remote MCP connector (Claude Desktop "custom
  // connector", and the same shape most MCP-aware clients accept).
  const connectorJson = useMemo(
    () =>
      JSON.stringify(
        {
          mcpServers: {
            "faastlab-askai": {
              url: endpointUrl,
              headers: { Authorization: `Bearer ${token}` },
            },
          },
        },
        null,
        2,
      ),
    [endpointUrl, token],
  );

  async function runTool() {
    setRunning(true);
    setResult(null);
    setLatency(null);
    const spec = PRIMARY_ARG[tool];
    const args: Record<string, unknown> = {};
    if (spec && argValue.trim()) {
      // list_recent's limit is numeric; everything else is a string.
      args[spec.key] = spec.key === "limit" ? Number(argValue) : argValue.trim();
    }
    const res = await callMcpTool(tool, args);
    setRunning(false);
    if (!res) {
      setResult("Tool call failed. Check you're logged in as owner and the corpus has documents.");
      return;
    }
    setResult(res.result);
    setLatency(res.latency_ms);
  }

  if (!isOwner) {
    return (
      <div className="flex h-dvh">
        <Sidebar />
        <main className="flex-1 p-6">
          <div className="rounded bg-amber-50 border border-amber-300 p-4 text-sm text-amber-900 max-w-2xl">
            Only owners can view MCP settings.
          </div>
        </main>
      </div>
    );
  }

  const activeTool: McpTool | undefined = info?.tools.find((t) => t.name === tool);
  const primary = PRIMARY_ARG[tool];

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <h1 className="text-lg font-semibold">MCP server</h1>
          <p className="text-xs text-ink-500">
            Connect Claude, ChatGPT, or Copilot to your sovereign corpus over MCP —
            the agent reasons and calls these tools, you keep the data.
          </p>
        </header>

        <div className="flex-1 overflow-y-auto p-6 bg-slate-50">
          {loading ? (
            <div className="text-sm text-ink-500">Loading…</div>
          ) : (
            <div className="max-w-3xl mx-auto space-y-6">
              {/* ---- Connect ---- */}
              <section className="rounded-lg border border-slate-200 bg-white p-5">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold">Connection</h2>
                  <span
                    className={
                      "rounded-full px-2 py-0.5 text-[11px] font-medium " +
                      (info?.enabled
                        ? "bg-emerald-100 text-emerald-900"
                        : "bg-amber-100 text-amber-900")
                    }
                  >
                    {info?.enabled ? "● Live" : "○ Disabled — set MCP_SHARED_TOKEN"}
                  </span>
                </div>

                <div className="mt-4 space-y-3 text-sm">
                  <Row label="Endpoint">
                    <code className="text-xs break-all">{endpointUrl}</code>
                    <CopyButton text={endpointUrl} />
                  </Row>
                  <Row label="Auth token">
                    <code className="text-xs break-all">
                      {info?.shared_token
                        ? revealToken
                          ? info.shared_token
                          : "•".repeat(Math.min(24, info.shared_token.length))
                        : "not set"}
                    </code>
                    {info?.shared_token && (
                      <>
                        <button
                          onClick={() => setRevealToken((v) => !v)}
                          className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-100"
                        >
                          {revealToken ? "Hide" : "Reveal"}
                        </button>
                        <CopyButton text={info.shared_token} />
                      </>
                    )}
                  </Row>
                  <Row label="Serves tenant">
                    <code className="text-xs">{info?.tenant}</code>
                  </Row>
                </div>

                <div className="mt-4">
                  <div className="flex items-center justify-between mb-1">
                    <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
                      Client config (Claude Desktop / MCP clients)
                    </h3>
                    <CopyButton text={connectorJson} />
                  </div>
                  <pre className="rounded bg-slate-900 text-slate-100 text-xs p-3 overflow-x-auto">
                    {connectorJson}
                  </pre>
                  <p className="mt-1 text-[11px] text-ink-400">
                    In Claude Desktop: Settings → Connectors → Add custom connector →
                    paste the URL and the <code>Authorization</code> header. Then ask a
                    question — Claude will call <code>ask</code> / <code>search_documents</code>.
                  </p>
                </div>
              </section>

              {/* ---- Inspector ---- */}
              <section className="rounded-lg border border-slate-200 bg-white p-5">
                <h2 className="text-sm font-semibold">Tool inspector</h2>
                <p className="text-xs text-ink-500 mt-0.5">
                  Run a tool against your corpus to confirm it works before connecting a
                  client. This is the exact code path an agent hits.
                </p>

                <div className="mt-4 flex flex-wrap items-end gap-2">
                  <label className="text-xs text-ink-500">
                    Tool
                    <select
                      value={tool}
                      onChange={(e) => {
                        setTool(e.target.value);
                        setResult(null);
                        setArgValue("");
                      }}
                      className="mt-1 block rounded border border-slate-300 px-3 py-2 text-sm"
                    >
                      {info?.tools.map((t) => (
                        <option key={t.name} value={t.name}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {primary && (
                    <label className="text-xs text-ink-500 flex-1 min-w-[16rem]">
                      {primary.label}
                      <input
                        value={argValue}
                        onChange={(e) => setArgValue(e.target.value)}
                        placeholder={primary.placeholder}
                        className="mt-1 block w-full rounded border border-slate-300 px-3 py-2 text-sm"
                        onKeyDown={(e) => e.key === "Enter" && runTool()}
                      />
                    </label>
                  )}
                  <button
                    onClick={runTool}
                    disabled={running}
                    className="rounded-md bg-ink-900 px-4 py-2 text-sm text-white hover:bg-ink-700 disabled:opacity-50"
                  >
                    {running ? "Running…" : "Run tool"}
                  </button>
                </div>

                {activeTool && (
                  <p className="mt-2 text-[11px] text-ink-400">{activeTool.description}</p>
                )}

                {result !== null && (
                  <div className="mt-4">
                    <div className="text-xs text-ink-500 mb-1">
                      Result{latency != null ? ` · ${latency} ms` : ""}
                    </div>
                    <pre className="rounded bg-slate-50 border border-slate-200 text-xs p-3 overflow-x-auto whitespace-pre-wrap max-h-96">
                      {result}
                    </pre>
                  </div>
                )}
              </section>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      <span className="w-32 shrink-0 text-xs text-ink-500">{label}</span>
      <div className="flex items-center gap-2 flex-wrap min-w-0">{children}</div>
    </div>
  );
}
