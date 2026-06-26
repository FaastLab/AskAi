import { useState, type ReactNode } from "react";

export function Composer({
  onSubmit,
  disabled,
  footer,
}: {
  onSubmit: (q: string) => void;
  disabled?: boolean;
  // Optional left-aligned toolbar rendered directly below the textbox (e.g. the
  // role controls) — placed here so it sits at the lower-left of the input.
  footer?: ReactNode;
}) {
  const [value, setValue] = useState("");

  const submit = () => {
    const q = value.trim();
    if (!q) return;
    onSubmit(q);
    setValue("");
  };

  return (
    <div className="border-t border-slate-200 bg-white p-4">
      <div className="max-w-3xl mx-auto">
        <div className="flex gap-2">
          <textarea
            className="flex-1 rounded-md border border-slate-300 p-3 text-sm
                       focus:outline-none focus:ring-2 focus:ring-ink-900"
            rows={2}
            placeholder="Ask a question about UK financial regulation…"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <button
            onClick={submit}
            disabled={disabled || !value.trim()}
            className="rounded-md bg-ink-900 text-white px-4 text-sm
                       hover:bg-ink-700 disabled:opacity-50"
          >
            Send
          </button>
        </div>
        {footer && (
          <div className="mt-2 flex items-center gap-2 flex-wrap">{footer}</div>
        )}
      </div>
    </div>
  );
}
