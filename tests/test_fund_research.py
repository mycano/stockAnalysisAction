import json

from stock_analysis import app
from stock_analysis.fund_research import (
    _official_fund_evidence,
    build_fund_research_workspace,
    freeze_fund_evidence,
    synthesize_fund_committee,
)


def _pack():
    modules = {
        f"F{index}": {
            "available": index != 5,
            "evidence": [
                {
                    "evidence_id": f"F{index}:fixture",
                    "metric": f"metric_{index}",
                    "value": index,
                    "period": "20260717",
                    "validation_status": "accepted",
                    "source_type": "primary_disclosure",
                    "source": f"fixture-filing-F{index}",
                }
            ] if index != 5 else [],
            "gaps": ["缺少成分股估值"] if index == 5 else [],
        }
        for index in range(1, 9)
    }
    return {
        "schema_version": "1.0",
        "asset_type": "fund",
        "symbol": "512480",
        "name": "半导体ETF国联安",
        "trade_date": "20260717",
        "modules": modules,
        "profile": {"returns": {"近1年": 107.79}, "scale": {"latest_size_yi": 199.06}},
        "estimate": {"estimate_nav": 1.0714, "estimate_change_pct": -7.71},
        "price_volume": {"metrics": {
            "returns_5d": -21.84,
            "atr_14_pct": 9.53,
            "max_drawdown_60d_pct": -28.81,
            "annualized_volatility_60d_pct": 65.13,
        }},
        "premium_discount": {"latest": {"premium_discount_pct": -0.18}},
        "holdings": {"asof": "2026-03-31", "holdings": [{"code": "688256", "name": "寒武纪", "weight_pct": 6.64}]},
        "_meta": {
            "coverage": 87.5,
            "available_modules": ["F1", "F2", "F3", "F4", "F6", "F7", "F8"],
            "missing_modules": ["F5"],
            "source_events": [{"source": "fixture", "status": "ok"}],
        },
    }


def test_fund_snapshot_and_committee_share_one_frozen_evidence():
    snapshot = freeze_fund_evidence(_pack())
    committee, opinions = synthesize_fund_committee(snapshot, research_question="半导体景气、估值和回撤风险")

    assert snapshot["snapshot_id"].startswith("sha256:")
    assert len(opinions) == 6
    assert all(item["evidence_snapshot_id"] == snapshot["snapshot_id"] for item in opinions.values())
    assert committee["evidence_snapshot_id"] == snapshot["snapshot_id"]
    assert committee["action"] == "manual_review"


def test_fund_workspace_uses_institutional_skeleton(tmp_path):
    manifest, workspace = build_fund_research_workspace(_pack(), root=tmp_path)

    report = (workspace / manifest["artifacts"]["institutional_report"]["path"]).read_text(encoding="utf-8")
    for heading in (
        "## 结论与组合角色",
        "## 产品与策略",
        "## 收益来源",
        "## 风险特征",
        "## 持仓与暴露",
        "## 管理能力或跟踪质量",
        "## 当前市场适配度",
        "## 申购、持有与退出条件",
    ):
        assert heading in report
    assert "证据不足，维持观察" not in report
    assert "manual_review" not in report
    assert "Evidence Dashboard" not in report
    assert "底层估值模块 F5 尚未结构化" not in report
    assert "冻结 Evidence" not in report
    assert "fund-committee:" not in report
    assert "sha256:" not in report
    assert "审计与待核验事项" not in report
    assert json.loads((workspace / "02-frozen-fund-evidence.json").read_text(encoding="utf-8"))["snapshot_id"]
    for filename in (
        "evidence_manifest.json",
        "claim_ledger.json",
        "coverage_report.json",
        "unpublished_claims.json",
    ):
        assert json.loads((workspace / filename).read_text(encoding="utf-8"))


def test_research_cli_routes_fund_asset_type_without_workspace_path(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(app, "build_fund_evidence", lambda *_: _pack())

    assert app.run([
        "--market", "research", "--symbol", "512480", "--date", "20260717",
        "--asset-type", "fund", "--workspace-dir", str(tmp_path),
    ]) == 0

    captured = capsys.readouterr()
    output = captured.out
    assert "基金研究报告" in output
    assert "Research Workspace:" not in output
    assert "STOCK_ANALYSIS_WORKSPACE=" not in captured.err


def test_selected_fund_experts_consume_only_their_required_modules():
    pack = _pack()
    pack["modules"]["F5"] = {
        "available": True,
        "evidence": [
            {"evidence_id": "F5:pe", "metric": "positive_pe_harmonic_proxy", "value": 173.16, "validation_status": "conditional"},
            {"evidence_id": "F5:index-pe", "metric": "index_pe_calculation_share", "value": 108.15, "validation_status": "accepted"},
        ],
        "gaps": [],
    }
    pack["modules"]["F6"]["evidence"] = [
        {"evidence_id": "F6:drawdown", "metric": "max_drawdown_60d_pct", "value": -28.81, "validation_status": "accepted"},
        {"evidence_id": "F6:volatility", "metric": "annualized_volatility_60d_pct", "value": 65.13, "validation_status": "accepted"},
    ]
    pack["modules"]["F7"]["evidence"] = [
        {"evidence_id": "F7:index-cap", "metric": "index_single_constituent_cap_pct", "value": 15.0, "validation_status": "accepted"},
        {"evidence_id": "F7:fee", "metric": "management_fee_pct", "value": 0.5, "validation_status": "accepted"},
    ]
    pack["_meta"]["available_modules"].append("F5")
    pack["_meta"]["missing_modules"] = []
    snapshot = freeze_fund_evidence(pack)
    committee, opinions = synthesize_fund_committee(snapshot, research_question="估值、景气和交易风险")

    assert len(opinions) == 6
    metric_sets = {
        lens_id: {item["metric"] for item in opinion["metric_analyses"]}
        for lens_id, opinion in opinions.items()
    }
    assert len({frozenset(metrics) for metrics in metric_sets.values()}) > 1
    for lens_id, opinion in opinions.items():
        allowed_modules = set(opinion["required_modules"])
        assert {
            item["module"] for item in opinion["metric_analyses"]
        } <= allowed_modules, lens_id
    assert committee["evidence_consumption_audit"]


def test_official_fund_contract_and_index_methodology_are_structured():
    evidence = _official_fund_evidence("512480", "20260717")
    metrics = {item["metric"] for items in evidence.values() for item in items}

    assert {
        "index_single_constituent_cap_pct", "index_rebalance_months",
        "minimum_index_constituent_nav_pct", "management_fee_pct", "custodian_fee_pct",
    } <= metrics
    assert all(item["source_type"] == "primary_disclosure" for items in evidence.values() for item in items)
    assert all(item["url"] and item["page"] for items in evidence.values() for item in items)


def test_simons_reservation_reconciles_with_index_history_and_execution_cost_evidence(tmp_path):
    pack = _pack()
    pack["modules"]["F5"]["evidence"] = [
        {"evidence_id": "F5:index-pe", "metric": "index_pe_calculation_share", "value": 108.15, "period": "20260717", "validation_status": "accepted", "source_type": "primary_disclosure", "source": "fixture-index-filing"},
    ]
    pack["modules"]["F6"]["evidence"] = [
        {"evidence_id": "F6:index-sample", "metric": "index_history_sample_size", "value": 90, "period": "20260717", "validation_status": "accepted", "source_type": "primary_disclosure", "source": "fixture-index-history"},
        {"evidence_id": "F6:index-vol", "metric": "index_annualized_volatility_60d_pct", "value": 60.0, "period": "20260717", "validation_status": "accepted", "source_type": "primary_disclosure", "source": "fixture-index-history"},
    ]
    pack["modules"]["F7"]["evidence"] = [
        {"evidence_id": "F7:cost-status", "metric": "execution_cost_model_status", "value": "scenario_complete", "validation_status": "conditional"},
        {"evidence_id": "F7:cost", "metric": "execution_round_trip_cost_1m_bps", "value": 8.2, "validation_status": "conditional"},
    ]
    manifest, workspace = build_fund_research_workspace(
        pack,
        root=tmp_path,
        research_question="量化、指数趋势、交易成本和回撤",
        research_mode="lens",
        lens_mode="single",
        lenses=("simons",),
    )
    report = (workspace / manifest["artifacts"]["institutional_report"]["path"]).read_text(encoding="utf-8")
    ledger = json.loads((workspace / "claim_ledger.json").read_text(encoding="utf-8"))
    published_ids = {
        evidence_id
        for claim in ledger["publishable_claims"]
        for evidence_id in claim["evidence_ids"]
    }

    assert "缺少标的指数日线与完整交易成本模型" not in report
    assert "指数历史样本数（20260717）为 90" in report
    assert "index_history_sample_size" not in report
    assert {"F6:index-sample", "F6:index-vol"} <= published_ids
    assert "F5:index-pe" not in published_ids
    assert "F7:cost" not in published_ids


def test_fund_question_with_only_unrelated_supported_claims_blocks_report():
    pack = _pack()
    for code, section in pack["modules"].items():
        section["available"] = code == "F8"
        section["evidence"] = section["evidence"] if code == "F8" else []
        section["gaps"] = [] if code == "F8" else [f"{code} gap"]
    snapshot = freeze_fund_evidence(pack)
    committee, _ = synthesize_fund_committee(
        snapshot,
        research_question="产品契约如何约束复制方式？",
    )

    assert committee["publishable_claims"] == []
    assert committee["publication_status"] == "block_report"
    assert any(
        issue["code"] == "NO_SUPPORTED_CLAIMS"
        for issue in committee["safety_gate"]["issues"]
    )
