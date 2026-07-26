import requests

from stock_analysis.company_evidence import (
    _lens_evidence_requests,
    enrich_company_evidence_from_web,
)
from stock_analysis.external_evidence.models import SearchResult, WebDocument
from stock_analysis.external_evidence.plane import ExternalEvidencePlane
from stock_analysis.external_evidence.planner import budget_for, plan_queries
from stock_analysis.external_evidence.providers import FallbackSearch


class Search:
    def __init__(self, *, fail=False):
        self.fail = fail

    def search(self, query, *, domains=(), limit=10):
        if self.fail:
            raise OSError("offline")
        return [
            SearchResult(
                title="年度报告",
                url="https://www.sse.com.cn/disclosure/report.pdf",
                provider="test",
            )
        ]


class Reader:
    def read(self, url):
        return WebDocument(
            url=url,
            title="年度报告",
            text="公司披露的年度经营与股本信息。",
            publisher="sse.com.cn",
            published_at="20260401",
            retrieved_at="2026-07-26T00:00:00+00:00",
            content_hash="sha256:abc",
            location="PDF 第 12 页",
        )


class PrimaryFactReader(Reader):
    def read(self, url):
        document = super().read(url)
        return WebDocument(
            **{
                **document.__dict__,
                "text": "公司总股本为 1,256,197,800 股，营业收入为 1,741.44 亿元。",
            }
        )


def _queries(mode="standard"):
    return plan_queries(
        [
            {
                "module": "C5",
                "topics": ["治理", "资本配置"],
                "query": "贵州茅台 600519 年度报告",
                "preferred_domains": ["sse.com.cn"],
            }
        ],
        trade_date="20260726",
        mode=mode,
    )


def test_builtin_plane_returns_auditable_primary_evidence_without_extra_install():
    evidence, events = ExternalEvidencePlane(Search(), Reader()).collect(
        _queries(),
        mode="standard",
    )

    assert evidence[0].verification == "primary_source"
    assert evidence[0].source_tier == 1
    assert evidence[0].published_at == "20260401"
    assert evidence[0].content_hash == "sha256:abc"
    assert events[-1]["status"] == "ok"


def test_network_failure_is_internal_and_does_not_raise():
    evidence, events = ExternalEvidencePlane(Search(fail=True), Reader()).collect(
        _queries(),
        mode="standard",
    )

    assert evidence == []
    assert events[0]["status"] == "unavailable"
    assert events[0]["reason"] == "OSError"
    assert "安装" not in str(events)


def test_mode_budgets_follow_product_contract():
    assert budget_for("quick").max_queries == 3
    assert budget_for("standard").max_queries == 8
    assert budget_for("deep").max_queries == 20


def test_explicit_lens_builds_framework_specific_queries_without_install_dependency():
    requests = _lens_evidence_requests(
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "market": "a",
        },
        ("buffett", "soros"),
    )

    assert [item["module"] for item in requests] == ["C1", "C8"]
    assert "这门生意十年后" in requests[0]["query"]
    assert "市场预期与现实" in requests[1]["query"]
    assert all("agent-reach" not in str(item).lower() for item in requests)


def test_public_documents_do_not_inflate_structured_evidence_coverage():
    pack = {
        "symbol": "600519",
        "name": "贵州茅台",
        "market": "a",
        "trade_date": "20260726",
        "modules": {
            f"C{index}": {"available": False, "evidence": [], "gaps": ["gap"]}
            for index in range(1, 9)
        },
        "_meta": {
            "coverage": 0.0,
            "available_modules": [],
            "missing_modules": [f"C{index}" for index in range(1, 9)],
            "source_events": [],
            "primary_evidence_requests": [
                {
                    "module": "C5",
                    "topics": ["治理"],
                    "query": "贵州茅台 600519 年度报告",
                    "preferred_domains": ["sse.com.cn"],
                }
            ],
        },
    }

    result = enrich_company_evidence_from_web(
        pack,
        plane=ExternalEvidencePlane(Search(), Reader()),
    )

    assert result["_meta"]["coverage"] == 0.0
    assert result["modules"]["C5"]["available"] is False
    assert result["modules"]["C5"]["evidence"] == []
    assert result["_meta"]["external_documents"][0]["module"] == "C5"
    assert (
        result["_meta"]["external_documents"][0]["publication_policy"]
        == "discovery_only_until_fact_extracted"
    )


def test_primary_document_fact_extraction_recomputes_only_supported_coverage():
    evidence, _ = ExternalEvidencePlane(Search(), PrimaryFactReader()).collect(
        _queries(),
        mode="standard",
    )

    facts = evidence[0].extracted_facts
    assert {item["metric"] for item in facts} == {"total_shares", "revenue"}
    assert next(item["value"] for item in facts if item["metric"] == "total_shares") == 1_256_197_800


def test_search_fallback_uses_independent_secondary_backend():
    class TimeoutSearch:
        def search(self, query, *, domains=(), limit=10):
            raise requests.Timeout("primary timeout")

    rows = FallbackSearch(TimeoutSearch(), Search()).search("贵州茅台", limit=2)

    assert rows
