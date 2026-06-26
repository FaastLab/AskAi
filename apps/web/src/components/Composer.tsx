import { useState, type ReactNode } from "react";

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
    </div>
  );
}
