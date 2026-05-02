# `apps/web`

Phase 9 — Vite + React + TypeScript + Tailwind chat UI.

## Run

```bash
make ui
# in another terminal:
make dev   # starts the FastAPI server on :8000
```

The Vite dev server runs on `:3000` and proxies `/v1/*` to `:8000`,
so SSE works without CORS faff.

## Layout

```
apps/web/
├── package.json / vite.config.ts / tsconfig.json / tailwind.config.js
├── index.html
└── src/
    ├── main.tsx                # bootstrap + BrowserRouter
    ├── App.tsx                 # /chat[/:sessionId] route
    ├── styles/index.css        # tailwind base
    ├── lib/api.ts              # streamAsk() — SSE consumer
    ├── components/
    │   ├── Sidebar.tsx         # session list, "+ New chat"
    │   ├── Composer.tsx        # textarea + submit
    │   └── Message.tsx         # markdown body + Citations footer
    └── pages/Chat.tsx          # full split-pane chat
```

## What it does

- Single-page chat with streaming answers (tokens render as they arrive).
- Citations block under each assistant message, linked back to source
  documents and page numbers.
- Session sidebar — pick a previous conversation or start a new one.
- React Router URLs — `/chat/<session-id>` is shareable.

## Production build

```bash
cd apps/web && npm install && npm run build
# → dist/ (serve via nginx or any static host; the Helm chart is set up
#   to terminate SSE at the API ingress, not the UI).
```
