/** Tiny localStorage-backed settings store for BYOK. */

const STORAGE_KEY = "askai.settings.v1";

export type UserSettings = {
  openaiApiKey: string | null;
  cohereApiKey: string | null;
};

const empty: UserSettings = { openaiApiKey: null, cohereApiKey: null };

export function loadSettings(): UserSettings {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return empty;
    return { ...empty, ...(JSON.parse(raw) as Partial<UserSettings>) };
  } catch {
    return empty;
  }
}

export function saveSettings(s: UserSettings): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

export function clearSettings(): void {
  window.localStorage.removeItem(STORAGE_KEY);
}

/** Minimal sanity: OpenAI keys start with `sk-` and are ~50+ chars. */
export function looksLikeOpenAiKey(key: string): boolean {
  return /^sk-[A-Za-z0-9_\-]{20,}/.test(key.trim());
}

/** Build the headers to inject on every API call. */
export function authHeaders(s: UserSettings): Record<string, string> {
  const h: Record<string, string> = {};
  if (s.openaiApiKey) h["X-OpenAI-API-Key"] = s.openaiApiKey;
  if (s.cohereApiKey) h["X-Cohere-API-Key"] = s.cohereApiKey;
  return h;
}
