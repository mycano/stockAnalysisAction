"""Models shared by the built-in external-evidence plane."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AcquisitionBudget:
    max_queries: int
    max_documents: int


@dataclass(frozen=True)
class EvidenceQuery:
    module: str
    research_question: str
    query: str
    preferred_domains: tuple[str, ...]
    trade_date: str
    stop_condition: str = "one_primary_or_two_independent_secondary_sources"


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    provider: str = ""


@dataclass(frozen=True)
class WebDocument:
    url: str
    title: str
    text: str
    publisher: str
    published_at: str | None
    retrieved_at: str
    content_hash: str
    location: str = "webpage"


@dataclass(frozen=True)
class ExternalEvidence:
    module: str
    evidence_type: str
    title: str
    summary: str
    publisher: str
    url: str
    published_at: str | None
    effective_at: str | None
    retrieved_at: str
    source_tier: int
    verification: str
    content_hash: str
    location: str
    query: str = field(repr=False)
    extracted_facts: tuple[dict[str, object], ...] = ()

    def to_internal_dict(self) -> dict[str, object]:
        return {
            "title": self.title,
            "summary": self.summary,
            "publisher": self.publisher,
            "url": self.url,
            "published_at": self.published_at,
            "effective_at": self.effective_at,
            "retrieved_at": self.retrieved_at,
            "source_tier": self.source_tier,
            "verification": self.verification,
            "content_hash": self.content_hash,
            "location": self.location,
            "extracted_facts": [dict(item) for item in self.extracted_facts],
            "source_type": "external_public_document",
            "confidence": "conditional",
            "validation_status": "conditional",
        }
