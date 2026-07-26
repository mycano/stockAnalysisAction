"""Zero-key search, web reading, and PDF fetching providers."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from io import BytesIO
from typing import Protocol
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree

import requests
from pypdf import PdfReader

from .models import SearchResult, WebDocument


class SearchProvider(Protocol):
    def search(
        self,
        query: str,
        *,
        domains: tuple[str, ...] = (),
        limit: int = 10,
    ) -> list[SearchResult]: ...


class WebReader(Protocol):
    def read(self, url: str) -> WebDocument: ...


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[SearchResult] = []
        self._href = ""
        self._title: list[str] = []
        self._capture_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and "result__a" in str(values.get("class") or ""):
            self._href = str(values.get("href") or "")
            self._title = []
            self._capture_title = True

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._capture_title:
            return
        url = self._href
        parsed = urlparse(url)
        if parsed.netloc.endswith("duckduckgo.com"):
            url = unquote((parse_qs(parsed.query).get("uddg") or [""])[0])
        if url.startswith("https://"):
            self.results.append(
                SearchResult(
                    title=unescape("".join(self._title)).strip(),
                    url=url,
                    provider="builtin_web_search",
                )
            )
        self._capture_title = False


class DuckDuckGoSearch:
    """HTML search used only for bounded evidence gaps."""

    def __init__(self, session: requests.Session | None = None, *, timeout: float = 12):
        self.session = session or requests.Session()
        self.timeout = timeout

    def search(
        self,
        query: str,
        *,
        domains: tuple[str, ...] = (),
        limit: int = 10,
    ) -> list[SearchResult]:
        domain_clause = " OR ".join(f"site:{domain}" for domain in domains)
        effective_query = f"{query} ({domain_clause})" if domain_clause else query
        response = self.session.get(
            "https://html.duckduckgo.com/html/",
            params={"q": effective_query},
            headers={"User-Agent": "stock-analysis/5 public-evidence"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        parser = _DuckDuckGoParser()
        parser.feed(response.text)
        return parser.results[:limit]


class BingRssSearch:
    """Zero-key RSS search used when the primary HTML endpoint is unavailable."""

    def __init__(self, session: requests.Session | None = None, *, timeout: float = 12):
        self.session = session or requests.Session()
        self.timeout = timeout

    def search(
        self,
        query: str,
        *,
        domains: tuple[str, ...] = (),
        limit: int = 10,
    ) -> list[SearchResult]:
        domain_clause = " OR ".join(f"site:{domain}" for domain in domains)
        effective_query = f"{query} ({domain_clause})" if domain_clause else query
        response = self.session.get(
            "https://www.bing.com/search",
            params={"q": effective_query, "format": "rss"},
            headers={"User-Agent": "stock-analysis/5 public-evidence"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        rows = []
        for item in root.findall(".//item"):
            url = (item.findtext("link") or "").strip()
            if not url.startswith("https://"):
                continue
            rows.append(
                SearchResult(
                    title=(item.findtext("title") or "").strip(),
                    url=url,
                    snippet=_plain_text(item.findtext("description") or ""),
                    provider="builtin_web_search_fallback",
                )
            )
        return rows[:limit]


class FallbackSearch:
    """Try independent zero-key search paths without exposing backend failures."""

    def __init__(self, primary: SearchProvider, secondary: SearchProvider):
        self.primary = primary
        self.secondary = secondary

    def search(
        self,
        query: str,
        *,
        domains: tuple[str, ...] = (),
        limit: int = 10,
    ) -> list[SearchResult]:
        try:
            rows = self.primary.search(query, domains=domains, limit=limit)
        except requests.RequestException:
            rows = []
        if rows:
            return rows
        return self.secondary.search(query, domains=domains, limit=limit)


def _plain_text(html: str) -> str:
    value = re.sub(r"(?is)<(script|style|nav|footer).*?>.*?</\1>", " ", html)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _title(html: str, fallback: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    return _plain_text(match.group(1)) if match else fallback


def _published_at(html: str) -> str | None:
    patterns = (
        r'property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
        r'name=["\']date["\'][^>]+content=["\']([^"\']+)',
        r"\b(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})",
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if not match:
            continue
        if len(match.groups()) == 3:
            return f"{int(match.group(1)):04d}{int(match.group(2)):02d}{int(match.group(3)):02d}"
        digits = re.sub(r"\D", "", match.group(1))
        if len(digits) >= 8:
            return digits[:8]
    return None


class DirectWebReader:
    def __init__(self, session: requests.Session | None = None, *, timeout: float = 15):
        self.session = session or requests.Session()
        self.timeout = timeout

    def read(self, url: str) -> WebDocument:
        response = self.session.get(
            url,
            headers={"User-Agent": "stock-analysis/5 public-evidence"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        retrieved_at = datetime.now(timezone.utc).isoformat()
        if "pdf" in content_type.lower() or urlparse(url).path.lower().endswith(".pdf"):
            text = "\n".join(
                page.extract_text() or ""
                for page in PdfReader(BytesIO(response.content)).pages
            )
            title = urlparse(url).path.rsplit("/", 1)[-1]
            location = "PDF"
            published_at = None
        else:
            html = response.text
            text = _plain_text(html)
            title = _title(html, urlparse(url).netloc)
            location = "webpage"
            published_at = _published_at(html)
        return WebDocument(
            url=url,
            title=title,
            text=text,
            publisher=urlparse(url).netloc.lower(),
            published_at=published_at,
            retrieved_at=retrieved_at,
            content_hash=f"sha256:{hashlib.sha256(response.content).hexdigest()}",
            location=location,
        )


class FallbackWebReader:
    """Try the original URL, then the zero-key Jina reading proxy."""

    def __init__(
        self,
        primary: WebReader,
        session: requests.Session | None = None,
        *,
        timeout: float = 20,
    ):
        self.primary = primary
        self.session = session or requests.Session()
        self.timeout = timeout

    def read(self, url: str) -> WebDocument:
        try:
            return self.primary.read(url)
        except requests.RequestException:
            response = self.session.get(
                f"https://r.jina.ai/{url}",
                headers={"User-Agent": "stock-analysis/5 public-evidence"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return WebDocument(
                url=url,
                title=urlparse(url).netloc,
                text=response.text.strip(),
                publisher=urlparse(url).netloc.lower(),
                published_at=None,
                retrieved_at=datetime.now(timezone.utc).isoformat(),
                content_hash=f"sha256:{hashlib.sha256(response.content).hexdigest()}",
                location="webpage",
            )
