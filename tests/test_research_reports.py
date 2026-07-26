from stock_analysis.evidence import EvidenceBundle
from stock_analysis.lens_engine import load_lens_definitions
from stock_analysis.presentation import investor_facing_violations
from stock_analysis.report_contracts import load_report_contract
from stock_analysis.research_reports import (
    LENS_REPORT_OUTLINES,
    compose_general_report,
    compose_lens_report,
    compose_market_report,
    compose_portfolio_report,
)


def _company_pack():
    return {
        "symbol": "600519",
        "name": "贵州茅台",
        "trade_date": "20260724",
        "modules": {
            "C2": {
                "evidence": [
                    {
                        "metric": "roe_weighted",
                        "value": 31.5,
                        "period": "2025FY",
                        "validation_status": "accepted",
                    }
                ]
            },
            "C3": {
                "evidence": [
                    {
                        "metric": "parent_net_profit_yoy_pct",
                        "value": 12.3,
                        "period": "2025FY",
                        "validation_status": "accepted",
                    },
                    {
                        "metric": "core_product_revenue",
                        "value": 1450.0,
                        "period": "2025FY",
                        "validation_status": "accepted",
                    },
                ]
            },
            "C6": {
                "evidence": [
                    {
                        "metric": "market_quote",
                        "value": 1500.0,
                        "period": "20260724",
                        "currency": "CNY",
                        "validation_status": "accepted",
                    },
                    {
                        "metric": "total_market_cap",
                        "value": 1_880_000_000_000,
                        "period": "20260724",
                        "currency": "CNY",
                        "validation_status": "accepted",
                    },
                    {
                        "metric": "execution_cost_model_status",
                        "value": "insufficient_inputs",
                        "period": "20260724",
                        "validation_status": "conditional",
                    },
                ]
            },
        },
    }


def test_general_company_reports_follow_each_depth_contract():
    pack = _company_pack()

    reports = {
        depth: compose_general_report(pack, scene="company", depth=depth)
        for depth in ("quick", "standard", "deep")
    }

    for depth, report in reports.items():
        assert not load_report_contract("company", depth).validate(report)
        assert not investor_facing_violations(report)
        assert "core_product_revenue" not in report
        assert "insufficient_inputs" not in report
        assert "核心产品收入" in report
    assert reports["quick"] != reports["standard"] != reports["deep"]
    assert "三情景分析" in reports["deep"]
    assert "反方审查" in reports["deep"]


def test_all_fifteen_lenses_keep_distinct_framework_contracts():
    definitions = load_lens_definitions()

    assert set(definitions) == set(LENS_REPORT_OUTLINES)
    assert len(definitions) == 15
    assert len({outline[0] for outline in LENS_REPORT_OUTLINES.values()}) == 15
    for lens_id, outline in LENS_REPORT_OUTLINES.items():
        report = compose_lens_report(
            _company_pack(),
            lens_mode="single",
            lenses=[lens_id],
        )
        assert outline[0] in report
        assert definitions[lens_id]["valuation_preference"] in report
        assert "风险与证伪" in report
        assert "框架结论与失效条件" in report
        assert not investor_facing_violations(report)


def test_adversarial_report_is_synthesis_not_chat_transcript():
    report = compose_lens_report(
        _company_pack(),
        lens_mode="adversarial",
        lenses=["buffett", "soros"],
    )

    for heading in (
        "争议焦点",
        "双方共同认可的事实",
        "真正存在冲突的假设",
        "决定胜负的未来信号",
        "综合投资含义",
    ):
        assert heading in report
    assert "第一轮辩论" not in report
    assert "debate_round" not in report


def test_adversarial_report_translates_lens_metrics_into_investor_language():
    opinions = {
        "buffett": {
            "required_modules": ["C3"],
            "publishable_claims": [
                {
                    "claim": "core_product_revenue=145000000000。",
                    "applicable_period": "2025FY",
                    "scope": "C3",
                    "direction": "neutral",
                }
            ],
            "metric_analyses": [
                {
                    "module": "C3",
                    "metric": "core_product_revenue",
                    "value": 145000000000,
                    "interpretation": "core_product_revenue=145000000000；检验长期现金创造（C3）。",
                }
            ],
        },
        "soros": {
            "required_modules": ["C6"],
            "publishable_claims": [
                {
                    "claim": "market_quote=1500。",
                    "applicable_period": "20260724",
                    "scope": "C6",
                    "direction": "neutral",
                }
            ],
            "metric_analyses": [
                {
                    "module": "C6",
                    "metric": "market_quote",
                    "value": 1500,
                    "interpretation": "market_quote=1500；检验预期与价格反馈（C6）。",
                }
            ],
        },
    }

    report = compose_lens_report(
        _company_pack(),
        lens_mode="adversarial",
        lenses=["buffett", "soros"],
        opinions=opinions,
    )

    assert "核心产品收入（2025FY）为 1,450.00 亿元" in report
    assert "最新有效价格（20260724）为 1,500.00 元" in report
    assert "core_product_revenue" not in report
    assert "market_quote" not in report
    assert not investor_facing_violations(report)


def test_market_and_portfolio_reports_follow_depth_contracts():
    evidence = EvidenceBundle(
        trade_date="20260724",
        modules={
            "M1": {
                "available": True,
                "a_indices": [
                    {
                        "name": "上证指数",
                        "change_pct": 0.8,
                        "turnover": 850_000_000_000,
                    }
                ],
                "hk_indices": [],
                "us_indices": [],
                "breadth": {"available": True, "up": 3200, "down": 1800, "ratio": 1.78},
            },
            "M2": {
                "available": True,
                "industry_top20": [{"name": "半导体", "change_pct": 2.6}],
            },
            "M3": {"available": True, "summary": "短线情绪回暖。"},
            "M4": {"available": True, "summary": "高位方向仍有分歧。"},
            "M5": {"available": True, "summary": "成长风格占优。"},
            "M6": {"available": True, "summary": "防御板块相对稳定。"},
        },
    )
    market = compose_market_report(evidence, trade_date="20260724", depth="deep")
    portfolio = compose_portfolio_report(
        {
            "total_value_cny": 100_000,
            "top3_ratio": 0.72,
            "details": [
                {"symbol": "600519", "name": "贵州茅台", "market_value_cny": 72_000}
            ],
        },
        depth="standard",
    )

    assert not load_report_contract("market", "deep").validate(market)
    assert not load_report_contract("portfolio", "standard").validate(portfolio)
    assert "跨资产传导" in market
    assert "再平衡建议" in portfolio
    assert not investor_facing_violations(market)
    assert not investor_facing_violations(portfolio)


def test_fund_report_does_not_label_five_disclosed_holdings_as_top_ten():
    pack = {
        "symbol": "110011",
        "name": "易方达中小盘",
        "trade_date": "20260724",
        "modules": {
            "F1": {"evidence": []},
            "F2": {
                "evidence": [
                    {
                        "metric": "top10_weight_pct",
                        "value": 33.37,
                        "period": "20260724",
                        "validation_status": "accepted",
                    },
                    {
                        "metric": "disclosed_holding_count",
                        "value": 5,
                        "period": "20260724",
                        "validation_status": "accepted",
                    },
                ]
            },
            "F3": {"evidence": []},
            "F4": {"evidence": []},
            "F5": {"evidence": []},
            "F6": {"evidence": []},
            "F7": {"evidence": []},
            "F8": {"evidence": []},
        },
    }

    report = compose_general_report(pack, scene="fund", depth="standard")

    assert "当前已披露 5 只持仓合计权重" in report
    assert "- 前十大持仓权重" not in report
    assert "该数值不是完整前十大持仓权重" in report


def test_earnings_and_price_move_sections_are_substantively_distinct():
    pack = _company_pack()

    earnings = compose_general_report(pack, scene="earnings", depth="deep")
    move_quick = compose_general_report(pack, scene="price_move", depth="quick")
    move_deep = compose_general_report(pack, scene="price_move", depth="deep")

    assert not load_report_contract("earnings", "deep").validate(earnings)
    assert not load_report_contract("price_move", "quick").validate(move_quick)
    assert not load_report_contract("price_move", "deep").validate(move_deep)
    assert "当前没有一手披露支持单一公司事件解释" in move_quick
    assert "价格和成交只说明异动强度" in move_deep
    assert "会计质量以利润、经营现金流" in earnings
