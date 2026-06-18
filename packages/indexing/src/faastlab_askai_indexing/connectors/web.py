"""Web connector — config-driven crawling of URLs, sitemaps, and child pages.

Plugs into the normal `IngestionPipeline` (it yields `SourceDocument`s like
any other connector). Three modes:

* **page**    — fetch exactly the configured start URLs.
* **sitemap** — fetch each start URL as a `sitemap.xml`, expand `<loc>` entries.
* **crawl**   — breadth-first follow of in-page links, restricted to a URL
                prefix, bounded by `max_depth` and `max_pages`.

The frontier logic — URL normalisation, link/sitemap extraction, and the
follow decision — is pure and unit-tested; only `iter_documents()` touches the
network (httpx). Crawls are deliberately bounded and single-flight so a
misconfigured connector can't hammer a site or run away.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from html import unescape as _html_unescape
from urllib.parse import urldefrag, urljoin, urlparse

import httpx

from faastlab_askai_indexing.connectors.base import SourceDocument

log = logging.getLogger(__name__)

_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\'#]+)["\']', re.IGNORECASE)
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

_USER_AGENT = "FaastLabAskAiBot/1.0 (+https://askai.faastlab.ai)"


@dataclass(slots=True)
class WebCrawlConfig:
    start_urls: list[str]
    mode: str = "crawl"  # page | sitemap | crawl
    url_prefix: str | None = None
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    max_pages: int = 50
    max_depth: int = 2
    doc_type: str | None = None


def normalize_url(url: str) -> str:
    """Drop the fragment and trailing slash so the same page isn't crawled
    twice under cosmetically different URLs. Keeps the query string (it can be
    semantically significant) and the scheme/host as-is."""
    clean, _frag = urldefrag(url.strip())
    if clean.endswith("/") and urlparse(clean).path not in ("", "/"):
        clean = clean.rstrip("/")
    return clean


def extract_links(html: str, base_url: str) -> list[str]:
    """Absolute, http(s) links discovered in `html`, resolved against
    `base_url`, de-duplicated in document order."""
    out: list[str] = []
    seen: set[str] = set()
    for href in _HREF_RE.findall(html):
        absolute = normalize_url(urljoin(base_url, href))
        if not absolute.lower().startswith(("http://", "https://")):
            continue
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
    return out


def extract_sitemap_urls(xml: str) -> list[str]:
    """URLs from a sitemap (or sitemap-index) `<loc>` entries, de-duplicated."""
    out: list[str] = []
    seen: set[str] = set()
    for loc in _LOC_RE.findall(xml):
        url = normalize_url(loc)
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def extract_title(html: str) -> str | None:
    m = _TITLE_RE.search(html)
    if not m:
        return None
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    # Decode HTML entities so titles read "Handbook & Rulebook", not
    # "Handbook &amp; Rulebook". (Param is named `html`, so we use the
    # aliased unescape import.)
    return _html_unescape(title) or None


def should_follow(url: str, cfg: WebCrawlConfig, depth: int) -> bool:
    """Whether the crawler should enqueue `url` at `depth`.

    Enforces (in order): http(s) scheme, depth bound, the URL-prefix scope
    (defaults to the prefix of the first start URL so a crawl can't wander off
    the seed site), the exclude list (any substring match rejects), and the
    include list (if non-empty, at least one substring must match).
    """
    if not url.lower().startswith(("http://", "https://")):
        return False
    if depth > cfg.max_depth:
        return False
    prefix = cfg.url_prefix or _default_prefix(cfg)
    if prefix and not url.startswith(prefix):
        return False
    if any(bad in url for bad in cfg.exclude):
        return False
    if cfg.include and not any(good in url for good in cfg.include):
        return False
    return True


def _default_prefix(cfg: WebCrawlConfig) -> str | None:
    """Scope a prefix-less crawl to the directory of the first start URL."""
    if not cfg.start_urls:
        return None
    first = cfg.start_urls[0]
    parsed = urlparse(first)
    if not parsed.scheme:
        return None
    path = first.rsplit("/", 1)[0] if "/" in parsed.path.lstrip("/") else first
    return path


class WebConnector:
    """Async connector that crawls the web per a `WebCrawlConfig`."""

    def __init__(
        self,
        config: WebCrawlConfig,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._cfg = config
        self._client = client
        self._timeout = timeout

    async def iter_documents(self) -> AsyncIterator[SourceDocument]:
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )
        try:
            async for doc in self._crawl(client):
                yield doc
        finally:
            if own_client:
                await client.aclose()

    async def _seed_urls(self, client: httpx.AsyncClient) -> list[tuple[str, int]]:
        """Initial frontier: (url, depth) pairs. Sitemap mode expands here."""
        starts = [normalize_url(u) for u in self._cfg.start_urls if u.strip()]
        if self._cfg.mode != "sitemap":
            return [(u, 0) for u in starts]
        seeded: list[tuple[str, int]] = []
        for sm in starts:
            try:
                resp = await client.get(sm)
                resp.raise_for_status()
                for url in extract_sitemap_urls(resp.text):
                    seeded.append((url, 0))
            except Exception as exc:
                log.warning("web: sitemap fetch failed %s: %s", sm, exc)
        return seeded

    async def _crawl(self, client: httpx.AsyncClient) -> AsyncIterator[SourceDocument]:
        cfg = self._cfg
        frontier: deque[tuple[str, int]] = deque(await self._seed_urls(client))
        visited: set[str] = set()
        emitted = 0

        while frontier and emitted < cfg.max_pages:
            url, depth = frontier.popleft()
            if url in visited:
                continue
            visited.add(url)

            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                log.warning("web: fetch failed %s: %s", url, exc)
                continue

            content_type = (resp.headers.get("content-type") or "").split(";")[0].strip()
            body = resp.content
            is_html = "html" in content_type or content_type == ""

            # Only HTML/text and PDFs are worth indexing; skip images etc.
            if content_type and not (is_html or "pdf" in content_type or "text" in content_type):
                continue

            yield SourceDocument(
                source_uri=url,
                data=body,
                filename=url.rsplit("/", 1)[-1] or "page",
                content_type=content_type or "text/html",
                title=extract_title(resp.text) if is_html else None,
                metadata={
                    "connector": "web",
                    "doc_type": cfg.doc_type,
                    "crawl_depth": depth,
                },
            )
            emitted += 1

            # Only the crawl mode follows links; page/sitemap are flat lists.
            if cfg.mode == "crawl" and is_html and depth < cfg.max_depth:
                for link in extract_links(resp.text, url):
                    if link not in visited and should_follow(link, cfg, depth + 1):
                        frontier.append((link, depth + 1))
