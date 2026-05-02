import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { listSessions } from "../lib/api";

export function Sidebar() {
  const [sessions, setSessions] = useState<{ id: string; title: string | null }[]>([]);
  const navigate = useNavigate();
  const { sessionId } = useParams();

  useEffect(() => {
    listSessions().then(setSessions);
  }, [sessionId]);

  return (
    <aside className="w-72 border-r border-slate-200 bg-white p-4 flex flex-col gap-3">
      <button
        onClick={() => navigate("/chat")}
        className="rounded-md bg-ink-900 text-white text-sm py-2 hover:bg-ink-700"
      >
        + New chat
      </button>
      <div className="text-xs uppercase tracking-wide text-ink-500 mt-2">Recent</div>
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
      <div className="text-xs text-ink-500 border-t border-slate-200 pt-3">
        FaastLab AskAi · v0.1
      </div>
    </aside>
  );
}
