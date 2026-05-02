# Security — secret-scanning workflow

AskAi commits go through a `pre-commit` hook that runs
[detect-secrets](https://github.com/Yelp/detect-secrets) against every
staged file. If a hook spots a likely secret (API key, private key, JWT,
high-entropy hex blob…) the commit is blocked.

## One-time setup per clone

```bash
uv sync --all-packages --dev    # installs pre-commit + detect-secrets
uv run pre-commit install       # registers the hook on `git commit`
```

That's it. From now on every `git commit` runs the suite.

## Re-baselining (when needed)

If detect-secrets flags a known false positive (e.g. a fixture string
that *looks* like a secret), update the baseline:

```bash
uv run detect-secrets scan --baseline .secrets.baseline
```

Review the diff before committing the new baseline.

## What gets blocked

- AWS access keys, Azure storage keys, GCP service-account JSON
- OpenAI / Anthropic / Cohere / Twilio / Slack / Stripe / SendGrid tokens
- GitHub / GitLab / Discord / Telegram bot tokens
- JWTs, RSA/ECDSA private keys
- High-entropy base64 / hex strings (heuristic)

## What's allowlisted

- Lock files (`uv.lock`, `package-lock.json`) — pinned hashes look
  high-entropy but aren't secrets.
- The baseline file itself.

## Rotating a leaked key

If a secret slips through and is committed, rotate it immediately:

1. **OpenAI**: <https://platform.openai.com/api-keys> → revoke + new key.
2. **Cohere**: <https://dashboard.cohere.com/api-keys>.
3. **JWT secret** (`JWT_SECRET` in `.env`): generate a new one, restart api.
4. Then scrub the leaked value from history with `git filter-repo`
   (preferred over `git filter-branch`).
5. Force-push and notify all collaborators to re-clone.

Then add the leaked value's pattern to the baseline so the hook would
have caught it next time.
