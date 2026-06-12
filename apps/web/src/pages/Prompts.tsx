import { useEffect, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  activatePromptVersion,
  listPrompts,
  savePromptVersion,
  type GatewayPrompt,
} from "../lib/api";
import { loadAuth } from "../lib/auth";

export function PromptsPage() {
  const auth = loadAuth();
  const isOwner = auth?.user.role === "owner";

  const [prompts, setPrompts] = useState<GatewayPrompt[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function refresh(keep?: string) {
    setLoading(true);
    const list = (await listPrompts()) ?? [];
    setPrompts(list);
    const pick = keep ?? selected ?? list[0]?.name ?? null;
    setSelected(pick);
    const cur = list.find((p) => p.name === pick);
    if (cur) setDraft(cur.active_template);
    setLoading(false);
  }

  useEffect(() => {
    if (isOwner) void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOwner]);

  const current = prompts.find((p) => p.name === selected) ?? null;
  const dirty = current ? draft !== current.active_template : false;

  function select(name: string) {
    setSelected(name);
    setMsg(null);
    const p = prompts.find((x) => x.name === name);
    if (p) setDraft(p.active_template);
  }

  async function save() {
    if (!current || !dirty) return;
    setSaving(true);
    setMsg(null);
    try {
      const { version } = await savePromptVersion(current.name, draft);
      setMsg(`Saved & activated ${version} — live on the next question.`);
      await refresh(current.name);
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function activate(version: string) {
    if (!current) return;
    setSaving(true);
    setMsg(null);
    try {
      await activatePromptVersion(current.name, version);
      setMsg(`Activated ${version}.`);
      await refresh(current.name);
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!isOwner) {
    return (
      <div className="flex h-dvh">
        <Sidebar />
        <main className="flex-1 p-6">
          <div className="rounded bg-amber-50 border border-amber-300 p-4 text-sm text-amber-900 max-w-2xl">
            Only the tenant owner can edit prompts.
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <h1 className="text-lg font-semibold">Prompts</h1>
          <p className="text-xs text-ink-500">
            Edit the AI's instructions live. Saving creates a new version and
            makes it active immediately — no redeploy. Roll back anytime.
          </p>
        </header>

        {loading ? (
          <div className="p-6 text-sm text-ink-500">Loading…</div>
        ) : (
          <div className="flex-1 flex min-h-0">
            {/* Prompt list */}
            <div className="w-56 border-r border-slate-200 overflow-y-auto bg-slate-50">
              <ul className="divide-y divide-slate-200">
                {prompts.map((p) => (
                  <li key={p.name}>
                    <button
                      onClick={() => select(p.name)}
                      className={`w-full text-left px-4 py-3 text-sm hover:bg-white ${
                        selected === p.name ? "bg-white font-medium" : ""
                      }`}
                    >
                      <div className="font-mono text-xs">{p.name}</div>
                      <div className="text-[11px] text-ink-500">
                        {p.source === "db" ? p.active_version : "default"}
                        {p.versions.length > 0 && ` · ${p.versions.length} versions`}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </div>

            {/* Editor */}
            <div className="flex-1 flex flex-col min-w-0">
              {!current ? (
                <div className="p-6 text-sm text-ink-500">Select a prompt.</div>
              ) : (
                <>
                  <div className="flex-1 flex flex-col p-4 min-h-0">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xs text-ink-500">
                        Active: <strong>{current.active_version}</strong> (
                        {current.source})
                      </span>
                      {dirty && (
                        <span className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-1.5 py-0.5">
                          unsaved changes
                        </span>
                      )}
                      <div className="ml-auto flex gap-2">
                        {current.default_template != null && (
                          <button
                            onClick={() => setDraft(current.default_template ?? "")}
                            className="text-xs rounded border border-slate-300 px-2 py-1 hover:bg-slate-50"
                          >
                            Reset to default
                          </button>
                        )}
                        <button
                          onClick={save}
                          disabled={!dirty || saving}
                          className="text-xs rounded bg-ink-900 text-white px-3 py-1 hover:bg-ink-700 disabled:opacity-50"
                        >
                          {saving ? "Saving…" : "Save & activate"}
                        </button>
                      </div>
                    </div>
                    <textarea
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      spellCheck={false}
                      className="flex-1 w-full resize-none rounded border border-slate-300 p-3 font-mono text-xs leading-relaxed focus:outline-none focus:ring-2 focus:ring-ink-300"
                    />
                    {msg && (
                      <div className="mt-2 text-xs text-ink-600">{msg}</div>
                    )}
                  </div>

                  {/* Version history */}
                  {current.versions.length > 0 && (
                    <div className="border-t border-slate-200 max-h-48 overflow-y-auto">
                      <div className="px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-500">
                        Version history
                      </div>
                      <ul className="divide-y divide-slate-100">
                        {current.versions.map((v) => (
                          <li
                            key={v.version}
                            className="px-4 py-2 flex items-center gap-3 text-xs"
                          >
                            <span className="font-mono">{v.version}</span>
                            {v.is_active && (
                              <span className="rounded-full bg-emerald-100 text-emerald-900 px-2 py-0.5 text-[10px] font-medium uppercase">
                                active
                              </span>
                            )}
                            <span className="text-ink-500">
                              {new Date(v.created_at).toLocaleString()}
                            </span>
                            {!v.is_active && (
                              <button
                                onClick={() => activate(v.version)}
                                disabled={saving}
                                className="ml-auto rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50 disabled:opacity-50"
                              >
                                Activate
                              </button>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
