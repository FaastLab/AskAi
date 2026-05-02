import { useState } from "react";
import {
  clearSettings,
  loadSettings,
  looksLikeOpenAiKey,
  saveSettings,
  type UserSettings,
} from "../lib/settings";

export function SettingsModal({
  open,
  onClose,
  requireByok,
}: {
  open: boolean;
  onClose: () => void;
  requireByok: boolean;
}) {
  const [settings, setSettings] = useState<UserSettings>(loadSettings());
  const [reveal, setReveal] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const onSave = () => {
    setError(null);
    const key = (settings.openaiApiKey || "").trim();
    if (key && !looksLikeOpenAiKey(key)) {
      setError(
        "That doesn't look like an OpenAI key — they start with 'sk-' and are ~50+ characters."
      );
      return;
    }
    saveSettings({
      openaiApiKey: key || null,
      cohereApiKey: (settings.cohereApiKey || "").trim() || null,
    });
    onClose();
  };

  const onForget = () => {
    clearSettings();
    setSettings({ openaiApiKey: null, cohereApiKey: null });
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-lg bg-white shadow-xl">
        <div className="border-b border-slate-200 px-5 py-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Settings</h2>
          <button
            onClick={onClose}
            className="text-ink-500 hover:text-ink-900 text-sm"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="px-5 py-4 space-y-5">
          <div className="text-sm text-ink-700 leading-relaxed">
            {requireByok ? (
              <>
                <strong>This deployment requires your own OpenAI key.</strong>{" "}
                Your key never leaves your browser except as the
                <code className="mx-1 rounded bg-slate-100 px-1 py-0.5 text-xs">
                  X-OpenAI-API-Key
                </code>
                header sent on each request you make. We never log it.
              </>
            ) : (
              <>
                Optionally bring your own LLM key. If set, your usage is
                billed to <em>you</em>, not the server. Stored only in this
                browser's local storage.
              </>
            )}
          </div>

          <div>
            <label className="block text-xs font-medium text-ink-700 mb-1">
              OpenAI API key
            </label>
            <div className="flex gap-2">
              <input
                type={reveal ? "text" : "password"}
                value={settings.openaiApiKey ?? ""}
                onChange={(e) =>
                  setSettings({ ...settings, openaiApiKey: e.target.value })
                }
                placeholder="sk-…"
                className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm font-mono
                           focus:outline-none focus:ring-2 focus:ring-ink-900"
                autoComplete="off"
              />
              <button
                onClick={() => setReveal((r) => !r)}
                className="rounded border border-slate-300 px-3 text-xs hover:bg-slate-50"
              >
                {reveal ? "Hide" : "Show"}
              </button>
            </div>
            <a
              className="text-xs text-ink-500 underline mt-1 inline-block"
              href="https://platform.openai.com/api-keys"
              target="_blank"
              rel="noreferrer"
            >
              Create a key at platform.openai.com →
            </a>
          </div>

          <details className="text-sm">
            <summary className="cursor-pointer text-ink-700">
              Advanced — Cohere reranker key (optional)
            </summary>
            <input
              type={reveal ? "text" : "password"}
              value={settings.cohereApiKey ?? ""}
              onChange={(e) =>
                setSettings({ ...settings, cohereApiKey: e.target.value })
              }
              placeholder="cohere key — only if RERANKER_PROVIDER=cohere"
              className="mt-2 w-full rounded border border-slate-300 px-3 py-2 text-sm font-mono"
              autoComplete="off"
            />
          </details>

          {error && (
            <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}
        </div>

        <div className="border-t border-slate-200 px-5 py-3 flex items-center justify-between">
          <button
            onClick={onForget}
            className="text-xs text-ink-500 hover:text-red-600"
          >
            Forget keys on this device
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="rounded border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              onClick={onSave}
              className="rounded bg-ink-900 px-4 py-2 text-sm text-white hover:bg-ink-700"
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
