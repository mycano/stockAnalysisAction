"""Authority and publication-cutoff checks for public documents."""

from __future__ import annotations

from urllib.parse import urlparse

from .models import WebDocument

PRIMARY_DOMAINS = {
    "cninfo.com.cn",
    "sse.com.cn",
    "szse.cn",
    "bse.cn",
    "hkexnews.hk",
    "sec.gov",
    "release.tdnet.info",
    "edinet-fsa.go.jp",
    "dart.fss.or.kr",
    "kind.krx.co.kr",
    "pbc.gov.cn",
    "stats.gov.cn",
    "csrc.gov.cn",
}


def source_tier(url: str) -> int:
    host = urlparse(url).netloc.lower().split(":", 1)[0]
    if any(host == domain or host.endswith(f".{domain}") for domain in PRIMARY_DOMAINS):
        return 1
    if host.endswith((".gov", ".gov.cn", ".org")):
        return 2
    return 3


def validate_document(document: WebDocument, *, trade_date: str) -> tuple[bool, str]:
    if not document.url.startswith("https://") or not document.text.strip():
        return False, "unusable"
    if document.published_at and document.published_at > trade_date:
        return False, "lookahead"
    if source_tier(document.url) == 1 and document.published_at:
        return True, "primary_source"
    return True, "public_source_pending_primary_confirmation"
