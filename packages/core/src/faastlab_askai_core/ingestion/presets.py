"""System preset Sources — the regulator connectors shipped ready to toggle on.

Pure data (no DB/IO) so it unit-tests and seeds easily. Each preset is a
regulator data Source with real, verified URLs (Crown Copyright / Open
Government Licence v3 — redistribution + use with attribution; design §10).
Enabling a preset (API) clones it into a tenant Source + Indexer that runs the
existing crawler/pipeline.

URLs are curated from corpus/uk_finreg/handbook_sources.yaml (verified HTTP 200,
correct body type, 2026-05-16). They're representative, not exhaustive — extend
the lists or add presets without code changes to the model.
"""

from __future__ import annotations

from typing import Any

_OGL = "ogl-v3"  # Open Government Licence v3.0 / Crown Copyright
_GOVUK_ATTR = "Contains public sector information licensed under the Open Government Licence v3.0."

# FCA Handbook sourcebooks — canonical PDFs at api-handbook.fca.org.uk.
_FCA_SOURCEBOOKS = [
    "PRIN", "SYSC", "COND", "APER", "COCON", "FIT", "TC", "GEN", "FEES",
    "GENPRU", "MIPRU", "COBS", "ICOBS", "MCOB", "BCOBS", "CONC", "CASS",
    "MAR", "SUP", "DEPP", "DISP", "COMP", "COLL", "FUND", "DTR", "ESG",
    "PERG", "FCG", "ENFG", "CTPS", "UKLR", "CREDS", "REC",
]


def _fca_urls() -> list[str]:
    base = "https://api-handbook.fca.org.uk/files/sourcebook/"
    urls = [f"{base}{sb}.pdf" for sb in _FCA_SOURCEBOOKS]
    # A couple of finalised-guidance / policy statements too.
    urls += [
        "https://www.fca.org.uk/publication/finalised-guidance/fg22-5.pdf",
        "https://www.fca.org.uk/publication/policy/ps22-10.pdf",
    ]
    return urls


# ---- Preset catalogue -------------------------------------------------------


def regulator_presets() -> list[dict[str, Any]]:
    """The shipped regulator presets, OFF by default. Each entry is a Source
    definition (+ a stable `key` for enable/lookup). `config` is the connector
    config consumed by the crawler when the preset's indexer runs."""
    return [
        {
            "key": "fca-handbook",
            "name": "FCA — Handbook & Guidance",
            "category": "fca",
            "kind": "web",
            "license": _OGL,
            "attribution": _GOVUK_ATTR,
            "description": (
                "FCA Handbook sourcebooks (PRIN, COBS, SYSC, CONC, …) + key "
                "finalised guidance."
            ),
            "config": {"mode": "page", "start_urls": _fca_urls(), "max_pages": 60},
        },
        {
            "key": "pra-rulebook",
            "name": "PRA — Rulebook & Instruments",
            "category": "pra",
            "kind": "web",
            "license": _OGL,
            "attribution": _GOVUK_ATTR,
            "description": "PRA Rulebook online + published rulebook instruments.",
            "config": {
                "mode": "crawl",
                "start_urls": ["https://www.prarulebook.co.uk/"],
                "url_prefix": "https://www.prarulebook.co.uk/",
                "max_pages": 80,
                "max_depth": 2,
            },
        },
        {
            "key": "boe-publications",
            "name": "Bank of England — FSR & MPR",
            "category": "boe",
            "kind": "web",
            "license": _OGL,
            "attribution": _GOVUK_ATTR,
            "description": "Bank of England Financial Stability Reports + Monetary Policy Reports.",
            "config": {
                "mode": "page",
                "start_urls": [
                    "https://www.bankofengland.co.uk/-/media/boe/files/financial-stability-report/2025/financial-stability-report-december-2025.pdf",
                    "https://www.bankofengland.co.uk/-/media/boe/files/financial-stability-report/2025/financial-stability-report-july-2025.pdf",
                    "https://www.bankofengland.co.uk/-/media/boe/files/monetary-policy-report/2026/april/monetary-policy-report-april-2026.pdf",
                ],
                "max_pages": 20,
            },
        },
        {
            "key": "hmrc-manuals",
            "name": "HMRC — Internal Manuals (rule pages)",
            "category": "hmrc",
            "kind": "web",
            "license": _OGL,
            "attribution": _GOVUK_ATTR,
            "description": (
                "Crawls the child rule-pages of HMRC manuals (Cryptoassets, "
                "Economic Crime Supervision, SAO) — not just the contents page."
            ),
            "config": {
                "mode": "crawl",
                "start_urls": [
                    "https://www.gov.uk/hmrc-internal-manuals/cryptoassets-manual",
                    "https://www.gov.uk/hmrc-internal-manuals/economic-crime-supervision-handbook",
                    "https://www.gov.uk/hmrc-internal-manuals/senior-accounting-officers-guidance",
                ],
                "url_prefix": "https://www.gov.uk/hmrc-internal-manuals/",
                "max_pages": 400,
                "max_depth": 3,
            },
        },
        {
            "key": "ico-guidance",
            "name": "ICO — UK GDPR Guidance",
            "category": "ico",
            "kind": "web",
            "license": _OGL,
            "attribution": _GOVUK_ATTR,
            "description": "ICO UK GDPR guidance hubs + data-sharing code of practice.",
            "config": {
                "mode": "crawl",
                "start_urls": [
                    "https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/",
                ],
                "url_prefix": "https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/",
                "max_pages": 120,
                "max_depth": 2,
            },
        },
        {
            "key": "tpr-codes",
            "name": "TPR — General Code of Practice",
            "category": "tpr",
            "kind": "web",
            "license": _OGL,
            "attribution": _GOVUK_ATTR,
            "description": "The Pensions Regulator General Code of Practice.",
            "config": {
                "mode": "page",
                "start_urls": [
                    "https://www.thepensionsregulator.gov.uk/media/3rhduw51/general-code-of-practice.pdf",
                ],
                "max_pages": 10,
            },
        },
    ]


def find_preset(key: str) -> dict[str, Any] | None:
    for p in regulator_presets():
        if p["key"] == key:
            return p
    return None
