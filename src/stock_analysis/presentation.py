"""Investor-facing delivery boundary.

Internal route, evidence, claim, workspace, and diagnostics objects remain
auditable on disk.  This module is the only default path from workflow stdout
to an investor-facing response.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass

INTERNAL_TERMS = (
    "RouteDecision",
    "HostRequest",
    "ResolvedRequest",
    "reason_codes",
    "workflow_id",
    "output_contract",
    "block_reasons",
    "catalog_hash",
    "workspace.json",
    "evidence_manifest",
    "claim_ledger",
    "coverage_report",
    "unpublished_claims",
    "schema_version",
    "lens_id",
    "lens_mode",
    "lens_contract",
    "evidence_requirement",
    "debate_round",
    "state_revision",
    "blackboard",
)

METRIC_LABELS = {
    "core_product_revenue": "核心产品收入",
    "series_product_revenue": "系列产品收入",
    "series_revenue_yoy_pct": "系列产品收入同比变化",
    "wholesale_revenue": "批发渠道收入",
    "wholesale_revenue_yoy_pct": "批发渠道收入同比变化",
    "direct_sales_revenue": "直销渠道收入",
    "direct_sales_revenue_yoy_pct": "直销渠道收入同比变化",
    "parent_netprofit": "归属于母公司股东的净利润",
    "parent_net_profit": "归属于母公司股东的净利润",
    "parent_net_margin_pct": "归母净利率",
    "operating_cash_conversion_pct": "经营现金转化率",
    "revenue_yoy_pct": "营业收入同比增速",
    "sales_expense_yoy_pct": "销售费用同比变化",
    "total_assets": "总资产",
    "total_liabilities": "总负债",
    "parent_net_profit_yoy_pct": "归属于母公司股东的净利润同比增速",
    "roe_weighted": "加权净资产收益率",
    "gross_margin": "毛利率",
    "operating_cash_flow": "经营活动现金流",
    "free_cash_flow_lite": "简化自由现金流",
    "debt_asset_ratio": "资产负债率",
    "market_quote": "最新有效价格",
    "total_market_cap": "总市值",
    "float_market_cap": "流通市值",
    "pe_ttm": "滚动市盈率",
    "pe_static_proxy": "静态市盈率参考",
    "pb": "市净率",
    "pb_reported_proxy": "报告期市净率参考",
    "scenario_price_15x_pe": "十五倍市盈率情景价格",
    "scenario_price_18x_pe": "十八倍市盈率情景价格",
    "scenario_price_22x_pe": "二十二倍市盈率情景价格",
    "returns_5d": "近五个交易日收益率",
    "returns_20d": "近二十个交易日收益率",
    "returns_60d": "近六十个交易日收益率",
    "atr_14_pct": "十四日平均真实波幅",
    "volume_zscore": "成交量相对历史水平",
    "execution_cost_model_status": "交易成本情景完整性",
    "tracked_index": "跟踪指数",
    "top5_weight_pct": "前五大持仓权重",
    "top10_weight_pct": "前十大持仓权重",
    "disclosed_holding_count": "已披露持仓数量",
    "premium_discount_pct": "最新折溢价率",
    "premium_discount_20d_mean_pct": "近二十日平均折溢价率",
    "premium_discount_20d_std_pct": "近二十日折溢价波动",
    "reported_annual_tracking_error_pct": "披露的年化跟踪误差",
    "index_pe_total_share": "指数整体市盈率",
    "index_pe_calculation_share": "指数可计算样本市盈率",
    "index_dividend_yield_pct": "指数股息率",
    "index_valuation_scope_pct": "指数估值覆盖比例",
    "disclosed_holdings_valuation_coverage_pct": "已披露持仓估值覆盖比例",
    "positive_pe_harmonic_proxy": "正市盈率持仓调和估值参考",
    "loss_making_disclosed_weight_pct": "亏损成分披露权重",
    "max_drawdown_60d_pct": "近六十日最大回撤",
    "annualized_volatility_60d_pct": "近六十日年化波动率",
    "index_history_sample_size": "指数历史样本数",
    "index_annualized_volatility_60d_pct": "指数近六十日年化波动率",
    "latest_size_yi": "最新基金规模",
    "manager_count": "基金经理人数",
    "management_fee_pct": "管理费率",
    "custodian_fee_pct": "托管费率",
    "execution_spread_bps": "买卖价差",
    "execution_round_trip_cost_1m_bps": "百万元往返交易成本",
    "execution_average_turnover_20d_cny": "近二十日平均成交额",
    "execution_nav_dislocation_bps": "成交价与净值偏离",
    "latest_estimate_change_pct": "最新估算净值涨跌幅",
}

_SNAKE_CASE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
_JSON_FENCE = re.compile(r"```(?:json|JSON)\b")
_LOCAL_PATH = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\)[^\s)\]]+")


def _contains_json_serialization(text: str) -> bool:
    candidates = [text.strip(), *(line.strip() for line in text.splitlines())]
    candidates.extend(
        match.group(0)
        for pattern in (r"\{[^{}\n]{1,2000}\}", r"\[[^\[\]\n]{1,2000}\]")
        for match in re.finditer(pattern, text)
    )
    for candidate in candidates:
        if not candidate or candidate[0] not in "[{" or candidate[-1] not in "]}":
            continue
        try:
            value = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, (dict, list)):
            return True
    return False


@dataclass(frozen=True)
class DeliveryPayload:
    notice: str
    report: str
    limitations: tuple[str, ...] = ()

    def render(self) -> str:
        parts = [part.strip() for part in (self.notice, self.report) if part.strip()]
        if self.limitations:
            parts.extend(
                [
                    "---",
                    "数据边界说明",
                    "\n".join(f"- {item}" for item in self.limitations),
                ]
            )
        return "\n\n".join(parts).strip() + "\n"


def investor_semantic_text(text: str) -> str:
    """Translate canonical metric keys before any text reaches the investor."""

    translated = text
    for metric in sorted(METRIC_LABELS, key=len, reverse=True):
        translated = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(metric)}(?![A-Za-z0-9_])",
            METRIC_LABELS[metric],
            translated,
        )
    return translated


def investor_facing_violations(text: str) -> list[str]:
    violations = [f"包含内部术语：{term}" for term in INTERNAL_TERMS if term in text]
    if _JSON_FENCE.search(text):
        violations.append("包含 JSON 代码块")
    if _contains_json_serialization(text):
        violations.append("包含序列化 JSON")
    if _LOCAL_PATH.search(text):
        violations.append("包含本地文件路径")
    raw_fields = sorted(set(_SNAKE_CASE.findall(text)))
    if raw_fields:
        violations.append(f"包含未翻译字段：{', '.join(raw_fields)}")
    return violations


def build_delivery(
    report: str,
    *,
    notice: str = "",
    limitations: Iterable[str] = (),
) -> DeliveryPayload:
    translated = investor_semantic_text(report)
    payload = DeliveryPayload(
        notice=notice.strip(),
        report=translated.strip(),
        limitations=tuple(item.strip() for item in limitations if item.strip()),
    )
    violations = investor_facing_violations(payload.render())
    if violations:
        raise ValueError("；".join(violations))
    return payload
