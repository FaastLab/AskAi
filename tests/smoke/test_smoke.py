"""End-to-end smoke tests — run before every deploy.

These are deliberately HTTP-based and stateless. They hit a live API
(default localhost:8000, override with SMOKE_BASE_URL=https://askai.faastlab.ai)
and verify the critical paths still work.

Each test exists because we had a real regression that the test would
have caught immediately:

  - test_healthz_endpoint             → uvicorn / NPM routing
  - test_config_endpoint              → settings load
  - test_signup_and_login_flow        → auth round-trip
  - test_documents_list_visible       → shared-corpus union
  - test_documents_counts             → route order + counts shape
  - test_search_returns_real_hits     → 🟢 catches the embedding-update transaction bug
                                          that left chunks with [0.0]*1536 placeholders
  - test_ask_non_streaming_returns_answer_with_citations → catches RAG chain breakage
  - test_validator_packs_listed       → validator registry sanity
  - test_documents_counts_route_not_clashing_with_id_route → route-ordering regression
  - test_trial_user_can_ask_within_trial → trial-guard regression

Run:
    SMOKE_BASE_URL=https://askai.faastlab.ai \
    SMOKE_OPENAI_KEY=sk-... \
    make smoke
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

BASE_URL = os.environ.get("SMOKE_BASE_URL", "http://localhost:8000").rstrip("/")
OPENAI_KEY = os.environ.get("SMOKE_OPENAI_KEY")  # required for /search and /ask tests

KNOWN_GOOD_QUERY = "consumer duty"


@pytest.fixture(scope="session")
def http() -> httpx.Client:
    """Sync httpx client — sidesteps pytest-asyncio event-loop quirks for
    module-scoped fixtures that confused our async setup earlier."""
    with httpx.Client(timeout=httpx.Timeout(120.0), follow_redirects=True) as c:
        yield c


@pytest.fixture(scope="session")
def auth_session(http: httpx.Client) -> dict:
    """Sign up a throw-away tenant once per session and reuse the JWT."""
    email = f"smoke+{uuid.uuid4().hex[:8]}@faastlab.ai"
    payload = {
        "email": email,
        "password": "smoke-test-pass-1234!",
        "organisation": f"Smoke Test {uuid.uuid4().hex[:6]}",
    }
    r = http.post(f"{BASE_URL}/v1/auth/signup", json=payload)
    assert r.status_code == 201, f"signup failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data
    assert data["user"]["role"] == "owner"
    return data


# ---------------------------------------------------------------------------
# 1. Plumbing
# ---------------------------------------------------------------------------


def test_healthz_endpoint(http: httpx.Client) -> None:
    r = http.get(f"{BASE_URL}/healthz")
    assert r.status_code == 200, f"unexpected {r.status_code}: {r.text}"
    assert r.json()["status"] == "ok"


def test_config_endpoint(http: httpx.Client) -> None:
    r = http.get(f"{BASE_URL}/v1/config")
    assert r.status_code == 200
    body = r.json()
    assert "default_tenant" in body
    assert "llm_model" in body
    assert body["embeddings_dim"] in (1024, 1536, 3072)


# ---------------------------------------------------------------------------
# 2. Auth round-trip
# ---------------------------------------------------------------------------


def test_signup_and_login_flow(http: httpx.Client) -> None:
    email = f"smoke+{uuid.uuid4().hex[:8]}@faastlab.ai"
    pw = "smoke-test-pass-1234!"
    org = f"SmokeOrg {uuid.uuid4().hex[:6]}"

    # Signup
    r = http.post(
        f"{BASE_URL}/v1/auth/signup",
        json={"email": email, "password": pw, "organisation": org},
    )
    assert r.status_code == 201
    assert r.json()["access_token"]

    # Re-login with same creds
    r = http.post(f"{BASE_URL}/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200
    login_token = r.json()["access_token"]
    assert login_token

    # /auth/me with the JWT
    r = http.get(
        f"{BASE_URL}/v1/auth/me", headers={"Authorization": f"Bearer {login_token}"}
    )
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == email
    assert me["role"] == "owner"


# ---------------------------------------------------------------------------
# 3. Documents — shared-corpus union (new Pro tenant sees public corpus)
# ---------------------------------------------------------------------------


def test_documents_list_visible(http: httpx.Client, auth_session: dict) -> None:
    token = auth_session["access_token"]
    r = http.get(
        f"{BASE_URL}/v1/documents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    docs = r.json()
    assert isinstance(docs, list)
    assert len(docs) >= 1, "tenant sees no documents — shared corpus union broken"


def test_documents_counts(http: httpx.Client, auth_session: dict) -> None:
    token = auth_session["access_token"]
    r = http.get(
        f"{BASE_URL}/v1/documents/_counts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    counts = r.json()
    assert "total" in counts
    assert "uploads" in counts
    assert counts["uploads"] == 0


def test_documents_counts_route_not_clashing_with_id_route(
    http: httpx.Client, auth_session: dict
) -> None:
    """Regression guard: `/documents/_counts` must NOT be matched as a UUID
    by `/documents/{document_id}`."""
    token = auth_session["access_token"]
    r = http.get(
        f"{BASE_URL}/v1/documents/_counts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, dict)
    assert "total" in body


# ---------------------------------------------------------------------------
# 4. The big one — RAG retrieval actually returns hits
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not OPENAI_KEY, reason="needs SMOKE_OPENAI_KEY for embedding")
def test_search_returns_real_hits(http: httpx.Client, auth_session: dict) -> None:
    token = auth_session["access_token"]
    r = http.post(
        f"{BASE_URL}/v1/search",
        headers={
            "Authorization": f"Bearer {token}",
            "X-OpenAI-API-Key": OPENAI_KEY,
            "Content-Type": "application/json",
        },
        json={"query": KNOWN_GOOD_QUERY, "k": 5, "filters": {"only_active": True}},
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()
    hits = body.get("hits", [])
    assert len(hits) > 0, (
        f"search for {KNOWN_GOOD_QUERY!r} returned 0 hits — "
        "vector retrieval broken (embedding placeholders? wrong tenant union?)"
    )
    for h in hits:
        assert h["content"], "hit has empty content"
        assert h["score"] is not None


@pytest.mark.skipif(not OPENAI_KEY, reason="needs SMOKE_OPENAI_KEY for embedding")
def test_ask_non_streaming_returns_answer_with_citations(
    http: httpx.Client, auth_session: dict
) -> None:
    token = auth_session["access_token"]
    r = http.post(
        f"{BASE_URL}/v1/ask",
        headers={
            "Authorization": f"Bearer {token}",
            "X-OpenAI-API-Key": OPENAI_KEY,
            "Content-Type": "application/json",
        },
        json={
            "query": f"What does the FCA say about {KNOWN_GOOD_QUERY}?",
            "stream": False,
            "filters": {},
        },
        timeout=120.0,
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    body = r.json()
    assert "answer" in body
    assert "citations" in body
    # Refusal text is exactly 128 chars — anything longer means real answer.
    assert len(body["answer"]) > 200, (
        f"ask returned a stub answer ({len(body['answer'])} chars) — "
        "likely the no-context refusal. Retrieval broken."
    )
    assert len(body["citations"]) > 0, "answer has no citations — RAG citing broken"


# ---------------------------------------------------------------------------
# 5. Validator + trial guard
# ---------------------------------------------------------------------------


def test_validator_packs_listed(http: httpx.Client, auth_session: dict) -> None:
    token = auth_session["access_token"]
    r = http.get(
        f"{BASE_URL}/v1/validators/packs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    packs = r.json()
    pack_ids = {p["id"] for p in packs}
    assert "fca-consumer-duty" in pack_ids
    assert "hmrc-aml" in pack_ids
    assert "uk-gdpr" in pack_ids
    for p in packs:
        assert len(p["requirements"]) >= 1


def test_trial_user_can_ask_within_trial(
    http: httpx.Client, auth_session: dict
) -> None:
    """New tenant signup → 14-day trial → /v1/ask should NOT 402."""
    token = auth_session["access_token"]
    r = http.post(
        f"{BASE_URL}/v1/ask",
        headers={
            "Authorization": f"Bearer {token}",
            "X-OpenAI-API-Key": OPENAI_KEY or "sk-smoke-test-placeholder",
            "Content-Type": "application/json",
        },
        json={"query": "hello", "stream": False, "filters": {}},
        timeout=60.0,
    )
    assert r.status_code != 402, "trial guard blocked a brand-new trial user"
