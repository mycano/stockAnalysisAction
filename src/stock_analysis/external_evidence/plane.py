"""Bounded acquisition with silent failure isolation."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import EvidenceQuery, ExternalEvidence
from .planner import budget_for
from .providers import (
    BingRssSearch,
    DirectWebReader,
    DuckDuckGoSearch,
    FallbackSearch,
    FallbackWebReader,
    SearchProvider,
    WebReader,
)
from .validator import source_tier, validate_document


def _scaled_number(raw: str, unit: str | None) -> float:
    value = float(raw.replace(",", ""))
    return value * {"亿": 100_000_000, "万": 10_000}.get(unit or "", 1)


def _extract_primary_facts(
    text: str,
    *,
    module: str,
    verification: str,
) -> tuple[dict[str, object], ...]:
    """Extract only narrowly defined numeric facts from primary-source prose."""

    if verification != "primary_source":
        return ()
    patterns = (
        ("total_shares", r"总股本(?:为|约为|：|:)?\s*([\d,.]+)\s*(亿|万)?股", "shares"),
        ("revenue", r"营业收入(?:为|约为|：|:)?\s*([\d,.]+)\s*(亿|万)?元", "CNY"),
        (
            "parent_net_profit",
            r"归属于(?:上市公司|母公司)?股东的?净利润(?:为|约为|：|:)?\s*([\d,.]+)\s*(亿|万)?元",
            "CNY",
        ),
        (
            "management_fee_pct",
            r"管理费率?(?:为|按|：|:)?\s*([\d.]+)\s*(%)",
            "percent",
        ),
        (
            "latest_size_yi",
            r"(?:基金规模|基金资产净值)(?:为|约为|：|:)?\s*([\d,.]+)\s*(亿)元",
            "yi_cny",
        ),
    )
    facts: list[dict[str, object]] = []
    for metric, pattern, unit in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        raw, scale = match.group(1), match.group(2)
        if unit == "percent":
            value = float(raw)
        elif unit == "yi_cny":
            value = float(raw.replace(",", ""))
        else:
            value = _scaled_number(raw, scale)
        facts.append(
            {
                "module": module,
                "metric": metric,
                "value": value,
                "unit": unit,
                "claim_supported": match.group(0),
                "validation_status": "accepted",
            }
        )
    return tuple(facts)


@dataclass
class ExternalEvidencePlane:
    search_provider: SearchProvider
    web_reader: WebReader

    def collect(
        self,
        queries: tuple[EvidenceQuery, ...],
        *,
        mode: str,
    ) -> tuple[list[ExternalEvidence], list[dict[str, str]]]:
        budget = budget_for(mode)
        evidence: list[ExternalEvidence] = []
        events: list[dict[str, str]] = []
        documents_seen: set[str] = set()
        for query in queries[: budget.max_queries]:
            try:
                results = self.search_provider.search(
                    query.query,
                    domains=query.preferred_domains,
                    limit=min(5, budget.max_documents - len(documents_seen)),
                )
            except Exception as exc:
                events.append(
                    {
                        "source": "builtin_web_search",
                        "status": "unavailable",
                        "reason": type(exc).__name__,
                    }
                )
                continue
            for result in results:
                if result.url in documents_seen or len(documents_seen) >= budget.max_documents:
                    continue
                documents_seen.add(result.url)
                try:
                    document = self.web_reader.read(result.url)
                    valid, verification = validate_document(
                        document,
                        trade_date=query.trade_date,
                    )
                except Exception as exc:
                    events.append(
                        {
                            "source": "builtin_web_reader",
                            "status": "unavailable",
                            "reason": type(exc).__name__,
                        }
                    )
                    continue
                if not valid:
                    continue
                evidence.append(
                    ExternalEvidence(
                        module=query.module,
                        evidence_type="public_document",
                        title=document.title or result.title,
                        summary=(document.text or result.snippet)[:1200],
                        publisher=document.publisher,
                        url=document.url,
                        published_at=document.published_at,
                        effective_at=document.published_at,
                        retrieved_at=document.retrieved_at,
                        source_tier=source_tier(document.url),
                        verification=verification,
                        content_hash=document.content_hash,
                        location=document.location,
                        extracted_facts=_extract_primary_facts(
                            document.text,
                            module=query.module,
                            verification=verification,
                        ),
                        query=query.query,
                    )
                )
                if verification == "primary_source":
                    break
        if evidence:
            events.append(
                {"source": "builtin_external_evidence", "status": "ok", "reason": ""}
            )
        elif not events:
            events.append(
                {
                    "source": "builtin_external_evidence",
                    "status": "unavailable",
                    "reason": "no_valid_public_document",
                }
            )
        return evidence, events


def build_default_plane() -> ExternalEvidencePlane:
    return ExternalEvidencePlane(
        search_provider=FallbackSearch(DuckDuckGoSearch(), BingRssSearch()),
        web_reader=FallbackWebReader(DirectWebReader()),
    )
