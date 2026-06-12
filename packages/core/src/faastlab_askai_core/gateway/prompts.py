"""Prompt registry — versioned, governed prompt templates.

Why this exists: an enterprise buyer asks "what exactly is the system telling
the model, and can you prove it didn't change under us?" Inlined f-strings
can't answer that. Here, prompts are named + versioned rows; one version is
active at a time; activation is a flip, not an edit, so history is auditable
and a regression rolls back by re-activating a prior version.

Usage:
    registry = PromptRegistry()
    text = await registry.render("rag.answer", question=q, context=ctx)

Code defaults: `register_default(name, template)` seeds an in-process
fallback used when the DB has no row for a name — so the system works before
anyone curates prompts in the DB, and DB curation is opt-in governance that
transparently overrides the default.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update

from faastlab_askai_core.db import Prompt, get_sessionmaker
from faastlab_askai_core.exceptions import PromptNotFoundError, PromptRenderError

log = logging.getLogger(__name__)

# Code-default templates, keyed by name. Lowest precedence — DB rows win.
_DEFAULTS: dict[str, str] = {}


def register_default(name: str, template: str) -> None:
    """Register an in-process default template for `name` (DB rows override)."""
    _DEFAULTS[name] = template


@dataclass(frozen=True, slots=True)
class PromptRecord:
    name: str
    version: str
    template: str
    source: str  # "db" | "default"

    def render(self, **variables: object) -> str:
        return render_template(self.template, variables)


@dataclass(frozen=True, slots=True)
class PromptVersion:
    version: str
    description: str | None
    is_active: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PromptSummary:
    name: str
    active_template: str
    active_version: str  # "default" when no DB version is active
    source: str  # "db" | "default"
    default_template: str | None  # the built-in code default, for "reset"
    versions: list[PromptVersion]


class _SafeMissing(dict):
    """Marks missing keys so render can raise a precise error."""

    def __missing__(self, key: str) -> str:
        raise KeyError(key)


def render_template(template: str, variables: dict[str, object]) -> str:
    """Fill `{placeholders}` in `template`. Extra variables are ignored;
    a missing one raises `PromptRenderError` (fail loud, not silently wrong)."""
    try:
        return template.format_map(_SafeMissing(variables))
    except KeyError as exc:
        raise PromptRenderError(
            f"prompt template missing variable: {exc.args[0]!r}"
        ) from exc


class PromptRegistry:
    """Resolves prompt templates from the DB, falling back to code defaults.

    Stateless aside from the process-wide `_DEFAULTS`; share one instance.
    """

    async def _fetch_active(self, name: str) -> Prompt | None:
        sm = get_sessionmaker()
        async with sm() as session:
            return (
                await session.execute(
                    select(Prompt)
                    .where(Prompt.name == name, Prompt.is_active.is_(True))
                    .order_by(Prompt.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

    async def _fetch_version(self, name: str, version: str) -> Prompt | None:
        sm = get_sessionmaker()
        async with sm() as session:
            return (
                await session.execute(
                    select(Prompt).where(
                        Prompt.name == name, Prompt.version == version
                    )
                )
            ).scalar_one_or_none()

    async def get(self, name: str, version: str | None = None) -> PromptRecord:
        """Return the requested prompt version, or the active one if `version`
        is None, or the code default if neither exists in the DB."""
        row = (
            await self._fetch_version(name, version)
            if version is not None
            else await self._fetch_active(name)
        )
        if row is not None:
            return PromptRecord(
                name=row.name, version=row.version, template=row.template, source="db"
            )
        # DB miss — fall back to a registered code default (active only).
        if version is None and name in _DEFAULTS:
            return PromptRecord(
                name=name, version="default", template=_DEFAULTS[name], source="default"
            )
        raise PromptNotFoundError(
            f"no prompt {name!r}"
            + (f" version {version!r}" if version else " (no active version or default)")
        )

    async def render(
        self, name: str, *, version: str | None = None, **variables: object
    ) -> str:
        """Convenience: fetch then render in one call."""
        record = await self.get(name, version)
        return record.render(**variables)

    # ---- Management (Prompts UI) -------------------------------------------

    async def list_all(self) -> list[PromptSummary]:
        """Every prompt the system knows: registered code defaults unioned with
        DB-curated versions. The active template is the DB-active row if any,
        else the code default."""
        sm = get_sessionmaker()
        async with sm() as session:
            rows = (
                await session.execute(select(Prompt).order_by(Prompt.created_at))
            ).scalars().all()

        by_name: dict[str, list[Prompt]] = {}
        for row in rows:
            by_name.setdefault(row.name, []).append(row)

        names = sorted(set(by_name) | set(_DEFAULTS))
        summaries: list[PromptSummary] = []
        for name in names:
            versions = by_name.get(name, [])
            active = next((v for v in versions if v.is_active), None)
            if active is not None:
                template, active_version, source = active.template, active.version, "db"
            else:
                template, active_version, source = _DEFAULTS.get(name, ""), "default", "default"
            summaries.append(
                PromptSummary(
                    name=name,
                    active_template=template,
                    active_version=active_version,
                    source=source,
                    default_template=_DEFAULTS.get(name),
                    versions=[
                        PromptVersion(
                            version=v.version,
                            description=v.description,
                            is_active=v.is_active,
                            created_at=v.created_at,
                        )
                        for v in reversed(versions)  # newest first
                    ],
                )
            )
        return summaries

    async def save_version(
        self,
        name: str,
        template: str,
        *,
        description: str | None = None,
        activate: bool = True,
    ) -> str:
        """Insert a new version of `name` (auto-numbered vN). When `activate`,
        deactivate the others and make this the live one. Returns the version."""
        sm = get_sessionmaker()
        async with sm() as session:
            count = (
                await session.execute(
                    select(Prompt).where(Prompt.name == name)
                )
            ).scalars().all()
            version = f"v{len(count) + 1}"
            if activate:
                await session.execute(
                    update(Prompt).where(Prompt.name == name).values(is_active=False)
                )
            session.add(
                Prompt(
                    name=name,
                    version=version,
                    template=template,
                    description=description,
                    is_active=activate,
                )
            )
            await session.commit()
        return version

    async def activate(self, name: str, version: str) -> None:
        """Make a specific version live (rollback/forward). Raises if missing."""
        sm = get_sessionmaker()
        async with sm() as session:
            exists = (
                await session.execute(
                    select(Prompt.id).where(
                        Prompt.name == name, Prompt.version == version
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                raise PromptNotFoundError(f"no prompt {name!r} version {version!r}")
            await session.execute(
                update(Prompt).where(Prompt.name == name).values(is_active=False)
            )
            await session.execute(
                update(Prompt)
                .where(Prompt.name == name, Prompt.version == version)
                .values(is_active=True)
            )
            await session.commit()
