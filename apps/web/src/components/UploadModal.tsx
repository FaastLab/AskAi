import { useRef, useState } from "react";
import { uploadDocument, type UploadResult } from "../lib/api";

const ACCEPTED = ".pdf,.docx,.html,.htm,.md,.markdown,.txt";
const MAX_BYTES = 50 * 1024 * 1024; // 50 MB

type Status = "idle" | "uploading" | "success" | "error";

export function UploadModal({
  open,
  onClose,
  onUploaded,
}: {
  open: boolean;
  onClose: () => void;
  onUploaded?: (result: UploadResult) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [dragOver, setDragOver] = useState(false);

  if (!open) return null;

  const reset = () => {
    setFile(null);
    setStatus("idle");
    setError(null);
    setResult(null);
  };

  const close = () => {
    reset();
    onClose();
  };

  const pick = (f: File | null) => {
    if (!f) return;
    if (f.size > MAX_BYTES) {
      setError(`File too large — max 50 MB (got ${(f.size / 1024 / 1024).toFixed(1)} MB).`);
      setFile(null);
      return;
    }
    setError(null);
    setFile(f);
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) pick(f);
  };

  const upload = async () => {
    if (!file) return;
    setStatus("uploading");
    setError(null);
    try {
      const res = await uploadDocument(file);
      setResult(res);
      setStatus("success");
      onUploaded?.(res);
    } catch (err) {
      setStatus("error");
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-lg bg-white shadow-xl">
        <div className="border-b border-slate-200 px-5 py-3 flex items-center justify-between">
          <h2 className="text-base font-semibold">Add a document</h2>
          <button
            onClick={close}
            className="text-ink-500 hover:text-ink-900 text-sm"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {status === "success" && result ? (
            <div className="rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-900">
              <div className="font-medium">
                {result.status === "skipped"
                  ? "Already indexed"
                  : `Indexed ${result.chunks_written} chunks`}
              </div>
              <div className="text-xs text-green-700 mt-1">
                Document ID: <code className="font-mono">{result.document_id}</code>
              </div>
              <div className="text-xs text-green-700">
                {result.note || "Ready to query — try asking a question now."}
              </div>
            </div>
          ) : (
            <>
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                onDrop={onDrop}
                onClick={() => inputRef.current?.click()}
                className={`rounded-md border-2 border-dashed p-6 text-center cursor-pointer
                  ${dragOver ? "border-ink-900 bg-slate-50" : "border-slate-300"}
                  hover:bg-slate-50 transition-colors`}
              >
                <input
                  ref={inputRef}
                  type="file"
                  accept={ACCEPTED}
                  className="hidden"
                  onChange={(e) => pick(e.target.files?.[0] ?? null)}
                />
                {file ? (
                  <div className="text-sm">
                    <div className="font-medium">{file.name}</div>
                    <div className="text-xs text-ink-500 mt-1">
                      {(file.size / 1024 / 1024).toFixed(1)} MB
                    </div>
                  </div>
                ) : (
                  <div className="text-sm text-ink-500">
                    <div>
                      <strong className="text-ink-900">Click to choose</strong> or
                      drag a file here
                    </div>
                    <div className="text-xs mt-1">PDF · DOCX · HTML · Markdown · TXT (max 50 MB)</div>
                  </div>
                )}
              </div>

              <div className="text-xs text-ink-500 leading-relaxed">
                The document is parsed, chunked, embedded, and stored in your tenant —
                searchable immediately. Public regulator PDFs (BoE, FCA, PRA) work
                great. Private/confidential docs stay on the server.
              </div>

              {error && (
                <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">
                  {error}
                </div>
              )}
            </>
          )}
        </div>

        <div className="border-t border-slate-200 px-5 py-3 flex items-center justify-end gap-2">
          {status === "success" ? (
            <button
              onClick={close}
              className="rounded bg-ink-900 px-4 py-2 text-sm text-white hover:bg-ink-700"
            >
              Done
            </button>
          ) : (
            <>
              <button
                onClick={close}
                className="rounded border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50"
                disabled={status === "uploading"}
              >
                Cancel
              </button>
              <button
                onClick={upload}
                disabled={!file || status === "uploading"}
                className="rounded bg-ink-900 px-4 py-2 text-sm text-white hover:bg-ink-700 disabled:opacity-50"
              >
                {status === "uploading" ? "Indexing…" : "Upload & index"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
