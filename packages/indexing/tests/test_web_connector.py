"""Unit tests for the web connector — pure frontier logic + a mocked crawl."""

from __future__ import annotations

import httpx
import respx

from faastlab_askai_indexing.connectors.web import (
    WebConnector,
    WebCrawlConfig,
    extract_links,
    extract_sitemap_urls,
    extract_title,
    normalize_url,
    should_follow,
)

# ---- pure helpers ----------------------------------------------------------


def test_normalize_url_strips_fragment_and_trailing_slash() -> None:
    assert normalize_url("https://x.com/a/#frag") == "https://x.com/a"
    assert normalize_url("https://x.com/") == "https://x.com/"  # root slash kept


def test_extract_links_resolves_relative_and_filters() -> None:
    html = (
        '<a href="/manual/CG10100">x</a>'
        '<a href="https://other.com/y">y</a>'
        '<a href="mailto:a@b.com">mail</a>'
        '<a href="#top">anchor</a>'
    )
    links = extract_links(html, "https://gov.uk/manual/index")
    assert "https://gov.uk/manual/CG10100" in links
    assert "https://other.com/y" in links
    assert not any(link.startswith("mailto:") for link in links)


def test_extract_links_dedups() -> None:
    html = '<a href="/a">1</a><a href="/a">2</a>'
    assert extract_links(html, "https://x.com/") == ["https://x.com/a"]


def test_extract_sitemap_urls() -> None:
    xml = "<urlset><url><loc>https://x.com/a</loc></url><url><loc>https://x.com/b</loc></url></urlset>"
    assert extract_sitemap_urls(xml) == ["https://x.com/a", "https://x.com/b"]


def test_extract_title() -> None:
    assert extract_title("<title>  Hello\n World </title>") == "Hello World"
    assert extract_title("<p>no title</p>") is None


def test_should_follow_enforces_depth() -> None:
    cfg = WebCrawlConfig(start_urls=["https://x.com/m/"], max_depth=2)
    assert should_follow("https://x.com/m/a", cfg, depth=2) is True
    assert should_follow("https://x.com/m/a", cfg, depth=3) is False


def test_should_follow_enforces_prefix() -> None:
    cfg = WebCrawlConfig(start_urls=["https://x.com/m"], url_prefix="https://x.com/m")
    assert should_follow("https://x.com/m/a", cfg, depth=1) is True
    assert should_follow("https://x.com/other", cfg, depth=1) is False


def test_should_follow_include_exclude() -> None:
    cfg = WebCrawlConfig(
        start_urls=["https://x.com/"],
        url_prefix="https://x.com",
        include=["/manual/"],
        exclude=["/print"],
    )
    assert should_follow("https://x.com/manual/CG1", cfg, 1) is True
    assert should_follow("https://x.com/manual/CG1/print", cfg, 1) is False  # excluded
    assert should_follow("https://x.com/news/1", cfg, 1) is False  # not included


# ---- mocked crawl ----------------------------------------------------------


@respx.mock
async def test_crawl_follows_children_under_prefix_and_caps() -> None:
    base = "https://gov.uk/hmrc-manual"
    index_html = (
        '<html><title>HMRC Manual</title><body>'
        f'<a href="{base}/CG10100">CG10100</a>'
        f'<a href="{base}/CG10200">CG10200</a>'
        '<a href="https://elsewhere.com/x">offsite</a>'
        '</body></html>'
    )
    respx.get(base).mock(
        return_value=httpx.Response(200, html=index_html, headers={"content-type": "text/html"})
    )
    for page in ("CG10100", "CG10200"):
        respx.get(f"{base}/{page}").mock(
            return_value=httpx.Response(
                200,
                html=f"<title>{page}</title><p>rule text</p>",
                headers={"content-type": "text/html"},
            )
        )

    cfg = WebCrawlConfig(
        start_urls=[base], mode="crawl", url_prefix=base, max_pages=10, max_depth=2
    )
    docs = [d async for d in WebConnector(cfg).iter_documents()]
    uris = {d.source_uri for d in docs}

    # Crawled the index + both child rule pages, but not the offsite link.
    assert base in uris
    assert f"{base}/CG10100" in uris
    assert f"{base}/CG10200" in uris
    assert "https://elsewhere.com/x" not in uris


@respx.mock
async def test_crawl_respects_max_pages() -> None:
    base = "https://x.com/a"
    html = "".join(f'<a href="https://x.com/a/{i}">{i}</a>' for i in range(20))
    html_headers = {"content-type": "text/html"}
    respx.get(base).mock(
        return_value=httpx.Response(200, html=f"<body>{html}</body>", headers=html_headers)
    )
    respx.get(url__startswith="https://x.com/a/").mock(
        return_value=httpx.Response(200, html="<p>x</p>", headers=html_headers)
    )
    cfg = WebCrawlConfig(
        start_urls=[base], mode="crawl", url_prefix=base, max_pages=5, max_depth=2
    )
    docs = [d async for d in WebConnector(cfg).iter_documents()]
    assert len(docs) == 5  # hard cap honoured
