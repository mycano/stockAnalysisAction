import pytest

from stock_analysis.presentation import (
    build_delivery,
    investor_facing_violations,
    investor_semantic_text,
)


def test_metric_keys_are_translated_before_delivery():
    report = investor_semantic_text(
        "core_product_revenue 增长，roe_weighted 为 31%，total_market_cap 暂不使用。"
    )

    assert "核心产品收入" in report
    assert "加权净资产收益率" in report
    assert "总市值" in report
    assert "_" not in report


@pytest.mark.parametrize(
    "text",
    [
        "RouteDecision 已通过",
        "```json\n{}\n```",
        "详见 /Users/example/workspace.json",
        "当前 coverage_report 为 partial",
    ],
)
def test_investor_lint_rejects_engineering_output(text):
    assert investor_facing_violations(text)


def test_delivery_keeps_limitations_outside_report_body():
    delivery = build_delivery(
        "# 贵州茅台研究报告\n\n## 投资结论\n\n经营质量保持稳定。",
        notice="已按完整研究模式完成分析。",
        limitations=("未取得最新渠道库存的权威披露，因此不判断短期库存拐点。",),
    )

    rendered = delivery.render()
    assert rendered.index("# 贵州茅台研究报告") < rendered.index("---")
    assert rendered.index("---") < rendered.index("数据边界说明")
    assert "RouteDecision" not in rendered


@pytest.mark.parametrize(
    "text",
    [
        '{"route": "internal"}',
        '[{"status": "partial"}]',
    ],
)
def test_investor_lint_rejects_bare_json(text):
    assert "包含序列化 JSON" in investor_facing_violations(text)
