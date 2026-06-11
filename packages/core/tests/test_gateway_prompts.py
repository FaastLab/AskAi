"""Unit tests for the AI gateway (#4) slice 3: versioned prompt registry.

`render_template` is pure. `PromptRegistry` DB fetches are stubbed so these
run without Postgres; default-fallback uses the in-process registry.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from faastlab_askai_core.exceptions import PromptNotFoundError, PromptRenderError
from faastlab_askai_core.gateway import (
    PromptRecord,
    PromptRegistry,
    register_default,
    render_template,
)

# ---- render_template (pure) -------------------------------------------------


def test_render_substitutes() -> None:
    assert render_template("Hi {name}", {"name": "Ada"}) == "Hi Ada"


def test_render_ignores_extra_vars() -> None:
    assert render_template("Hi {name}", {"name": "Ada", "unused": 1}) == "Hi Ada"


def test_render_missing_var_raises() -> None:
    with pytest.raises(PromptRenderError):
        render_template("Hi {name} from {place}", {"name": "Ada"})


def test_prompt_record_render() -> None:
    rec = PromptRecord(name="g", version="v1", template="Q: {q}", source="db")
    assert rec.render(q="why?") == "Q: why?"


# ---- registry: default fallback --------------------------------------------


async def test_get_falls_back_to_default(monkeypatch) -> None:
    reg = PromptRegistry()

    async def _none_active(_name):
        return None

    monkeypatch.setattr(reg, "_fetch_active", _none_active)
    register_default("test.greet", "Hello {who}")

    rec = await reg.get("test.greet")
    assert rec.source == "default"
    assert rec.version == "default"
    assert rec.render(who="world") == "Hello world"


async def test_db_row_overrides_default(monkeypatch) -> None:
    reg = PromptRegistry()
    register_default("test.override", "DEFAULT {x}")

    async def _active(_name):
        return SimpleNamespace(name="test.override", version="v2", template="DB {x}")

    monkeypatch.setattr(reg, "_fetch_active", _active)
    rec = await reg.get("test.override")
    assert rec.source == "db"
    assert rec.version == "v2"
    assert rec.render(x="!") == "DB !"


async def test_get_specific_version(monkeypatch) -> None:
    reg = PromptRegistry()

    async def _version(_name, version):
        assert version == "v3"
        return SimpleNamespace(name="p", version="v3", template="T")

    monkeypatch.setattr(reg, "_fetch_version", _version)
    rec = await reg.get("p", version="v3")
    assert rec.version == "v3" and rec.source == "db"


async def test_missing_without_default_raises(monkeypatch) -> None:
    reg = PromptRegistry()

    async def _none(_name):
        return None

    monkeypatch.setattr(reg, "_fetch_active", _none)
    with pytest.raises(PromptNotFoundError):
        await reg.get("test.nope.unique")


async def test_missing_specific_version_raises(monkeypatch) -> None:
    reg = PromptRegistry()
    # Even with a default registered, an explicit version miss is an error
    # (defaults only satisfy the "active" request).
    register_default("test.ver", "D")

    async def _none(_name, _version):
        return None

    monkeypatch.setattr(reg, "_fetch_version", _none)
    with pytest.raises(PromptNotFoundError):
        await reg.get("test.ver", version="v9")


async def test_render_convenience(monkeypatch) -> None:
    reg = PromptRegistry()

    async def _none_active(_name):
        return None

    monkeypatch.setattr(reg, "_fetch_active", _none_active)
    register_default("test.conv", "Answer in {lang}")
    assert await reg.render("test.conv", lang="English") == "Answer in English"
