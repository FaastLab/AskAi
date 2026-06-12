"""Unit tests for the #6 policy engine (pure)."""

from __future__ import annotations

import pytest

from faastlab_askai_core.exceptions import PolicyViolation
from faastlab_askai_core.gateway import Policy, PolicyEngine, resolve_policy

ENGINE = PolicyEngine()


def test_resolve_defaults_permissive() -> None:
    p = resolve_policy(None)
    assert p.enabled is True
    assert p.allowed_models == ()
    assert p.max_tokens_per_request == 0
    assert p.has_restrictions is False


def test_resolve_from_settings() -> None:
    p = resolve_policy(
        {
            "gateway": {
                "policy": {
                    "enabled": False,
                    "allowed_models": ["qwen", " ", "gpt-4o"],
                    "max_tokens_per_request": "800",
                }
            }
        }
    )
    assert p.enabled is False
    assert p.allowed_models == ("qwen", "gpt-4o")  # blanks dropped
    assert p.max_tokens_per_request == 800
    assert p.has_restrictions is True


def test_enforce_allows_default() -> None:
    ENGINE.enforce(resolve_policy(None), model="anything")  # no raise


def test_enforce_blocks_when_disabled() -> None:
    with pytest.raises(PolicyViolation):
        ENGINE.enforce(Policy(enabled=False), model="qwen")


def test_enforce_blocks_model_not_in_allowlist() -> None:
    with pytest.raises(PolicyViolation):
        ENGINE.enforce(Policy(allowed_models=("qwen",)), model="gpt-4o")


def test_enforce_allows_model_in_allowlist() -> None:
    ENGINE.enforce(Policy(allowed_models=("qwen", "gpt-4o")), model="qwen")


def test_effective_max_tokens_no_cap() -> None:
    assert ENGINE.effective_max_tokens(Policy(), 1400) == 1400
    assert ENGINE.effective_max_tokens(Policy(), None) is None


def test_effective_max_tokens_clamps() -> None:
    p = Policy(max_tokens_per_request=500)
    assert ENGINE.effective_max_tokens(p, 1400) == 500  # clamped down
    assert ENGINE.effective_max_tokens(p, 300) == 300  # under cap, unchanged
    assert ENGINE.effective_max_tokens(p, None) == 500  # default to cap
