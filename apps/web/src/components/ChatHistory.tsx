import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { listSessions } from "../lib/api";

/**
 * Dedicated chat-history column for the Chat page.
 *
 * Previously the session list lived in the global Sidebar, squeezed under the
 * long nav into barely an inch of scroll. Here it gets its own full-height
 * panel beside the conversation: "New chat" on top, the recent sessions below
 * with room to breathe.
 */
export function ChatHistory() {
  const [sessions, setSessions] = useState<{ id: string; title: string | null }[]>([]);
  const { sessionId } = useParams();
  const navigate = useNavigate();

  // Refresh whenever the active session changes — covers a brand-new chat
  // getting its id + auto-title after the first message is sent.
  useEffect(() => {
    listSessions()
      .then(setSessions)
      .catch(() => setSessions([]));
  }, [sessionId]);

  return (
    <aside className="w-64 shrink-0 border-r border-slate-200 bg-white flex flex-col">
      <div className="p-3 border-b border-slate-200">
        <button
          onClick={() => navigate("/chat")}
          className="w-full rounded-md bg-ink-900 text-white text-sm py-2 hover:bg-ink-700"
        >
          + New chat
        </button>
      </div>
      <div className="px-3 pt-3 pb-1 text-xs uppercase tracking-wide text-ink-500">
        Recent chats
      </div>
      <ul className="flex-1 overflow-y-auto px-2 pb-2 space-y-1">
        {sessions.map((s) => (
          <li key={s.id}>
            <Link
              to={`/chat/${s.id}`}
              title={s.title || "(untitled)"}
              className={`block rounded-md px-3 py-2 text-sm truncate hover:bg-slate-100 ${
                s.id === sessionId
                  ? "bg-slate-100 font-medium text-ink-900"
                  : "text-ink-700"
              }`}
            >
              {s.title || "(untitled)"}
            </Link>
          </li>
        ))}
        {sessions.length === 0 && (
          <li className="px-3 py-2 text-sm text-ink-500">No chats yet</li>
        )}
      </ul>
    </aside>
  );
}
