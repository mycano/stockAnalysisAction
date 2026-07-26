import json

import pytest

from stock_analysis import app, company_evidence
from stock_analysis.models import QuoteData
from stock_analysis.thesis import compare_theses, create_thesis, review_thesis, thesis_version_path
from stock_analysis.workflows import render_earnings_review, render_price_move, render_stock_review


def _financials():
    return {
        "periods": [
            {
                "report_date": "2026-03-31",
                "period_label": "2026Q1",
                "revenue": 78_000_000_000,
                "parent_netprofit": 25_000_000_000,
                "roe_weighted": 10.57,
                "gross_margin": 91.2,
                "debt_asset_ratio": 12.12,
                "operating_cash_flow": 26_910_000_000,
                "free_cash_flow_lite": 26_305_000_000,
                "net_cash_finance": -12_000_000_000,
            },
            {
                "report_date": "2025-12-31",
                "period_label": "2025FY",
                "basic_eps": 65.66,
                "bps": 195.36,
            },
            {
                "report_date": "2025-03-31",
                "period_label": "2025Q1",
                "revenue": 70_000_000_000,
                "parent_net_profit": 24_000_000_000,
            },
        ],
        "forecasts": {"available": True, "rows": [{"notice_date": "2026-04-10", "report_date": "2026-03-31", "title": "一季度业绩预告", "type": "预增"}]},
        "earnings_flash": {"available": True, "rows": [{"notice_date": "2026-04-20", "report_date": "2026-03-31", "title": "一季度业绩快报", "type": "快报"}]},
    }


def _company_pack(monkeypatch):
    def primary_item(module, metric, value):
        return {
            "metric": metric, "value": value, "period": "2025FY", "published_at": "2026-04-17",
            "source": "贵州茅台2025年年度报告", "source_type": "issuer_primary_disclosure",
            "confidence": "primary", "url": "https://example.com/annual.pdf", "page": 10,
            "extraction_method": "official_pdf_regex",
        }

    primary = {f"C{index}": [] for index in range(1, 9)}
    for module, metric, value in (
        ("C1", "direct_sales_revenue", 84_543_031_854.63),
        ("C4", "core_product_gross_margin_pct", 93.53),
        ("C5", "annual_dividend_total", 35_032_568_759.73),
        ("C5", "shareholder_payout_ratio_pct", 42.56),
        ("C7", "series_revenue_yoy_pct", -9.76),
        ("C8", "moutai_base_capacity_added_tons", 1800),
    ):
        primary[module].append(primary_item(module, metric, value))
    monkeypatch.setattr(company_evidence, "load_issuer_primary_facts", lambda *_: primary)
    monkeypatch.setattr(
        company_evidence,
        "fetch_single_quote",
        lambda *_: QuoteData(
            symbol="600519", name="贵州茅台", market="a", price=1500.0, pe=21.5, pb=7.4,
            total_market_cap=1_880_000_000_000, currency="CNY", trade_date="20260710", source="tencent"
        ),
    )
    monkeypatch.setattr(company_evidence, "fetch_a_share_financial_snapshot", lambda *_: _financials())
    monkeypatch.setattr(
        company_evidence,
        "fetch_a_share_price_volume",
        lambda *_: {"source": "tencent-kline", "metrics": {"returns_20d": 0.12, "atr_14": 30.2}},
    )
    monkeypatch.setattr(
        company_evidence,
        "fetch_futu_public_pulse",
        lambda *_: {"event_title": "公司回购公告", "evidence_url": "https://example.com", "news_tone": "偏正面", "news_count": 2},
    )
    monkeypatch.setattr(
        company_evidence,
        "fetch_company_disclosures",
        lambda *_: {
            "available": True,
            "rows": [
                {"title": "年度分红实施公告", "publish_date": "20260701", "url": "https://example.com/dividend", "category": "capital_allocation", "source": "futu_announcement_search", "source_type": "public_announcement_index", "confidence": "secondary"},
                {"title": "董事会换届公告", "publish_date": "20260620", "url": "https://example.com/board", "category": "governance", "source": "futu_announcement_search", "source_type": "public_announcement_index", "confidence": "secondary"},
            ],
            "_source": "Futu 免登录公告搜索",
        },
    )
    return company_evidence.build_company_evidence("600519", "20260710")


def test_company_evidence_has_c1_to_c8_and_explicit_gaps(monkeypatch):
    pack = _company_pack(monkeypatch)

    assert pack["schema_version"] == "1.2"
    assert list(pack["modules"]) == ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"]
    assert pack["modules"]["C2"]["available"] is True
    assert pack["modules"]["C1"]["available"] is True
    assert pack["modules"]["C4"]["available"] is True
    assert pack["modules"]["C5"]["available"] is True
    assert pack["_meta"]["coverage"] == 100.0
    assert pack["_meta"]["identity_validation"]["status"] == "matched"
    assert pack["_meta"]["publication_cutoff_audit"]["violations"] == []
    primary_metrics = {
        item["metric"]
        for code in ("C1", "C4", "C5", "C7", "C8")
        for item in pack["modules"][code]["evidence"]
        if item.get("source_type") == "issuer_primary_disclosure"
    }
    assert {
        "direct_sales_revenue", "core_product_gross_margin_pct", "annual_dividend_total",
        "shareholder_payout_ratio_pct", "series_revenue_yoy_pct",
    } <= primary_metrics
    assert all(
        item.get("url") and item.get("page")
        for code in ("C1", "C4", "C5", "C7", "C8")
        for item in pack["modules"][code]["evidence"]
        if item.get("source_type") == "issuer_primary_disclosure"
    )
    assert {item["metric"] for item in pack["modules"]["C6"]["evidence"]} >= {"market_quote", "pe_ttm", "pb"}
    assert {item["metric"] for item in pack["modules"]["C6"]["evidence"]} >= {
        "pe_static_proxy", "pb_reported_proxy", "scenario_price_15x_pe", "scenario_price_18x_pe", "scenario_price_22x_pe",
    }
    assert {item["metric"] for item in pack["modules"]["C6"]["evidence"]} >= {
        "implied_net_profit_20x", "implied_net_profit_25x", "implied_net_profit_30x", "implied_net_profit_35x",
    }
    assert pack["expectation_model"]["status"] == "market_implied_only"
    assert pack["financial_history"][0]["period_label"] == "2026Q1"
    assert all(item["evidence_id"].startswith("C") for section in pack["modules"].values() for item in section["evidence"])
    assert pack["_meta"]["evidence_snapshot_id"].startswith("sha256:")
    assert {event["source"] for event in pack["_meta"]["source_events"]} >= {
        "tencent",
        "eastmoney_datacenter",
        "futu_public",
        "Futu 免登录公告搜索",
        "issuer_primary_disclosure",
        "execution_cost_model",
    }


def test_company_workflow_reports_do_not_turn_gaps_into_scores(monkeypatch):
    pack = _company_pack(monkeypatch)

    stock = render_stock_review(pack)
    earnings = render_earnings_review(pack)
    price_move = render_price_move(pack)

    assert "## 一句话结论" in stock
    assert "Evidence Coverage" not in stock
    assert "C4 护城河证据" not in stock
    assert "## 业绩摘要" in earnings
    assert "roe_weighted" not in earnings
    assert "## 已确认原因" in price_move
    assert "相关性不自动升级为因果" in price_move


def test_thesis_create_and_review_persist_only_structured_evidence(monkeypatch, tmp_path):
    pack = _company_pack(monkeypatch)
    monkeypatch.setenv("STOCK_ANALYSIS_THESIS_DIR", str(tmp_path))

    thesis, path = create_thesis(pack)
    reviewed, reviewed_path, changes = review_thesis(pack)

    assert path == reviewed_path
    assert path.exists()
    assert thesis["status"] == "under_review"
    assert reviewed is not None
    assert thesis["version"] == 1
    assert reviewed["version"] == 2
    assert "未发现可由当前结构化证据自动判定的变化" in changes
    assert json.loads(path.read_text(encoding="utf-8"))["symbol"] == "600519"
    assert thesis_version_path("600519", 1).exists()
    assert thesis_version_path("600519", 2).exists()
    comparison = compare_theses("600519", 1, 2)
    assert comparison["from"]["version"] == 1
    assert comparison["to"]["version"] == 2

    with pytest.raises(ValueError, match="论文已存在"):
        create_thesis(pack)


def test_thesis_review_migrates_legacy_latest_without_losing_v1(monkeypatch, tmp_path):
    pack = _company_pack(monkeypatch)
    monkeypatch.setenv("STOCK_ANALYSIS_THESIS_DIR", str(tmp_path))
    legacy = {
        "schema_version": "1.0",
        "symbol": "600519",
        "name": "贵州茅台",
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
        "status": "under_review",
        "thesis": {"core_assumptions": ["legacy"]},
        "evidence_snapshot": {
            "trade_date": "20250101",
            "coverage": 50,
            "available_modules": [],
            "missing_modules": ["C1"],
        },
    }
    (tmp_path / "600519.json").write_text(
        json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
    )

    reviewed, _, _ = review_thesis(pack)

    assert reviewed is not None and reviewed["version"] == 2
    archived = json.loads(thesis_version_path("600519", 1).read_text(encoding="utf-8"))
    assert archived["thesis"]["core_assumptions"] == ["legacy"]


def test_cli_stock_review_emits_company_evidence(monkeypatch, tmp_path, capsys):
    pack = {"symbol": "600519", "name": "贵州茅台", "trade_date": "20260710", "_meta": {"coverage": 0, "available_modules": [], "missing_modules": list(company_evidence.COMPANY_MODULES), "source_events": []}, "financial_facts": [], "quote": {}, "modules": {key: {"available": False, "evidence": [], "gaps": ["缺口"]} for key in company_evidence.COMPANY_MODULES}}
    monkeypatch.setattr(app, "build_company_evidence", lambda *_: pack)
    monkeypatch.chdir(tmp_path)

    assert app.run(["--market", "stock-review", "--symbol", "600519", "--date", "20260710", "--emit-evidence"]) == 0

    assert "个股研究报告" in capsys.readouterr().out
    assert (tmp_path / "company_evidence_600519_20260710.json").exists()


def test_cli_passes_expectations_file_to_company_research(monkeypatch, tmp_path, capsys):
    assumptions = {"valuation_year": 2027, "multiples": [25]}
    assumptions_path = tmp_path / "expectations.json"
    assumptions_path.write_text(json.dumps(assumptions), encoding="utf-8")
    captured = {}

    def build(symbol, trade_date, expectations=None):
        captured["expectations"] = expectations
        return {
            "symbol": symbol,
            "name": symbol,
            "trade_date": trade_date,
            "_meta": {"coverage": 0, "available_modules": [], "missing_modules": list(company_evidence.COMPANY_MODULES), "source_events": []},
            "financial_facts": [],
            "quote": {},
            "modules": {key: {"available": False, "evidence": [], "gaps": ["缺口"]} for key in company_evidence.COMPANY_MODULES},
        }

    monkeypatch.setattr(app, "build_company_evidence", build)

    assert app.run([
        "--market", "stock-review", "--symbol", "600519", "--date", "20260710",
        "--expectations-file", str(assumptions_path),
    ]) == 0

    assert captured["expectations"] == assumptions
    assert "个股研究报告" in capsys.readouterr().out
