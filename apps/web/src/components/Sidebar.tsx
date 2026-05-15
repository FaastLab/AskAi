import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate, useParams } from "react-router-dom";
import { listSessions } from "../lib/api";

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

      <div className="text-xs text-ink-500 border-t border-slate-200 pt-3">
        FaastLab AskAi · v0.1
      </div>
    </aside>
  );
}
