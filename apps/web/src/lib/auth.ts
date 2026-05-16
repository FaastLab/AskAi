/** Token storage + auth helpers — localStorage-backed JWT. */

const STORAGE_KEY = "askai.auth.v1";

export type AuthUser = {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  tenant_id: string;
  tenant_slug: string;
  tenant_name: string;
  plan: string | null;
  trial_expires_at: string | null;
  trial_remaining_days: number | null;
};

export type AuthState = {
  access_token: string;
  expires_in: number;
  saved_at: number;     // ms epoch
  user: AuthUser;
};

export function loadAuth(): AuthState | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AuthState;
    // Defensive: token validity is enforced server-side; we just hide
    // obviously-stale tokens client-side to avoid spurious 401s.
    if (parsed.saved_at && parsed.expires_in) {
      const expiresAt = parsed.saved_at + parsed.expires_in * 1000;
      if (Date.now() >= expiresAt) {
        return null;
      }
    }
    return parsed;
  } catch {
    return null;
  }
}

export function saveAuth(payload: {
  access_token: string;
  expires_in: number;
  user: AuthUser;
}): AuthState {
  const state: AuthState = {
    access_token: payload.access_token,
    expires_in: payload.expires_in,
    saved_at: Date.now(),
    user: payload.user,
  };
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  return state;
}

export function clearAuth(): void {
  window.localStorage.removeItem(STORAGE_KEY);
}

/** Bearer-token header — merge into fetch headers if a session exists. */
export function bearerHeader(): Record<string, string> {
  const auth = loadAuth();
  if (!auth) return {};
  return { Authorization: `Bearer ${auth.access_token}` };
}

/** True if there's a non-expired session in storage. */
export function isAuthenticated(): boolean {
  return loadAuth() !== null;
}
