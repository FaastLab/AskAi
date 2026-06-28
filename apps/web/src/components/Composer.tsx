import { useRef, useState, type ReactNode } from "react";
import { transcribeAudio } from "../lib/api";

export function Composer({
  onSubmit,
  disabled,
  controls,
}: {
  onSubmit: (q: string) => void;
  disabled?: boolean;
  // Optional controls rendered as a column to the LEFT of the textbox (e.g. the
  // role selector) — stacked vertically beside the input.
  controls?: ReactNode;
}) {
  const [value, setValue] = useState("");

  const submit = () => {
    const q = value.trim();
    if (!q) return;
    onSubmit(q);
    setValue("");
  };

  // --- Mic: record → Whisper → submit as a normal (grounded) question --------
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  async function toggleMic() {
    setMicError(null);
    if (recording) {
      recorderRef.current?.stop(); // triggers onstop below
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        if (!blob.size) return;
        setTranscribing(true);
        try {
          const text = (await transcribeAudio(blob)).trim();
          // Submit straight through the normal /ask flow so the spoken question
          // is grounded in the corpus (with the selected role + citations). The
          // transcript shows as the user's message bubble.
          if (text) onSubmit(text);
        } catch {
          setMicError("Couldn't transcribe — try again.");
        } finally {
          setTranscribing(false);
        }
      };
      recorderRef.current = mr;
      mr.start();
      setRecording(true);
    } catch {
      setMicError("Mic access denied.");
    }
  }

  const micBusy = transcribing;

  return (
    <div className="border-t border-slate-200 bg-white p-4">
      <div className="max-w-3xl mx-auto flex gap-2 items-start">
        {controls && (
          <div className="flex flex-col gap-1 shrink-0 w-36">{controls}</div>
        )}
        <textarea
          className="flex-1 rounded-md border border-slate-300 p-3 text-sm
                     focus:outline-none focus:ring-2 focus:ring-ink-900"
          rows={2}
          placeholder={
            recording
              ? "Listening… tap the mic to stop"
              : transcribing
                ? "Transcribing…"
                : "Ask a question about UK financial regulation…"
          }
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        {/* Mic: tap to record, tap again to stop + ask */}
        <button
          onClick={toggleMic}
          disabled={disabled || micBusy}
          title={recording ? "Stop & ask" : "Ask by voice"}
          className={
            "rounded-md px-3 text-sm border disabled:opacity-50 " +
            (recording
              ? "bg-red-600 text-white border-red-600 animate-pulse"
              : "bg-white text-ink-700 border-slate-300 hover:bg-slate-100")
          }
        >
          {micBusy ? "…" : recording ? "■" : "🎙"}
        </button>
        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          className="rounded-md bg-ink-900 text-white px-4 text-sm
                     hover:bg-ink-700 disabled:opacity-50"
        >
          Send
        </button>
      </div>
      {micError && (
        <div className="max-w-3xl mx-auto mt-1 text-xs text-red-700">{micError}</div>
      )}
    </div>
  );
}
