# FaastLab AskAi — Regulator Watcher

Polls UK regulator news feeds, dedupes events, persists them to Postgres,
and notifies via console / DB / generic HTTP webhook. Slack and email
notifiers are planned next.

## Supported regulators (v1)

| Code | Regulator | Default feed |
|------|-----------|--------------|
| `fca` | Financial Conduct Authority | https://www.fca.org.uk/news/rss.xml |
| `boe` | Bank of England | https://www.bankofengland.co.uk/rss/news |
| `pra` | Prudential Regulation Authority | https://www.bankofengland.co.uk/rss/prudential-regulation/publications |
| `fos` | Financial Ombudsman Service | https://www.financial-ombudsman.org.uk/rss/news |
| `tpr` | The Pensions Regulator | https://www.thepensionsregulator.gov.uk/rss/news |

All URLs are configurable via env vars (see `WATCHER_*` settings in
`packages/core/src/faastlab_askai_core/config/settings.py`). Feeds that
don't expose RSS fall back to HTML scrape adapters.

## Run it

```bash
# One-shot poll (CLI):
python -m faastlab_askai_watcher poll

# Just FCA:
python -m faastlab_askai_watcher poll --regulator fca

# Scheduled (Celery Beat): see tasks.py — wired into the existing worker.
```

## Notifications

Each new event is fanned out to every configured notifier:

- **Console** — always on; logs at INFO level.
- **DB** — always on; persists to `watcher_events` (unique on `(regulator, external_id)` for idempotency).
- **Webhook** — opt-in; set `WATCHER_WEBHOOK_URL` and the watcher POSTs each event as JSON.
- _Slack_ — planned.

## Adding a new feed

1. Drop a new `FeedSource` subclass into `feeds/` (typically just a config
   line in `feeds/registry.py` if it's a standard RSS feed).
2. Register it in `feeds/registry.py`.
3. Add the URL to settings.

That's it — no orchestrator changes needed.
