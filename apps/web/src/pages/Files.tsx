import { useEffect, useMemo, useRef, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import {
  deleteDocument,
  getDocumentFileUrl,
  listDocuments,
  updateDocument,
  uploadDocument,
  type DocumentRecord,
} from "../lib/api";

// ---------------------------------------------------------------------------
// Folder helpers — folders are a virtual overlay derived from each document's
// `folder` path (Azure-blob-style prefixes). "" is the tenant's root.
// ---------------------------------------------------------------------------

function docFolder(d: DocumentRecord): string {
  return (d.folder ?? "").replace(/^\/+|\/+$/g, "");
}

function joinFolder(base: string, name: string): string {
  return [base, name].filter(Boolean).join("/");
}

function formatBytes(n: number | null): string {
  if (n == null || n <= 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export function FilesPage() {
  const [docs, setDocs] = useState<DocumentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [cwd, setCwd] = useState(""); // current folder ("" = root)
  // Client-side pending (empty) folders the user just created — they have no
  // documents yet so they wouldn't appear from the derived tree otherwise.
  const [pendingFolders, setPendingFolders] = useState<string[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [uploading, setUploading] = useState<{ done: number; total: number } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [moveTarget, setMoveTarget] = useState<string[] | null>(null); // doc ids being moved
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  async function refresh() {
    setLoading(true);
    try {
      // Own uploads only — the shared regulator corpus is read-only and lives
      // in the Documents (knowledge base) view, not here.
      const d = await listDocuments({ docType: "uploads", limit: 500 });
      setDocs(d);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  // Clear selection when changing folder.
  useEffect(() => {
    setSelected(new Set());
  }, [cwd]);

  const allFolders = useMemo(() => {
    const set = new Set<string>();
    for (const d of docs) {
      const f = docFolder(d);
      if (!f) continue;
      // Register every ancestor prefix so intermediate folders are navigable.
      const parts = f.split("/");
      for (let i = 1; i <= parts.length; i++) set.add(parts.slice(0, i).join("/"));
    }
    for (const p of pendingFolders) set.add(p);
    return set;
  }, [docs, pendingFolders]);

  // Immediate subfolders of cwd.
  const subfolders = useMemo(() => {
    const prefix = cwd ? cwd + "/" : "";
    const names = new Set<string>();
    for (const full of allFolders) {
      if (cwd ? full.startsWith(prefix) : true) {
        const rest = cwd ? full.slice(prefix.length) : full;
        const name = rest.split("/")[0];
        if (name) names.add(name);
      }
    }
    return Array.from(names).sort();
  }, [allFolders, cwd]);

  // Files directly in cwd.
  const filesHere = useMemo(
    () => docs.filter((d) => docFolder(d) === cwd),
    [docs, cwd],
  );

  function folderFileCount(full: string): number {
    const prefix = full + "/";
    return docs.filter((d) => {
      const f = docFolder(d);
      return f === full || f.startsWith(prefix);
    }).length;
  }

  // ---- Upload (bulk) -------------------------------------------------------
  async function uploadFiles(files: FileList | File[]) {
    const arr = Array.from(files);
    if (arr.length === 0) return;
    setError(null);
    setUploading({ done: 0, total: arr.length });
    let failed = 0;
    for (let i = 0; i < arr.length; i++) {
      try {
        const res = await uploadDocument(arr[i]);
        // Place it in the current folder (upload ingests at root, then we move).
        if (cwd && res.document_id) {
          await updateDocument(res.document_id, { folder: cwd });
        }
      } catch (err) {
        failed += 1;
        setError(`Some files failed to upload: ${(err as Error).message}`);
      }
      setUploading({ done: i + 1, total: arr.length });
    }
    setUploading(null);
    // The uploaded docs now exist in cwd → the pending marker is redundant.
    setPendingFolders((p) => p.filter((f) => f !== cwd));
    await refresh();
    if (failed === 0) setError(null);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files?.length) uploadFiles(e.dataTransfer.files);
  }

  // ---- Selection -----------------------------------------------------------
  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  function toggleAll() {
    setSelected((prev) =>
      prev.size === filesHere.length ? new Set() : new Set(filesHere.map((d) => d.id)),
    );
  }

  // ---- Actions -------------------------------------------------------------
  async function doDelete(ids: string[]) {
    if (ids.length === 0) return;
    const ok = window.confirm(
      `Permanently delete ${ids.length} document${ids.length === 1 ? "" : "s"}? ` +
        "This removes the file, its index, and its stored original. This cannot be undone.",
    );
    if (!ok) return;
    setError(null);
    for (const id of ids) {
      const success = await deleteDocument(id);
      if (!success) setError("Some documents could not be deleted.");
    }
    setSelected(new Set());
    await refresh();
  }

  async function doMove(ids: string[], destination: string) {
    setError(null);
    for (const id of ids) {
      const res = await updateDocument(id, { folder: destination });
      if (!res) setError("Some documents could not be moved.");
    }
    setMoveTarget(null);
    setSelected(new Set());
    await refresh();
  }

  async function openFile(id: string) {
    const url = await getDocumentFileUrl(id);
    if (url) window.open(url, "_blank", "noopener,noreferrer");
    else setError("Could not open file — your session may have expired.");
  }

  function newFolder() {
    const name = window.prompt("New folder name");
    if (!name) return;
    const cleaned = name.trim().replace(/[/\\]/g, "-");
    if (!cleaned) return;
    const full = joinFolder(cwd, cleaned);
    setPendingFolders((p) => (p.includes(full) ? p : [...p, full]));
    setCwd(full);
  }

  const crumbs = cwd ? cwd.split("/") : [];

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <header className="border-b border-slate-200 bg-white px-6 py-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="min-w-0">
              <h1 className="text-lg font-semibold">My files</h1>
              {/* Breadcrumb */}
              <div className="mt-0.5 text-xs text-ink-500 flex items-center gap-1 flex-wrap">
                <button
                  onClick={() => setCwd("")}
                  className={"hover:text-ink-900 " + (cwd === "" ? "font-medium text-ink-900" : "")}
                >
                  Root
                </button>
                {crumbs.map((c, i) => {
                  const path = crumbs.slice(0, i + 1).join("/");
                  return (
                    <span key={path} className="flex items-center gap-1">
                      <span className="text-ink-300">/</span>
                      <button
                        onClick={() => setCwd(path)}
                        className={
                          "hover:text-ink-900 " +
                          (i === crumbs.length - 1 ? "font-medium text-ink-900" : "")
                        }
                      >
                        {c}
                      </button>
                    </span>
                  );
                })}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={newFolder}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm hover:bg-slate-100 inline-flex items-center gap-2"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2Z" />
                  <line x1="12" y1="11" x2="12" y2="17" />
                  <line x1="9" y1="14" x2="15" y2="14" />
                </svg>
                New folder
              </button>
              <button
                onClick={() => fileInputRef.current?.click()}
                className="rounded-md bg-ink-900 px-3 py-2 text-sm text-white hover:bg-ink-700 inline-flex items-center gap-2"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="17 8 12 3 7 8" />
                  <line x1="12" y1="3" x2="12" y2="15" />
                </svg>
                Upload
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(e) => {
                  if (e.target.files) uploadFiles(e.target.files);
                  e.target.value = "";
                }}
              />
            </div>
          </div>
        </header>

        {/* Selection toolbar */}
        {selected.size > 0 && (
          <div className="border-b border-slate-200 bg-ink-900 text-white px-6 py-2 flex items-center gap-3 text-sm">
            <span>{selected.size} selected</span>
            <button
              onClick={() => setMoveTarget(Array.from(selected))}
              className="rounded px-2 py-1 hover:bg-white/10"
            >
              Move to…
            </button>
            <button
              onClick={() => doDelete(Array.from(selected))}
              className="rounded px-2 py-1 text-rose-200 hover:bg-white/10"
            >
              Delete
            </button>
            <button
              onClick={() => setSelected(new Set())}
              className="ml-auto rounded px-2 py-1 hover:bg-white/10"
            >
              Clear
            </button>
          </div>
        )}

        {error && (
          <div className="bg-rose-50 border-b border-rose-200 px-6 py-2 text-sm text-rose-800">
            {error}
          </div>
        )}
        {uploading && (
          <div className="bg-blue-50 border-b border-blue-200 px-6 py-2 text-sm text-blue-900">
            Uploading… {uploading.done}/{uploading.total}
          </div>
        )}

        {/* Body */}
        <div
          className={
            "flex-1 overflow-y-auto p-6 " + (dragOver ? "bg-blue-50" : "bg-slate-50")
          }
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          {loading ? (
            <div className="text-sm text-ink-500">Loading…</div>
          ) : (
            <div className="max-w-4xl mx-auto space-y-4">
              {/* Folders */}
              {subfolders.length > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
                  {subfolders.map((name) => {
                    const full = joinFolder(cwd, name);
                    return (
                      <button
                        key={full}
                        onClick={() => setCwd(full)}
                        className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-3 text-left hover:border-ink-300 hover:bg-slate-50"
                      >
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-amber-500 shrink-0">
                          <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2Z" />
                        </svg>
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-ink-900">
                            {name}
                          </span>
                          <span className="block text-xs text-ink-500">
                            {folderFileCount(full)} item
                            {folderFileCount(full) === 1 ? "" : "s"}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Files table */}
              <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
                <div className="flex items-center px-4 py-2 border-b border-slate-200 text-xs font-semibold uppercase tracking-wide text-ink-500">
                  <input
                    type="checkbox"
                    className="mr-3"
                    checked={filesHere.length > 0 && selected.size === filesHere.length}
                    onChange={toggleAll}
                    aria-label="Select all"
                  />
                  <span className="flex-1">Name</span>
                  <span className="w-24 text-right">Size</span>
                  <span className="w-28 text-right">Added</span>
                  <span className="w-28 text-right">Actions</span>
                </div>
                {filesHere.length === 0 ? (
                  <div className="p-8 text-center text-sm text-ink-500">
                    {subfolders.length > 0
                      ? "No files in this folder. Open a subfolder, or drop files here to upload."
                      : "No files here yet. Drag & drop files anywhere, or use Upload."}
                  </div>
                ) : (
                  <ul className="divide-y divide-slate-100">
                    {filesHere.map((d) => (
                      <li
                        key={d.id}
                        className={
                          "flex items-center px-4 py-2.5 text-sm hover:bg-slate-50 " +
                          (selected.has(d.id) ? "bg-slate-50" : "")
                        }
                      >
                        <input
                          type="checkbox"
                          className="mr-3"
                          checked={selected.has(d.id)}
                          onChange={() => toggle(d.id)}
                          aria-label={`Select ${d.title}`}
                        />
                        <button
                          onClick={() => openFile(d.id)}
                          className="flex-1 min-w-0 text-left flex items-center gap-2"
                          title="Open original"
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-ink-400 shrink-0">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                            <polyline points="14 2 14 8 20 8" />
                          </svg>
                          <span className="truncate text-ink-900">{d.title}</span>
                        </button>
                        <span className="w-24 text-right text-ink-500 tabular-nums">
                          {formatBytes(d.size_bytes)}
                        </span>
                        <span className="w-28 text-right text-ink-500">
                          {new Date(d.created_at).toLocaleDateString()}
                        </span>
                        <span className="w-28 text-right flex justify-end gap-1">
                          <button
                            onClick={() => setMoveTarget([d.id])}
                            className="rounded p-1 text-ink-500 hover:bg-slate-200 hover:text-ink-900"
                            title="Move"
                            aria-label="Move"
                          >
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8l-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2Z" />
                            </svg>
                          </button>
                          <button
                            onClick={() => doDelete([d.id])}
                            className="rounded p-1 text-ink-500 hover:bg-rose-100 hover:text-rose-700"
                            title="Delete"
                            aria-label="Delete"
                          >
                            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <polyline points="3 6 5 6 21 6" />
                              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                            </svg>
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <p className="text-xs text-ink-500 text-center">
                Tip: drag &amp; drop files anywhere on this page to upload them into{" "}
                <strong>{cwd || "Root"}</strong>.
              </p>
            </div>
          )}
        </div>
      </main>

      {moveTarget && (
        <MoveModal
          count={moveTarget.length}
          folders={Array.from(allFolders).sort()}
          current={cwd}
          onCancel={() => setMoveTarget(null)}
          onMove={(dest) => doMove(moveTarget, dest)}
        />
      )}
    </div>
  );
}

function MoveModal({
  count,
  folders,
  current,
  onCancel,
  onMove,
}: {
  count: number;
  folders: string[];
  current: string;
  onCancel: () => void;
  onMove: (destination: string) => void;
}) {
  const [dest, setDest] = useState(current);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onCancel}>
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-slate-200">
          <h2 className="text-sm font-semibold">
            Move {count} document{count === 1 ? "" : "s"}
          </h2>
        </div>
        <div className="p-5 space-y-3">
          <label className="block text-xs text-ink-500">
            Destination folder (leave blank for Root)
          </label>
          <input
            list="folder-options"
            value={dest}
            onChange={(e) => setDest(e.target.value)}
            placeholder="e.g. contracts/2026"
            className="w-full rounded border border-slate-300 px-3 py-2 text-sm focus:border-ink-500 focus:outline-none"
            autoFocus
          />
          <datalist id="folder-options">
            {folders.map((f) => (
              <option key={f} value={f} />
            ))}
          </datalist>
          <div className="flex justify-end gap-2 pt-1">
            <button
              onClick={onCancel}
              className="rounded px-3 py-2 text-sm text-ink-600 hover:bg-slate-100"
            >
              Cancel
            </button>
            <button
              onClick={() => onMove(dest)}
              className="rounded bg-ink-900 px-3 py-2 text-sm text-white hover:bg-ink-700"
            >
              Move
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
