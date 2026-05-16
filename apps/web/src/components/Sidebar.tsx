import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate, useParams } from "react-router-dom";
import { listSessions } from "../lib/api";
import { clearAuth, loadAuth } from "../lib/auth";

const MIN_REFETCH_INTERVAL_MS = 5000;

export function Sidebar() {
  const [sessions, setSessions] = useState<{ id: string; title: string | null }[]>([]);
  const navigate = useNavigate();
  const { sessionId } = useParams();
  const location = useLocation();
  const lastFetchRef = useRef<number>(0);
  const inFlightRef = useRef<boolean>(false);

  // We only need session list on chat routes.
  const onChat = location.pathname.startsWith("/chat");

  useEffect(() => {
    if (!onChat) return;
    // Throttle: don't refetch if we just did within MIN_REFETCH_INTERVAL_MS,
    // and never run two requests in parallel. Avoids an audit-log /
    // connection-pool storm when React re-runs the effect.
    const now = Date.now();
    if (inFlightRef.current) return;
    if (now - lastFetchRef.current < MIN_REFETCH_INTERVAL_MS) return;

    inFlightRef.current = true;
    lastFetchRef.current = now;
    listSessions()
      .then(setSessions)
      .finally(() => {
        inFlightRef.current = false;
      });
  }, [sessionId, onChat]);

  const navBase =
    "flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-slate-100";
  const navActive = "bg-slate-100 font-medium text-ink-900";
  const navInactive = "text-ink-700";

  return (
    <aside className="w-72 border-r border-slate-200 bg-white p-4 flex flex-col gap-3">
      {/* Top-level navigation */}
      <nav className="flex flex-col gap-1">
        <NavLink
          to="/chat"
          end
          className={({ isActive }) =>
            `${navBase} ${isActive || onChat ? navActive : navInactive}`
          }
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          Chat
        </NavLink>
        <NavLink
          to="/documents"
          className={({ isActive }) =>
            `${navBase} ${isActive ? navActive : navInactive}`
          }
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="9" y1="13" x2="15" y2="13" />
            <line x1="9" y1="17" x2="15" y2="17" />
          </svg>
          Documents
        </NavLink>
        <NavLink
          to="/validator"
          className={({ isActive }) =>
            `${navBase} ${isActive ? navActive : navInactive}`
          }
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 11l3 3L22 4" />
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
          </svg>
          Validator
        </NavLink>
        {(loadAuth()?.user.role === "owner" || loadAuth()?.user.role === "admin") && (
          <NavLink
            to="/audit"
            className={({ isActive }) =>
              `${navBase} ${isActive ? navActive : navInactive}`
            }
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <line x1="10" y1="9" x2="8" y2="9" />
            </svg>
            Audit trail
          </NavLink>
        )}
        {loadAuth()?.user.role === "owner" && (
          <NavLink
            to="/admin"
            className={({ isActive }) =>
              `${navBase} ${isActive ? navActive : navInactive}`
            }
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
            Admin
          </NavLink>
        )}
      </nav>

      {onChat && (
        <>
          <button
            onClick={() => navigate("/chat")}
            className="mt-2 rounded-md bg-ink-900 text-white text-sm py-2 hover:bg-ink-700"
          >
            + New chat
          </button>
          <div className="text-xs uppercase tracking-wide text-ink-500 mt-2">
            Recent
          </div>
          <ul className="flex-1 overflow-y-auto space-y-1">
            {sessions.map((s) => (
              <li key={s.id}>
                <Link
                  to={`/chat/${s.id}`}
                  className={`block rounded-md px-3 py-2 text-sm hover:bg-slate-100 ${
                    s.id === sessionId ? "bg-slate-100 font-medium" : ""
                  }`}
                >
                  {s.title || "(untitled)"}
                </Link>
              </li>
            ))}
            {sessions.length === 0 && (
              <li className="text-sm text-ink-500 px-1">No sessions yet</li>
            )}
          </ul>
        </>
      )}

      {!onChat && <div className="flex-1" />}

      <div className="border-t border-slate-200 pt-3 space-y-2">
        <AuthFooter />
        <div className="text-xs text-ink-500">FaastLab AskAi · v0.1</div>
      </div>
    </aside>
  );
}


function AuthFooter() {
  const navigate = useNavigate();
  const auth = loadAuth();

  if (!auth) {
    return (
      <div className="flex items-center justify-between gap-2">
        <Link
          to="/login"
          className="text-xs text-ink-700 underline hover:text-ink-900"
        >
          Sign in
        </Link>
        <Link
          to="/signup"
          className="text-xs rounded bg-ink-900 text-white px-2 py-1 hover:bg-ink-700"
        >
          Start trial
        </Link>
      </div>
    );
  }

  function onLogout() {
    clearAuth();
    navigate("/login", { replace: true });
  }

  const trialDays = auth.user.trial_remaining_days;
  return (
    <div>
      <div className="text-xs font-medium text-ink-900 truncate" title={auth.user.email}>
        {auth.user.full_name || auth.user.email}
      </div>
      <div className="text-[11px] text-ink-500 truncate" title={auth.user.tenant_name}>
        {auth.user.tenant_name}
      </div>
      {trialDays != null && (
        <div
          className={
            "mt-1 inline-block rounded px-1.5 py-0.5 text-[10px] " +
            (trialDays <= 3
              ? "bg-amber-100 text-amber-900"
              : "bg-emerald-100 text-emerald-900")
          }
          title="Trial remaining"
        >
          {trialDays === 0
            ? "Trial expired"
            : `Trial · ${trialDays}d left`}
        </div>
      )}
      <button
        onClick={onLogout}
        className="mt-2 block text-xs text-ink-500 underline hover:text-ink-900"
      >
        Sign out
      </button>
    </div>
  );
}
