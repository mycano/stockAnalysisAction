"""Deterministic investor reports for general and expert-framework research."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from statistics import median
from typing import Any

from .lens_engine import load_lens_definitions
from .presentation import METRIC_LABELS, build_delivery
from .report_contracts import load_report_contract

DISCLAIMER = "本报告基于公开信息形成研究判断，不构成个性化投资建议。"
_VALUE_LABELS = {
    "scenario_complete": "情景输入完整",
    "scenario_partial": "情景输入部分可用",
    "scenario_partial_market_rules": "市场规则输入部分可用",
    "insufficient_inputs": "输入不足，暂不发布交易成本估算",
    "primary_source": "一手来源",
    "derived_verified": "已复算验证",
}

_SCENE_MODULES = {
    "company": {
        "conclusion": ("C1", "C2", "C3", "C6"),
        "change": ("C2", "C3", "C6", "C8"),
        "business": ("C1", "C4"),
        "quality": ("C2", "C3", "C5"),
        "thesis": ("C1", "C2", "C3", "C4"),
        "competition": ("C1", "C4"),
        "financials": ("C2", "C3", "C5"),
        "valuation": ("C6",),
        "catalysts": ("C8",),
        "risks": ("C7", "C8"),
        "watchlist": ("C2", "C3", "C6", "C7", "C8"),
        "actions": ("C6", "C7", "C8"),
        "controversies": ("C1", "C3", "C4", "C6"),
        "history": ("C2", "C3", "C6"),
        "peers": ("C2", "C4", "C6"),
        "scenarios": ("C2", "C3", "C6", "C7"),
        "counter_case": ("C3", "C4", "C7", "C8"),
        "position": ("C6", "C7", "C8"),
    },
    "fund": {
        "identity": ("F1",),
        "conclusion": ("F1", "F3", "F5", "F6"),
        "holdings": ("F2",),
        "fit": ("F3", "F5", "F6"),
        "performance": ("F3", "F6"),
        "costs": ("F4", "F7"),
        "audience": ("F3", "F6", "F7"),
        "watchlist": ("F3", "F4", "F6", "F7", "F8"),
        "strategy": ("F1", "F2"),
        "return_sources": ("F2", "F3"),
        "risks": ("F4", "F6", "F7"),
        "management": ("F1", "F7"),
        "actions": ("F4", "F5", "F6", "F7", "F8"),
        "lookthrough": ("F2", "F5"),
        "factors": ("F2", "F3", "F6"),
        "attribution": ("F3", "F7"),
        "peers": ("F3", "F4", "F5", "F7"),
        "stress": ("F4", "F6", "F7"),
        "overlap": ("F2",),
    },
    "earnings": {
        "surprise": ("C2", "C3"),
        "change": ("C2", "C3"),
        "signals": ("C2", "C3", "C5", "C8"),
        "thesis": ("C2", "C3", "C6", "C8"),
        "summary": ("C2", "C3"),
        "segments": ("C1", "C3"),
        "margins": ("C2", "C3"),
        "cashflow": ("C2", "C3", "C5"),
        "guidance": ("C5", "C8"),
        "valuation": ("C6",),
        "risks": ("C7", "C8"),
        "trend": ("C2", "C3"),
        "peers": ("C2", "C3", "C6"),
        "primary": ("C1", "C2", "C3", "C5", "C8"),
        "quality": ("C2", "C3", "C5"),
        "revisions": ("C3", "C6", "C8"),
    },
    "price_move": {
        "move": ("C6", "C7"),
        "cause": ("C7", "C8"),
        "confirmed": ("C5", "C7", "C8"),
        "risk": ("C7", "C8"),
        "market": ("C6", "C7"),
        "timeline": ("C7", "C8"),
        "related": ("C7", "C8"),
        "structure": ("C6", "C7"),
        "fundamentals": ("C2", "C3", "C5"),
        "watchlist": ("C6", "C7", "C8"),
        "primary": ("C5", "C7", "C8"),
        "sentiment": ("C7", "C8"),
        "history": ("C6", "C7"),
        "positioning": ("C6", "C7"),
        "counterfactual": ("C2", "C3", "C7", "C8"),
    },
}

_SECTION_INTERPRETATIONS = {
    "business": "重点判断收入来源是否清晰、竞争优势能否转化为持续现金回报。",
    "thesis": "核心逻辑只保留能够被经营、财务或价格证据验证的部分，并以失效条件约束外推。",
    "competition": "竞争判断关注份额、定价权与替代风险，不以品牌叙事代替经营验证。",
    "financials": "财务质量同时观察增长、盈利能力、现金实现和资产负债表韧性。",
    "valuation": "估值结论以可复算输入为锚；绝对估值不可用时，保留相对估值和观察阈值。",
    "catalysts": "催化剂按已确认事项、可验证进展和低确定性观察项分层处理。",
    "risks": "风险关注触发因素、向利润和估值的传导路径，以及最先变化的观察指标。",
    "actions": "未持有者、普通持有者与高仓位持有者应采用不同的验证和风险控制条件。",
    "identity": "先确认产品类型、跟踪对象和法律披露边界，再评价收益表现。",
    "holdings": "持仓分析以最近披露时点为准，不把定期披露误写为实时持仓。",
    "fit": "市场适配度取决于底层资产估值、风格环境与投资者可承受回撤。",
    "performance": "收益必须与回撤、波动和所处市场阶段共同评价。",
    "costs": "费用、折溢价、成交价差与跟踪偏离共同决定实际持有体验。",
    "strategy": "产品契约决定收益来源和风险边界，不能用短期业绩替代策略判断。",
    "return_sources": "区分市场、行业、风格和个券贡献，避免把单一上涨阶段外推为稳定能力。",
    "management": "主动产品关注管理稳定性与风格一致性；指数产品关注跟踪质量和执行成本。",
    "surprise": "是否超预期必须以公司指引、可比期间或可核验市场预期为基准；没有基准时只陈述实际变化。",
    "change": "收入、利润、利润率与现金流需使用一致期间和口径比较。",
    "signals": "正负变化按对未来盈利和现金回报的影响排序，不以单项增长替代整体质量判断。",
    "summary": "财报摘要先报告已披露事实，再区分经营解释与分析判断。",
    "segments": "分业务分析关注增长来源、利润贡献与业务组合变化。",
    "margins": "利润率变化需结合产品结构、成本、费用和经营杠杆解释。",
    "cashflow": "利润增长只有与现金流和营运资本变化相互印证时，才代表更高盈利质量。",
    "guidance": "管理层指引与市场预期必须分开，不把分析师预测写成公司承诺。",
    "move": "先确认价格、成交和分析窗口，再讨论可能驱动。",
    "cause": "只有公司公告、监管披露或明确事件时间线支持的原因，才作为已确认触发因素。",
    "confirmed": "已确认原因与市场一致解释分开呈现，相关性不自动升级为因果。",
    "related": "高相关解释保留为待验证假设，并列出能够推翻它的信号。",
    "structure": "指数、行业、流动性和交易结构可能放大波动，但不自动改变公司基本面。",
    "fundamentals": "异动只有在盈利、现金流、资本配置或风险事实变化时，才触发基本面结论重审。",
    "timeline": "事件按公开时间排序，避免使用价格变化之后发布的信息解释此前行情。",
    "counterfactual": "若剔除同期市场和行业因素后异动仍显著，个体事件解释才获得更强支持。",
}

LENS_REPORT_OUTLINES: dict[str, tuple[str, ...]] = {
    "buffett": ("这是不是一门好生意", "护城河与定价权", "管理层与资本配置", "所有者收益与再投资", "内在价值与安全边际"),
    "munger": ("商业模式的关键变量", "激励与治理", "多学科反向检查", "会计利润与真实现金", "必须避开的愚蠢错误"),
    "duan_yongping": ("生意模式是否足够好", "企业文化与管理层", "用户价值与差异化", "现金创造与长期回报", "价格是否值得等待"),
    "zhang_kun": ("长期自由现金流来源", "竞争格局与商业壁垒", "管理层资本配置", "再投资空间与机会成本", "长期价值判断"),
    "graham": ("财务安全性", "盈利稳定性", "资产与保守价值", "安全边际与下行保护", "防御型条件检查"),
    "dalio": ("增长与通胀组合", "货币、信用与流动性", "债务周期与政策反应", "跨资产传导与相关性", "风险平衡情景"),
    "klarman": ("先看永久损失", "保守价值与折价", "资产负债表压力", "催化剂与价值实现", "等待与退出纪律"),
    "lynch": ("公司属于哪一类", "市场在期待什么故事", "增长从哪里来", "财务检查清单与估值", "持续追踪的故事线"),
    "o_neil": ("盈利与销售加速", "价格与成交确认", "相对强度与市场方向", "供需结构与机构行为", "买入与止损纪律"),
    "wood": ("颠覆性创新命题", "可扩展市场与渗透率", "单位经济性与融资能力", "指数级增长的反证", "长期情景估值"),
    "soros": ("预期与现实的缺口", "价格与基本面的反馈", "政策、信用与资金拐点", "反身性链条的断点", "快速纠错条件"),
    "livermore": ("主要趋势是否成立", "价格与成交的确认", "关键点位与市场行为", "仓位和亏损控制", "趋势失效信号"),
    "minervini": ("盈利质量与增长加速", "相对强度与趋势模板", "供需和机构参与", "风险收益比与止损", "交易假设的失效"),
    "simons": ("信号定义与数据质量", "稳定性和样本外检验", "相关性与组合效应", "成本后收益", "模型失效与再校准"),
    "feng_liu": ("市场认知处于何处", "基本面边际变化", "预期差与赔率", "可跟踪的产业信号", "认知修正与退出条件"),
}


def _metric_items(
    pack: Mapping[str, Any],
    modules: Iterable[str] | None = None,
    *,
    include_conditional: bool = False,
) -> list[dict[str, Any]]:
    selected = set(modules or ())
    rows: list[dict[str, Any]] = []
    for module, section in (pack.get("modules") or {}).items():
        if selected and module not in selected:
            continue
        for item in section.get("evidence") or []:
            metric = str(item.get("metric") or "")
            status = str(item.get("validation_status") or "").lower()
            if metric not in METRIC_LABELS or item.get("value") is None:
                continue
            allowed = {"accepted", "strongly_supported", "supported"}
            if include_conditional:
                allowed.add("conditional")
            if status not in allowed:
                continue
            rows.append({"module": module, **item})
    return rows


def _format_value(item: Mapping[str, Any]) -> str:
    value = item.get("value")
    metric = str(item.get("metric") or "")
    currency = str(item.get("currency") or "")
    numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
    if numeric and currency == "CNY" and abs(float(value)) >= 100_000_000:
        return f"{float(value) / 100_000_000:,.2f} 亿元"
    if metric == "latest_size_yi" and numeric:
        return f"{float(value):,.2f} 亿元"
    if metric == "execution_average_turnover_20d_cny" and numeric:
        return f"{float(value) / 100_000_000:,.2f} 亿元"
    if isinstance(value, float):
        rendered = f"{value:,.2f}"
    elif isinstance(value, int):
        rendered = f"{value:,}"
    else:
        rendered = _VALUE_LABELS.get(str(value), str(value))
    unit = str(item.get("unit") or "")
    if metric.endswith("_pct") or metric.startswith("returns_") or metric in {
        "gross_margin",
        "roe_weighted",
        "debt_asset_ratio",
    }:
        return f"{rendered}%"
    if metric in {
        "pe_ttm",
        "pe_static_proxy",
        "pb",
        "pb_reported_proxy",
        "index_pe_total_share",
        "positive_pe_harmonic_proxy",
    }:
        return f"{rendered} 倍"
    if metric.endswith("_bps"):
        return f"{rendered} 个基点"
    if unit and unit not in {currency, "%", "percent"}:
        return f"{rendered} {unit}"
    if currency:
        currency_label = {"CNY": "元", "HKD": "港元", "USD": "美元"}.get(
            currency,
            currency,
        )
        return f"{rendered} {currency_label}"
    return rendered


def _fact_lines(pack: Mapping[str, Any], modules: Iterable[str], *, limit: int = 6) -> list[str]:
    lines = []
    seen: set[tuple[str, str]] = set()
    disclosed_count = _metric_value(pack, "disclosed_holding_count")
    for item in _metric_items(pack, modules, include_conditional=True):
        metric = str(item["metric"])
        if metric == "execution_cost_model_status":
            continue
        label = METRIC_LABELS[metric]
        if metric == "top10_weight_pct" and disclosed_count is not None and disclosed_count < 10:
            label = f"当前已披露 {int(disclosed_count)} 只持仓合计权重"
        value_text = _format_value(item)
        if "无跟踪标的" in value_text:
            continue
        fingerprint = (label, value_text)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        period = str(item.get("period") or item.get("asof") or pack.get("trade_date") or "")
        time_text = f"（{period}）" if period else ""
        qualifier = "参考口径下，" if str(item.get("validation_status") or "").lower() == "conditional" else ""
        lines.append(f"- {qualifier}{label}{time_text}为 {value_text}。")
        if len(lines) >= limit:
            break
    return lines


def _metric_value(pack: Mapping[str, Any], *metrics: str) -> float | None:
    items = _metric_items(pack, include_conditional=True)
    for metric in metrics:
        for item in reversed(items):
            if item.get("metric") != metric:
                continue
            try:
                return float(item["value"])
            except (TypeError, ValueError):
                continue
    return None


def _event_lines(pack: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for module in ("C5", "C7", "C8"):
        for item in ((pack.get("modules") or {}).get(module) or {}).get("evidence") or []:
            title = str(item.get("title") or "").strip()
            published = str(item.get("published_at") or item.get("period") or "").strip()
            source_type = str(item.get("source_type") or "")
            if not title or source_type not in {
                "primary_disclosure",
                "structured_public_disclosure",
                "external_primary_disclosure",
            }:
                continue
            lines.append(f"- {published + '：' if published else ''}{title}")
    return list(dict.fromkeys(lines))


def _history_lines(pack: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for row in list(pack.get("financial_history") or [])[:6]:
        period = str(
            row.get("period")
            or row.get("report_date")
            or row.get("period_label")
            or ""
        )
        revenue = row.get("revenue")
        profit = row.get("parent_net_profit")
        if not period or (revenue is None and profit is None):
            continue
        parts = []
        if revenue is not None:
            parts.append(f"营业收入 {float(revenue) / 100_000_000:,.2f} 亿元")
        if profit is not None:
            parts.append(f"归母净利润 {float(profit) / 100_000_000:,.2f} 亿元")
        lines.append(f"- {period}：{'，'.join(parts)}。")
    return lines


def _peer_lines(pack: Mapping[str, Any]) -> list[str]:
    lines = []
    for peer in (pack.get("_meta") or {}).get("peer_comparison") or []:
        parts = []
        if peer.get("parent_net_profit") is not None:
            parts.append(
                f"归母净利润 {float(peer['parent_net_profit']) / 100_000_000:,.2f} 亿元"
            )
        if peer.get("roe_weighted") is not None:
            parts.append(f"净资产收益率 {float(peer['roe_weighted']):.2f}%")
        if peer.get("pe_ttm") is not None:
            parts.append(f"市盈率 {float(peer['pe_ttm']):.2f} 倍")
        if peer.get("pb") is not None:
            parts.append(f"市净率 {float(peer['pb']):.2f} 倍")
        if parts:
            lines.append(
                f"- {peer.get('name') or peer.get('symbol')}（{peer.get('symbol')}）："
                + "，".join(parts)
                + "。"
            )
    return lines


def _trailing_eps(pack: Mapping[str, Any]) -> float | None:
    history = list(pack.get("financial_history") or [])
    annual = next(
        (row for row in history if str(row.get("period_label") or "").endswith("FY")),
        None,
    )
    if not annual or annual.get("basic_eps") in (None, 0):
        return None
    latest = history[0] if history else annual
    latest_label = str(latest.get("period_label") or "")
    if latest is annual or latest_label.endswith("FY"):
        return float(annual["basic_eps"])
    latest_year = str(latest.get("report_date") or "")[:4]
    if not latest_year.isdigit() or latest.get("basic_eps") is None:
        return float(annual["basic_eps"])
    prior_label = latest_label.replace(latest_year, str(int(latest_year) - 1), 1)
    prior = next(
        (row for row in history[1:] if str(row.get("period_label") or "") == prior_label),
        None,
    )
    if not prior or prior.get("basic_eps") is None:
        return float(annual["basic_eps"])
    value = float(annual["basic_eps"]) + float(latest["basic_eps"]) - float(prior["basic_eps"])
    return value if math.isfinite(value) and value > 0 else None


def _normalized_growth_anchor(pack: Mapping[str, Any]) -> float:
    annual = [
        row
        for row in pack.get("financial_history") or []
        if str(row.get("period_label") or "").endswith("FY")
        and row.get("parent_net_profit") not in (None, 0)
    ]
    growth_rates = [
        (float(current["parent_net_profit"]) / float(previous["parent_net_profit"]) - 1) * 100
        for current, previous in zip(annual, annual[1:])
        if float(previous["parent_net_profit"]) > 0
    ]
    anchor = median(growth_rates[:3]) if growth_rates else 0.0
    return max(-20.0, min(anchor, 40.0))


def _scenario_multiples(pack: Mapping[str, Any]) -> tuple[float, float, float]:
    peer_pes = sorted(
        float(peer["pe_ttm"])
        for peer in (pack.get("_meta") or {}).get("peer_comparison") or []
        if peer.get("pe_ttm") is not None
        and math.isfinite(float(peer["pe_ttm"]))
        and 0 < float(peer["pe_ttm"]) <= 120
    )
    if len(peer_pes) >= 2:
        base = median(peer_pes)
        return (
            max(peer_pes[0], base * 0.75),
            base,
            min(peer_pes[-1], base * 1.25),
        )
    gross_margin = _metric_value(pack, "gross_margin") or 0.0
    growth = _normalized_growth_anchor(pack)
    base = 22.0 + (5.0 if growth >= 20 else 0.0) + (3.0 if gross_margin >= 40 else 0.0)
    return base * 0.75, base, base * 1.25


def _is_active_fund(pack: Mapping[str, Any]) -> bool:
    return not any(
        str(item.get("value") or "").strip()
        and "无跟踪标的" not in str(item.get("value"))
        for item in _metric_items(pack, ("F1",), include_conditional=True)
        if item.get("metric") == "tracked_index"
    )


def _fund_holdings(pack: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    holdings = (pack.get("holdings") or {}).get("holdings") or []
    return [
        item
        for item in holdings
        if isinstance(item, Mapping) and item.get("name") and item.get("weight_pct") is not None
    ]


def _fund_holding_lines(pack: Mapping[str, Any], *, limit: int = 5) -> list[str]:
    rows = _fund_holdings(pack)[:limit]
    if not rows:
        return ["- 当前仅按已披露组合汇总判断集中度，不补写未取得的底层名称与权重。"]
    asof = str((pack.get("holdings") or {}).get("asof") or pack.get("trade_date") or "")
    return [
        f"- {item['name']}（{item.get('code') or '代码未披露'}）权重约 "
        f"{float(item['weight_pct']):.2f}%（披露日 {asof}）。"
        for item in rows
    ]


def _general_conclusion(pack: Mapping[str, Any], scene: str) -> str:
    if scene == "fund":
        return_5d = _metric_value(pack, "returns_5d")
        return_20d = _metric_value(pack, "returns_20d")
        return_60d = _metric_value(pack, "returns_60d")
        drawdown = _metric_value(pack, "max_drawdown_60d_pct")
        if return_20d is not None and return_60d is not None and return_20d < 0 < return_60d:
            direction = "中期累计收益仍为正，但近二十个交易日已出现明显回撤"
        elif return_20d is not None and return_60d is not None and return_20d > 0 > return_60d:
            direction = "近二十个交易日有所修复，但中期趋势尚未扭转"
        elif return_20d is not None and return_20d > 0:
            direction = "近期趋势偏强"
        elif return_20d is not None and return_20d < 0:
            direction = "近期处于回撤或弱势阶段"
        elif return_5d is not None and return_5d > 0:
            direction = "短期有所走强，但仍需更长净值区间确认"
        elif return_5d is not None and return_5d < 0:
            direction = "短期处于回撤阶段"
        else:
            direction = "近期趋势需要结合净值与市场风格继续观察"
        risk = f"，近六十日最大回撤约 {abs(drawdown):.2f}%" if drawdown is not None else ""
        active = _is_active_fund(pack)
        role = "卫星型主动配置工具" if active else "规则化市场暴露工具"
        return f"{direction}{risk}；当前更适合作为{role}，配置比例取决于底层暴露与可承受回撤。"
    growth = _metric_value(pack, "parent_net_profit_yoy_pct", "revenue_yoy_pct")
    roe = _metric_value(pack, "roe_weighted")
    if growth is not None and growth > 10:
        quality = "经营增长仍具韧性"
    elif growth is not None and growth < 0:
        quality = "经营动能承压"
    else:
        quality = "经营表现总体平稳"
    pe = _metric_value(pack, "pe_ttm", "pe_static_proxy")
    valuation = (
        "估值处于相对克制区间"
        if pe is not None and pe < 18
        else "估值大致处于可解释区间"
        if pe is not None and pe <= 25
        else "当前价格包含较高增长要求"
        if pe is not None
        else "价格判断以经营兑现和后续估值锚为条件"
    )
    conclusion = (
        f"{quality}"
        + (f"，加权净资产收益率约 {roe:.2f}%" if roe is not None else "")
        + f"；{valuation}。未持有者宜等待价格补偿或盈利重新加速，持有者重点观察现金流与竞争优势是否延续。"
    )
    if scene == "earnings":
        return f"本期披露显示{quality}；是否构成预期差，需以明确比较基准和管理层原文复核。"
    if scene == "price_move":
        return "本次先确认价格与成交变化；没有一手事件证据时，相关线索只作为可能解释，不写成确定因果。"
    return conclusion


def _section_body(pack: Mapping[str, Any], scene: str, section_id: str, depth: str) -> list[str]:
    modules = _SCENE_MODULES[scene].get(section_id, tuple(pack.get("modules") or {}))
    facts = _fact_lines(pack, modules)
    if section_id == "conclusion":
        return [_general_conclusion(pack, scene), "", *facts[:3]]
    if scene == "price_move" and section_id == "move":
        price = _metric_value(pack, "market_quote")
        return_5d = _metric_value(pack, "returns_5d")
        return_20d = _metric_value(pack, "returns_20d")
        volume = _metric_value(pack, "volume_zscore")
        return [
            (
                f"数据截止时价格约 {price:.2f} 元。"
                if price is not None
                else "当前先确认异动窗口内的价格变化。"
            ),
            (
                f"近五日收益约 {return_5d:+.2f}%、近二十日约 {return_20d:+.2f}%；"
                if return_5d is not None and return_20d is not None
                else "收益窗口需要与市场和行业基准共同解释；"
            )
            + (
                f"成交量相对历史水平约 {volume:+.2f} 个标准差。"
                if volume is not None
                else "成交放大程度尚需历史序列验证。"
            ),
        ]
    if scene == "company" and section_id == "business":
        margin = _metric_value(pack, "gross_margin")
        return [
            "公司盈利能力主要取决于核心产品收入、定价能力与需求韧性。"
            + (f" 当前毛利率约 {margin:.2f}%，说明产品结构仍具较强价值创造能力。" if margin is not None else ""),
            "若核心产品收入与现金回报长期背离，商业模式质量需要重新评估。",
            "",
            *facts,
        ]
    if scene == "company" and section_id == "thesis":
        roe = _metric_value(pack, "roe_weighted")
        debt = _metric_value(pack, "debt_asset_ratio")
        cash = _metric_value(pack, "operating_cash_flow", "free_cash_flow_lite")
        return [
            "- 盈利质量："
            + (
                f"报告期净资产收益率约 {roe:.2f}%，需结合完整年度和历史区间判断资本回报持续性；"
                if roe is not None
                else "以资本回报持续性为验证重点；"
            )
            + "若盈利能力连续下行，本项逻辑失效。",
            "- 财务韧性："
            + (f"资产负债率约 {debt:.2f}%，当前财务结构较稳健；" if debt is not None else "重点检验杠杆与短期偿债压力；")
            + "若杠杆显著上升且现金流恶化，本项逻辑失效。",
            "- 现金回报："
            + (f"已披露经营现金流约 {cash / 100_000_000:,.2f} 亿元；" if cash is not None else "需以经营现金流和自由现金流继续验证；")
            + "若利润增长不能转化为现金，本项逻辑失效。",
        ]
    if scene == "company" and section_id == "competition":
        return [
            "高毛利与核心产品收入为定价权提供间接支持；竞争强弱可由产品收入、毛利率、"
            "终端需求和现金回款的同向变化持续跟踪。",
            "最先需要观察的恶化信号是核心产品收入减速、毛利率下降与现金回款转弱同时出现。",
            "",
            *facts,
        ]
    if section_id == "valuation" and scene == "company":
        pe = _metric_value(pack, "pe_ttm", "pe_static_proxy")
        pb = _metric_value(pack, "pb", "pb_reported_proxy")
        price = _metric_value(pack, "market_quote")
        low = _metric_value(pack, "scenario_price_18x_pe", "scenario_price_15x_pe")
        high = _metric_value(pack, "scenario_price_22x_pe")
        lines = [
            (
                f"参考口径下市盈率约 {pe:.2f} 倍，"
                + (
                    "对稳定增长已有一定要求，但尚未进入必须依赖高增长才能解释的区间。"
                    if pe is not None and pe <= 25
                    else "当前价格对未来增长兑现提出较高要求。"
                )
            )
            if pe is not None
            else "估值判断以最新价格、盈利与现金回报的相互关系为核心。",
        ]
        if price is not None and low is not None and high is not None:
            lower, upper = sorted((low, high))
            relation = (
                f"低于参考情景下沿 {lower:.2f}"
                if price < lower
                else f"高于参考情景上沿 {upper:.2f}"
                if price > upper
                else f"位于参考情景 {lower:.2f} 至 {upper:.2f} 之间"
            )
            lines.append(
                f"当前价格约 {price:.2f}，{relation}；"
                "区间仅用于检验盈利与估值敏感性，不是买卖指令。"
            )
        if depth == "deep" and pe is not None:
            lines.append(
                f"收益率反向验证：当前市盈率对应的盈利收益率约 {100 / pe:.2f}%，"
                "用于比较无风险利率与增长补偿。"
            )
        if depth == "deep" and pb is not None:
            lines.append(
                f"资产回报交叉验证：当前市净率约 {pb:.2f} 倍，"
                "需与净资产收益率和资本密集度共同解释；这与利润倍数法构成独立的资产端校验。"
            )
        return [*lines, "", *facts]
    if section_id == "actions" and scene == "company":
        return [
            "- 未持有者：优先等待价格接近保守估值情景，或盈利与现金流出现可验证的再加速。",
            "- 普通持有者：在核心产品收入、盈利能力和现金回报稳定时继续跟踪；任一关键逻辑被证伪时重新评估。",
            "- 高仓位持有者：先检查单一标的集中度与最大可承受回撤，不因公司质量较高而忽略估值和组合风险。",
        ]
    if section_id == "catalysts" and scene == "company":
        return [
            "- 经营催化：核心产品收入恢复更快增长，并由现金回款同步验证。",
            "- 估值催化：盈利预期上修而估值倍数保持稳定，使价格回报更多来自基本面兑现。",
            "- 股东回报催化：分红或回购提升现金回报，但需以公司正式披露为准。",
        ]
    if section_id == "risks" and scene == "company":
        drawdown = _metric_value(pack, "max_drawdown_60d_pct")
        volatility = _metric_value(pack, "annualized_volatility_60d_pct")
        return [
            "- 需求与竞争风险：核心产品收入、毛利率和现金回款同步转弱，将削弱定价权判断。",
            "- 盈利质量风险：利润增长若长期快于经营现金流，需重新检查渠道、信用和营运资本变化。",
            "- 估值风险：盈利兑现不足可能触发估值压缩。"
            + (
                f"近六十日最大回撤约 {abs(drawdown):.2f}%"
                + (f"、年化波动率约 {volatility:.2f}%" if volatility is not None else "")
                + "，说明价格风险不能由公司质量替代。"
                if drawdown is not None
                else "应以价格回撤和估值倍数变化作为先行信号。"
            ),
        ]
    if scene == "fund" and section_id == "strategy":
        active = _is_active_fund(pack)
        return [
            (
                "该产品属于主动管理基金，重点评价基金经理、持仓集中度、风格一致性与策略容量。"
                if active
                else "该产品以指数规则提供市场暴露，重点评价指数编制、集中度、费用与跟踪质量。"
            ),
            "产品是否优秀与当前是否适合配置必须分开判断。",
            "",
            *facts,
        ]
    if scene == "fund" and section_id == "return_sources":
        return [
            "收益来源应拆分为市场、行业、风格和个券贡献；当前披露只能确认持仓集中度与阶段收益，不能把顺风期表现全部归因于管理能力。",
            "",
            *facts,
        ]
    if scene == "fund" and section_id == "fit":
        recent = _metric_value(pack, "returns_60d", "returns_20d")
        drawdown = _metric_value(pack, "max_drawdown_60d_pct")
        return [
            (
                f"近阶段收益约 {recent:.2f}%，同时近六十日最大回撤约 {abs(drawdown):.2f}%；"
                "收益弹性与回撤压力并存，更适合风险预算明确的卫星配置。"
                if recent is not None and drawdown is not None
                else "当前适配度取决于底层风格与投资者可承受回撤是否一致。"
            )
        ]
    if scene == "fund" and section_id == "risks":
        top10 = _metric_value(pack, "top10_weight_pct")
        disclosed_count = _metric_value(pack, "disclosed_holding_count")
        drawdown = _metric_value(pack, "max_drawdown_60d_pct")
        volatility = _metric_value(pack, "annualized_volatility_60d_pct")
        return [
            "- 回撤风险："
            + (
                f"近六十日最大回撤约 {abs(drawdown):.2f}%"
                + (f"、年化波动率约 {volatility:.2f}%" if volatility is not None else "")
                + "，配置前需将其纳入组合风险预算。"
                if drawdown is not None
                else "需用完整净值序列检验下行阶段表现。"
            ),
            "- 集中度风险："
            + (
                (
                    f"最近仅披露 {int(disclosed_count)} 只持仓，合计权重约 {top10:.2f}%；"
                    "该数值不是完整前十大持仓权重。"
                    if disclosed_count is not None and disclosed_count < 10
                    else f"最近披露的前十大持仓权重约 {top10:.2f}%，"
                )
                + "底层资产共振下跌可能放大净值波动。"
                if top10 is not None
                else "需结合最近披露持仓检查行业与个券集中度。"
            ),
            "- 信息时滞风险：定期报告持仓不等于实时持仓，不能据此精确推断当前暴露。",
        ]
    if scene == "fund" and section_id == "management":
        active = _is_active_fund(pack)
        modules = ("F1",) if active else ("F1", "F7")
        management_facts = _fact_lines(pack, modules)
        manager_count = _metric_value(pack, "manager_count")
        size = _metric_value(pack, "latest_size_yi")
        return [
            (
                "主动产品不能仅凭阶段收益认定管理能力。"
                + (
                    f"当前披露基金经理 {int(manager_count)} 人、基金规模约 {size:.2f} 亿元；"
                    if manager_count is not None and size is not None
                    else ""
                )
                + "后续应比较任职前后、规模扩张前后及不同市场阶段的选股和行业配置贡献。"
                "取得任期净值与基准后，应分解超额收益、回撤控制和风格漂移；"
                "当前只确认团队与规模事实，不据此给出能力评级。"
                if active
                else "指数产品重点检查指数规则、跟踪偏离、费用与场内执行质量。"
            ),
            "",
            *management_facts,
        ]
    if scene == "fund" and depth == "deep" and section_id == "lookthrough":
        top5 = _metric_value(pack, "top5_weight_pct")
        disclosed_count = _metric_value(pack, "disclosed_holding_count")
        return [
            (
                f"最近披露组合中，前五项合计权重约 {top5:.2f}%；"
                + (
                    f"当前只取得 {int(disclosed_count)} 项持仓，不能把该样本外推为完整实时组合。"
                    if disclosed_count is not None and disclosed_count < 10
                    else "集中度应与行业共振风险一并评估。"
                )
                if top5 is not None
                else "底层穿透以最近披露时点为边界，不把定期披露误写为实时组合。"
            ),
            *_fund_holding_lines(pack),
        ]
    if scene == "fund" and depth == "deep" and section_id == "factors":
        top5 = _metric_value(pack, "top5_weight_pct")
        return_20d = _metric_value(pack, "returns_20d")
        return_60d = _metric_value(pack, "returns_60d")
        if return_20d is not None and return_60d is not None:
            if return_20d * return_60d < 0:
                trend_interpretation = (
                    f"近二十日收益约 {return_20d:+.2f}%，近六十日约 {return_60d:+.2f}%；"
                    "两段方向相反，说明风格或趋势正在切换，不能用单一窗口外推。"
                )
            elif return_20d > 0:
                trend_interpretation = (
                    f"近二十日收益约 {return_20d:+.2f}%，近六十日约 {return_60d:+.2f}%；"
                    "两个窗口均为正只能确认阶段顺风，仍不能单独证明稳定管理能力。"
                )
            else:
                trend_interpretation = (
                    f"近二十日收益约 {return_20d:+.2f}%，近六十日约 {return_60d:+.2f}%；"
                    "两个窗口均承压，应优先检查底层风格是否仍符合原配置目的。"
                )
        else:
            trend_interpretation = "风格稳定性仍需用完整净值与基准序列检验。"
        return [
            (
                f"披露持仓前五项合计约 {top5:.2f}%，说明组合表现会明显受主要持仓共同方向影响。"
                if top5 is not None
                else "当前先以披露持仓集中度约束风格判断。"
            ),
            trend_interpretation,
            *_fund_holding_lines(pack, limit=3),
        ]
    if scene == "fund" and depth == "deep" and section_id == "peers":
        active = _is_active_fund(pack)
        return [
            (
                "主动基金的同类比较应使用同策略产品，统一比较经理任期、超额收益、最大回撤、"
                "风格漂移、规模与费率；现有事实不足以对同类产品作可靠排名。"
                if active
                else "ETF 的同类比较应限定同一指数或高度相近指数，统一比较费率、跟踪误差、"
                "折溢价、成交额与规模；不同底层指数的短期收益不可直接排名。"
            ),
            "本产品当前可确认的自我基准如下：",
            *_fact_lines(pack, ("F3", "F4", "F5", "F7"), limit=6),
        ]
    if scene == "fund" and depth == "deep" and section_id == "stress":
        drawdown = abs(_metric_value(pack, "max_drawdown_60d_pct") or 0.0)
        volatility = _metric_value(pack, "annualized_volatility_60d_pct")
        premium_mean = _metric_value(pack, "premium_discount_20d_mean_pct")
        premium_std = _metric_value(pack, "premium_discount_20d_std_pct")
        lines = [
            (
                f"- 历史压力：若近期最大回撤重演，净值下行幅度约 {drawdown:.2f}%；"
                f"更严厉情景按其 1.5 倍估算约为 {drawdown * 1.5:.2f}%。"
                if drawdown
                else "- 历史压力：需取得完整净值序列后再量化回撤情景，不用零值代替缺口。"
            ),
            (
                f"- 波动压力：近六十日年化波动率约 {volatility:.2f}%，"
                "若组合风险预算低于这一水平，应降低配置上限而非依赖短期反弹。"
                if volatility is not None
                else "- 波动压力：配置前需先确定可承受回撤与持有期限。"
            ),
        ]
        if premium_mean is not None and premium_std is not None:
            lines.append(
                f"- 交易压力：近二十日折溢价均值约 {premium_mean:.2f}%、波动约 {premium_std:.2f}%；"
                f"均值减两倍波动对应约 {premium_mean - 2 * premium_std:.2f}%，"
                "用于检验极端成交条件，不代表预测。"
            )
        lines.append("- 退出触发：底层资产共振下跌、流动性恶化与产品规则变化同时出现时，应重新评估组合角色。")
        return lines
    if scene == "fund" and depth == "deep" and section_id == "overlap":
        return [
            "组合重叠必须与用户现有持仓逐项比对；未提供组合时，不输出伪精确的重叠比例。",
            "优先检查以下主要披露持仓是否已通过其他基金或个股重复持有：",
            *_fund_holding_lines(pack),
        ]
    if section_id == "actions" and scene == "fund":
        return [
            "- 开始观察：产品策略、基金经理或指数规则清晰，且底层暴露符合组合目标。",
            "- 分批配置：回撤风险可承受，底层估值与市场风格提供合理补偿。",
            "- 降低仓位：风格逆风、集中度或波动显著超出风险预算。",
            "- 重新评估产品：基金经理、指数规则、费用、规模或跟踪质量发生实质变化。",
        ]
    if scene == "price_move" and section_id in {"confirmed", "primary"}:
        events = _event_lines(pack)
        if events:
            return [
                "以下事项具有公司、监管或结构化公告证据，并按公开时间列示：",
                *events,
            ]
        return [
            "截至数据截止时点，未发现能够把本次价格变化确认为单一公司事件的一手披露；"
            "因此本节不发布确定因果。"
        ]
    if scene == "price_move" and section_id == "cause":
        events = _event_lines(pack)
        if events:
            return [
                "一手披露中与异动窗口最接近的事项如下；是否构成主要触发仍需结合发布时间和成交变化判断：",
                *events[:3],
            ]
        return [
            "当前没有一手披露支持单一公司事件解释。更合理的顺序是先检验同期市场与行业波动，"
            "再观察成交放大、资金行为和后续公告；这些线索在验证前都不是确定原因。"
        ]
    if scene == "price_move" and section_id == "related":
        return [
            "- 市场与行业同步波动可能放大个股表现；相关性不自动升级为因果，"
            "只有剔除共同因素后仍显著，个体解释才更可信。",
            "- 资金、情绪和技术结构仅作为待验证假设，不替代公司公告或基本面事实。",
            "- 若后续公告时间晚于价格异动，不应用该公告倒推此前行情的确定原因。",
        ]
    if scene == "price_move" and section_id == "market":
        returns = _metric_value(pack, "returns_5d", "returns_20d")
        volume = _metric_value(pack, "volume_zscore")
        return [
            (
                f"窗口收益约 {returns:+.2f}%；"
                if returns is not None
                else "当前先确认价格窗口与市场对照；"
            )
            + (
                f"成交量相对历史水平为 {volume:+.2f} 个标准差。"
                if volume is not None
                else "成交确认仍需结合历史分布。"
            ),
            "价格和成交只说明异动强度，不直接证明公司事件或基本面因果。",
            "",
            *_fact_lines(pack, ("C6",), limit=4),
        ]
    if scene == "price_move" and section_id == "timeline":
        events = _event_lines(pack)
        return (
            [
                "事件按公开时间排序，只有发布时间不晚于异动窗口的材料才可解释当时价格：",
                *events,
            ]
            if events
            else [
                "截至数据截止时点，事件窗口内未发现可确认的公司或监管披露；"
                "后续材料不得倒推为此前价格变化的既定原因。"
            ]
        )
    if scene == "price_move" and section_id == "sentiment":
        drawdown = _metric_value(pack, "max_drawdown_60d_pct")
        volatility = _metric_value(pack, "annualized_volatility_60d_pct")
        return [
            (
                f"近六十日最大回撤约 {abs(drawdown):.2f}%"
                + (f"、年化波动率约 {volatility:.2f}%" if volatility is not None else "")
                + "；情绪解释只能用于描述风险偏好，不能替代事件证据。"
                if drawdown is not None
                else "情绪仅作为风险偏好线索，不能替代公司公告或基本面事实。"
            )
        ]
    if scene == "price_move" and section_id == "history":
        return_5d = _metric_value(pack, "returns_5d")
        return_20d = _metric_value(pack, "returns_20d")
        return [
            (
                f"当前五日与二十日收益分别约 {return_5d:+.2f}%、{return_20d:+.2f}%。"
                if return_5d is not None and return_20d is not None
                else "当前证据先用于刻画本次窗口，不强行匹配历史样本。"
            ),
            "历史类比只有在市场环境、事件类型和成交结构同时可比时才有意义；"
            "现有事实不足以发布机械的相似日胜率。",
        ]
    if scene == "price_move" and section_id == "positioning":
        volume = _metric_value(pack, "volume_zscore")
        turnover = _metric_value(pack, "execution_average_turnover_20d_cny")
        return [
            (
                f"成交量相对历史水平约 {volume:+.2f} 个标准差；"
                if volume is not None
                else "成交量位置尚需历史序列确认；"
            )
            + (
                f"近二十日平均成交额约 {turnover / 100_000_000:.2f} 亿元。"
                if turnover is not None
                else "当前不据此推断具体机构或杠杆资金方向。"
            ),
            "公开量价数据不能识别单一资金主体，筹码判断保留为待验证假设。",
        ]
    if scene == "earnings" and section_id == "trend":
        history = _history_lines(pack)
        return (
            [
                "多期趋势按一致财务口径排列，重点识别增长换挡而非只看单季同比：",
                *history,
            ]
            if len(history) >= 2
            else [
                "当前可比期间不足两个，本节只保留本期实际变化，不把单期表现外推为长期趋势。",
                *_fact_lines(pack, ("C2", "C3"), limit=4),
            ]
        )
    if scene == "earnings" and section_id == "quality":
        profit = _metric_value(pack, "parent_net_profit")
        cash = _metric_value(pack, "operating_cash_flow")
        debt = _metric_value(pack, "debt_asset_ratio")
        lines = [
            "会计质量以利润、经营现金流、营运资本与一次性项目是否相互印证为核心，"
            "不把利润同比自动等同于可持续现金收益。"
        ]
        if profit is not None and cash is not None and profit:
            lines.append(
                f"经营现金流约为归母净利润的 {cash / profit:.2f} 倍；"
                "该比例用于识别现金实现，不替代完整现金流附注复核。"
            )
        if debt is not None:
            lines.append(f"资产负债率约 {debt:.2f}%，需结合有息负债和现金储备判断财务韧性。")
        lines.append("未取得明确一次性项目证据时，不推定其对利润的正负贡献。")
        return lines
    if scene == "company" and section_id == "history":
        history = _history_lines(pack)
        return (
            [
                "以下期间按一致财务口径比较收入与利润，用于识别增长换挡，"
                "不机械类比宏观环境不同的年份。",
                *history,
            ]
            if len(history) >= 2
            else _fact_lines(pack, ("C2", "C3"), limit=4)
        )
    if scene == "company" and section_id == "peers":
        peers = _peer_lines(pack)
        return (
            [
                "可比组按相近业务或产业链位置选择，并同时比较盈利、资本回报与估值：",
                *peers,
            ]
            if len(peers) >= 3
            else [
                "以公司自身的增长、盈利能力、现金回报与估值作为纵向基准：",
                *_fact_lines(pack, ("C2", "C3", "C6"), limit=6),
            ]
        )
    if section_id == "scenarios":
        eps = _trailing_eps(pack)
        growth = _normalized_growth_anchor(pack)
        low_pe, base_pe, high_pe = _scenario_multiples(pack)
        scenario_rows = (
            ("悲观", max(growth - 15.0, -25.0), low_pe),
            ("基准", growth, base_pe),
            ("乐观", min(growth + 10.0, 50.0), high_pe),
        )
        if eps is None:
            return _fact_lines(pack, ("C2", "C3", "C6", "C7"), limit=6)
        return [
            f"以下敏感性以可复算的滚动每股收益约 {eps:.2f} 元为起点，"
            f"历史年度利润增速锚经稳健约束后为 {growth:+.1f}%。",
            *(
                f"- {name}情景：利润增速假设 {scenario_growth:+.1f}%，"
                f"估值假设 {scenario_pe:.1f} 倍"
                + f"，对应价格敏感性约 {eps * (1 + scenario_growth / 100) * scenario_pe:.2f}"
                + "；触发信号由收入、现金流和估值倍数共同验证。"
                for name, scenario_growth, scenario_pe in scenario_rows
            ),
        ]
    if section_id == "counter_case":
        return [
            "当前结论最可能错在把阶段性经营表现外推得过久，或低估估值压缩与竞争变化。",
            "若核心盈利、现金流或底层资产收益连续背离当前判断，应立即重估原有逻辑。",
            *facts,
        ]
    if section_id == "position":
        return [
            "- 观察仓：用于验证核心经营、估值和风险信号是否同向。",
            "- 标准仓：仅在关键逻辑持续兑现、价格补偿充分且组合风险可承受时考虑。",
            "- 上限仓：必须结合用户完整组合、成本与风险预算后单独评估。",
            "- 减仓或退出：核心逻辑被证伪、估值补偿消失或组合风险超限。",
        ]
    interpretation = _SECTION_INTERPRETATIONS.get(section_id)
    if depth == "deep" and section_id in {"history", "peers", "controversies", "lookthrough", "factors", "attribution", "stress", "overlap"}:
        interpretations = {
            "history": "历史比较只选择经营阶段、盈利周期和估值条件真正可比的时期，避免机械类比。",
            "peers": "同业比较同时审视增长、盈利、现金流、资本效率和估值，单一倍数不构成结论。",
            "controversies": "核心争议集中在增长的持续性、质量溢价与市场预期是否已经透支。",
            "lookthrough": "底层穿透以最近披露时点和指数规则为边界，重点识别行业与个券集中度。",
            "factors": "风格判断区分市场、行业、规模与成长因子，短期收益不能证明风格稳定。",
            "attribution": "阶段归因区分市场环境、行业选择和产品执行，避免把顺风期表现全部归于能力。",
            "stress": "压力测试关注底层资产共振下跌、流动性变差和折溢价放大的共同影响。",
            "overlap": "组合重叠应以底层成分和权重为准，名称不同不代表风险来源不同。",
        }
        interpretation = interpretations[section_id]
    body = [interpretation] if interpretation else []
    body.extend(["", *facts] if facts else [])
    if not body:
        body.append("本节仅保留能够由当前公开事实直接支持的判断，不延伸未经验证的叙事。")
    return body


def compose_general_report(
    pack: Mapping[str, Any],
    *,
    scene: str,
    depth: str,
) -> str:
    contract = load_report_contract(scene, depth)
    title_kind = {
        "company": "个股",
        "fund": "基金",
        "earnings": "财报",
        "price_move": "异动",
    }[scene]
    lines = [
        f"# {pack.get('name') or pack.get('symbol')}（{pack.get('symbol')}）{title_kind}研究报告",
        "",
        f"**数据截止日期**：{pack.get('trade_date')}",
        "",
    ]
    for section in contract.sections:
        lines.extend([f"## {section.heading}", ""])
        lines.extend(_section_body(pack, scene, section.section_id, depth))
        lines.append("")
    if scene in {"company", "fund"} and depth in {"quick", "standard"}:
        lines.extend(
            [
                "如需进一步展开同业对比、多期验证和情景分析，可继续要求“深度分析”。",
                "",
            ]
        )
    lines.extend([DISCLAIMER, "投资有风险，决策需结合自身目标与风险承受能力。"])
    report = "\n".join(lines).strip()
    violations = contract.validate(report)
    if violations:
        raise ValueError("；".join(violations))
    return build_delivery(report).report


def compose_blocked_report(pack: Mapping[str, Any], reasons: Iterable[str]) -> str:
    """Explain a true publication blocker without exposing internal state."""

    natural_reasons = [str(reason).strip() for reason in reasons if str(reason).strip()]
    report = "\n".join(
        [
            f"# {pack.get('name') or pack.get('symbol')}（{pack.get('symbol')}）研究提示",
            "",
            "当前公开信息无法可靠确认研究对象或关键披露边界，因此本次不发布投资结论。",
            *(f"- {reason}" for reason in natural_reasons),
            "",
            "确认标的身份和披露口径后，可重新生成完整报告。",
        ]
    )
    return build_delivery(report).report


def _framework_facts(
    pack: Mapping[str, Any],
    *,
    modules: Iterable[str] | None = None,
    limit: int = 5,
) -> list[str]:
    if any(str(module).startswith("M") for module in (pack.get("modules") or {})):
        return _market_fact_lines(pack.get("modules") or {}, limit=limit)
    facts = _fact_lines(pack, tuple(modules or pack.get("modules") or {}), limit=limit)
    return facts or ["- 当前可发布事实仅用于约束框架判断，不据此补写未经验证的数据。"]


def _translated_lens_claims(opinion: Mapping[str, Any], *, limit: int = 3) -> list[str]:
    translated: list[str] = []
    for item in opinion.get("publishable_claims") or []:
        text = str(item.get("claim") or "").strip()
        if not text:
            continue
        metric_match = re.fullmatch(r"([a-z][a-z0-9_]*)=([^。]+)。?", text)
        if metric_match and metric_match.group(1) in METRIC_LABELS:
            metric, raw_value = metric_match.groups()
            try:
                value: Any = float(raw_value.rstrip("%"))
            except ValueError:
                value = raw_value
            formatted_item: dict[str, Any] = {"metric": metric, "value": value}
            if metric in {
                "core_product_revenue",
                "series_product_revenue",
                "wholesale_revenue",
                "parent_netprofit",
                "parent_net_profit",
                "operating_cash_flow",
                "free_cash_flow_lite",
                "market_quote",
                "total_market_cap",
                "float_market_cap",
            }:
                formatted_item["currency"] = "CNY"
            period = str(item.get("applicable_period") or "").strip()
            period_text = f"（{period}）" if period else ""
            translated.append(
                f"{METRIC_LABELS[metric]}{period_text}为 {_format_value(formatted_item)}。"
            )
            if len(translated) >= limit:
                break
            continue
        fields = set(re.findall(r"\b[a-z][a-z0-9_]*\b", text))
        if any(field not in METRIC_LABELS for field in fields):
            continue
        for field in sorted(fields, key=len, reverse=True):
            text = text.replace(f"{field}=", f"{METRIC_LABELS[field]}为")
            text = text.replace(field, METRIC_LABELS[field])
        translated.append(text)
        if len(translated) >= limit:
            break
    return translated


def _translated_lens_analyses(
    opinion: Mapping[str, Any],
    *,
    modules: Iterable[str] = (),
    metrics: Iterable[str] = (),
    limit: int = 5,
) -> list[str]:
    periods: dict[str, str] = {}
    for claim in opinion.get("publishable_claims") or []:
        match = re.fullmatch(
            r"([a-z][a-z0-9_]*)=([^。]+)。?",
            str(claim.get("claim") or "").strip(),
        )
        if match:
            periods[match.group(1)] = str(claim.get("applicable_period") or "").strip()
    translated: list[str] = []
    currency_metrics = {
        "core_product_revenue",
        "series_product_revenue",
        "wholesale_revenue",
        "direct_sales_revenue",
        "parent_netprofit",
        "parent_net_profit",
        "operating_cash_flow",
        "free_cash_flow_lite",
        "market_quote",
        "total_market_cap",
        "float_market_cap",
        "total_assets",
        "total_liabilities",
    }
    selected_modules = set(modules)
    preferred_metrics = tuple(metrics)
    metric_order = {metric: index for index, metric in enumerate(preferred_metrics)}
    analyses = list(opinion.get("metric_analyses") or [])
    if preferred_metrics:
        analyses.sort(
            key=lambda item: metric_order.get(str(item.get("metric") or ""), len(metric_order))
        )
    for analysis in analyses:
        metric = str(analysis.get("metric") or "")
        if selected_modules and str(analysis.get("module") or "") not in selected_modules:
            continue
        if preferred_metrics and metric not in metric_order:
            continue
        if metric not in METRIC_LABELS or analysis.get("value") is None:
            continue
        formatted_item: dict[str, Any] = {"metric": metric, "value": analysis["value"]}
        if metric in currency_metrics:
            formatted_item["currency"] = "CNY"
        period = periods.get(metric, "")
        period_text = f"（{period}）" if period else ""
        focus = str(analysis.get("interpretation") or "").partition("；")[2]
        focus = re.sub(r"（[CFM]\d+）[。.]?$", "", focus).strip("。 ")
        line = f"{METRIC_LABELS[metric]}{period_text}为 {_format_value(formatted_item)}"
        if focus:
            line += f"；{focus}"
        translated.append(line + "。")
        if len(translated) >= limit:
            break
    return translated


def _lens_section_modules(heading: str) -> tuple[str, ...]:
    rules = (
        (("管理层", "资本配置", "激励", "治理", "文化"), ("C5", "C2", "F7")),
        (("内在价值", "安全边际", "估值", "价格", "赔率", "买入", "止损", "仓位"), ("C6", "C7", "F4", "F6")),
        (
            ("成本后收益", "交易成本", "样本外", "信号定义", "数据质量", "稳定性"),
            ("C7", "F6", "F7"),
        ),
        (("现金", "盈利", "财务", "资产", "下行保护", "单位经济", "成本"), ("C2", "C5", "F3", "F4")),
        (("趋势", "成交", "相对强度", "关键点", "信号"), ("C7", "C3", "F3", "F6")),
        (("宏观", "通胀", "货币", "信用", "债务", "跨资产", "政策"), ("M1", "M5", "M6", "C7", "C8")),
        (
            ("护城河", "竞争", "生意", "商业", "增长", "故事", "创新", "渗透", "市场认知", "行业"),
            ("C1", "C2", "C3", "C4", "F1", "F2"),
        ),
    )
    for keywords, modules in rules:
        if any(keyword in heading for keyword in keywords):
            return modules
    return ()


def _lens_section_metrics(heading: str) -> tuple[str, ...]:
    rules = (
        (("护城河", "定价权", "差异化"), ("gross_margin", "core_product_revenue", "revenue_yoy_pct")),
        (
            ("好生意", "商业模式"),
            ("parent_net_margin_pct", "operating_cash_conversion_pct", "core_product_revenue"),
        ),
        (
            ("管理层", "资本配置", "激励", "治理", "文化"),
            ("roe_weighted", "free_cash_flow_lite", "operating_cash_flow", "debt_asset_ratio"),
        ),
        (
            ("所有者收益", "现金", "再投资"),
            ("free_cash_flow_lite", "operating_cash_flow", "operating_cash_conversion_pct", "roe_weighted"),
        ),
        (
            ("内在价值", "安全边际", "估值", "价格", "赔率"),
            ("pe_ttm", "pe_static_proxy", "pb", "pb_reported_proxy", "market_quote"),
        ),
        (
            ("成本后收益", "交易成本"),
            (
                "execution_round_trip_cost_1m_bps",
                "execution_spread_bps",
                "execution_average_turnover_20d_cny",
                "management_fee_pct",
            ),
        ),
        (
            ("信号定义", "数据质量", "样本外", "稳定性"),
            (
                "index_history_sample_size",
                "index_annualized_volatility_60d_pct",
                "returns_60d",
                "annualized_volatility_60d_pct",
            ),
        ),
        (
            ("趋势", "成交", "相对强度", "关键点"),
            ("returns_20d", "returns_60d", "returns_5d", "volume_zscore"),
        ),
        (
            ("增长", "故事", "创新", "渗透"),
            ("revenue_yoy_pct", "parent_net_profit_yoy_pct", "core_product_revenue"),
        ),
        (
            ("财务", "资产", "下行保护", "永久损失"),
            ("debt_asset_ratio", "total_liabilities", "total_assets", "roe_weighted"),
        ),
    )
    for keywords, metrics in rules:
        if any(keyword in heading for keyword in keywords):
            return metrics
    return ()


_LENS_SCOPE_LABELS = {
    "C1": "商业模式",
    "C2": "财务质量",
    "C3": "经营增长",
    "C4": "竞争优势",
    "C5": "治理与现金回报",
    "C6": "估值",
    "C7": "价格与风险",
    "C8": "催化剂与外部事件",
    "F1": "产品契约",
    "F2": "持仓与暴露",
    "F3": "收益来源",
    "F4": "费用",
    "F5": "市场适配",
    "F6": "回撤与波动",
    "F7": "管理与跟踪质量",
    "F8": "组合行动条件",
}


def _market_fact_lines(modules: Mapping[str, Any], *, limit: int = 8) -> list[str]:
    lines: list[str] = []
    m1 = modules.get("M1") or {}
    for row in [
        *(m1.get("a_indices") or []),
        *(m1.get("hk_indices") or []),
        *(m1.get("us_indices") or []),
    ]:
        if row.get("name") and row.get("change_pct") is not None:
            lines.append(f"- {row['name']}涨跌幅为 {float(row['change_pct']):+.2f}%。")
    breadth = m1.get("breadth") or {}
    if breadth.get("available"):
        lines.append(
            f"- 市场上涨 {breadth.get('up', 0)} 家、下跌 {breadth.get('down', 0)} 家。"
        )
    m2 = modules.get("M2") or {}
    for row in (m2.get("industry_top20") or [])[:3]:
        if row.get("name") and row.get("change_pct") is not None:
            lines.append(f"- {row['name']}行业涨跌幅为 {float(row['change_pct']):+.2f}%。")
    for module in ("M2", "M3", "M4", "M5", "M6"):
        summary = str((modules.get(module) or {}).get("summary") or "").strip()
        if summary:
            lines.append(f"- {summary}")
    return lines[:limit] or ["- 当前报告只保留已取得的指数、行业和成交事实，不扩展未经验证的市场叙事。"]


def _market_section(
    modules: Mapping[str, Any],
    section_id: str,
    *,
    depth: str,
) -> list[str]:
    m1 = modules.get("M1") or {}
    m2 = modules.get("M2") or {}
    facts = _market_fact_lines(modules)
    if section_id == "conclusion":
        changes = [
            float(row["change_pct"])
            for row in [
                *(m1.get("a_indices") or []),
                *(m1.get("hk_indices") or []),
                *(m1.get("us_indices") or []),
            ]
            if row.get("change_pct") is not None
        ]
        breadth = m1.get("breadth") or {}
        if changes and sum(changes) / len(changes) > 0 and breadth.get("ratio", 0) >= 1:
            view = "风险偏好有所回升，且指数与市场宽度相互印证"
        elif changes and sum(changes) / len(changes) < 0:
            view = "风险偏好偏弱，市场更接近防御或结构性分化"
        else:
            view = "指数方向分化，当前更适合按行业与风格而非单一指数判断"
        return [view + "。", "", *facts[:4]]
    if section_id in {"indices", "breadth", "global"}:
        return facts[:5]
    if section_id in {"rotation", "style"}:
        rows = [
            f"- {row['name']}：{float(row.get('change_pct') or 0):+.2f}%"
            for row in (m2.get("industry_top20") or [])[:6]
            if row.get("name")
        ]
        return rows or ["行业与风格结论只采用已取得的板块表现，不以热点标题替代市场宽度。"]
    if section_id in {"liquidity"}:
        turnover = sum(
            float(row.get("turnover") or 0)
            for row in [
                *(m1.get("a_indices") or []),
                *(m1.get("hk_indices") or []),
                *(m1.get("us_indices") or []),
            ]
        )
        lines = [f"- 主要指数合计成交额参考为 {turnover / 100_000_000:,.2f} 亿元。"] if turnover else []
        northbound = m1.get("northbound") or {}
        if northbound.get("total_yi") is not None:
            lines.append(f"- 北向资金净流入参考为 {float(northbound['total_yi']):+.2f} 亿元。")
        return lines or ["成交与资金判断以当前可核验口径为边界，不用缺省值推断流动性强弱。"]
    if section_id in {"drivers", "macro"}:
        return [
            "已确认事件、市场一致解释与本报告分析判断分开处理；只有时间顺序和跨资产表现一致时，才提高驱动解释的可信度。",
            *facts[4:7],
        ]
    if section_id in {"sentiment"}:
        return [
            str((modules.get("M3") or {}).get("summary") or "短线情绪以涨跌停、市场宽度与热门方向集中度共同判断。"),
            str((modules.get("M4") or {}).get("summary") or "拥挤风险需结合高位分歧和亏钱效应验证。"),
        ]
    if section_id in {"scenarios"}:
        return [
            "- 延续：指数、市场宽度与成交同步改善，领涨方向保持扩散。",
            "- 震荡：指数稳定但行业轮动加快，成交未形成趋势性变化。",
            "- 反转：指数与市场宽度同时转弱，原领涨方向出现放量回撤。",
        ]
    if section_id in {"watchlist"}:
        return [
            "- 主要指数与上涨家数是否同向。",
            "- 成交额能否支持领涨方向扩散。",
            "- 领涨行业是否出现持续盈利或政策验证。",
            "- 利率、汇率与大宗商品是否对当前风格形成反向压力。",
        ]
    deep_notes = {
        "earnings": "盈利预期必须由公司披露或可追溯预测修正支持，不用指数涨跌反推盈利变化。",
        "history": "历史比较只选取增长、通胀、流动性和估值条件真正相近的阶段。",
    }
    return [deep_notes.get(section_id, "本节只保留能够由跨市场、宏观或资金事实直接支持的判断。")]


def compose_market_report(
    evidence: Any,
    *,
    trade_date: str,
    depth: str,
) -> str:
    modules = evidence.modules if hasattr(evidence, "modules") else evidence.get("modules", {})
    contract = load_report_contract("market", depth)
    lines = ["# 市场行情研究报告", "", f"**数据截止日期**：{trade_date}", ""]
    for section in contract.sections:
        lines.extend([f"## {section.heading}", ""])
        lines.extend(_market_section(modules, section.section_id, depth=depth))
        lines.append("")
    lines.extend([DISCLAIMER, "市场有风险，决策需结合自身目标与风险承受能力。"])
    report = "\n".join(lines).strip()
    violations = contract.validate(report)
    if violations:
        raise ValueError("；".join(violations))
    return build_delivery(report).report


def _portfolio_details(snapshot: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item for item in snapshot.get("details") or [] if isinstance(item, Mapping)]


def compose_portfolio_report(
    snapshot: Mapping[str, Any],
    *,
    depth: str,
) -> str:
    contract = load_report_contract("portfolio", depth)
    details = _portfolio_details(snapshot)
    total = float(snapshot.get("total_value_cny") or 0)
    top3 = snapshot.get("top3_ratio")
    concentration = (
        f"前三大持仓占比约 {float(top3) * 100:.2f}%"
        if top3 is not None
        else "集中度应以完整持仓市值重新计算"
    )
    holdings = [
        f"- {item.get('name') or item.get('symbol')}：市值约 {float(item.get('market_value_cny') or item.get('market_value') or 0):,.2f} 元。"
        for item in details[:10]
    ]
    content = {
        "objective": ["组合评价以收益目标、最大可承受回撤和流动性需求为前提。"],
        "holdings": holdings or ["当前只对已明确授权且可验证的持仓进行分析。"],
        "exposure": ["行业、风格、市场和汇率暴露应穿透到底层资产后判断。"],
        "concentration": [concentration],
        "liquidity": ["流动性风险同时取决于持仓成交深度、退出期限和市场压力。"],
        "drawdown": ["回撤来源需区分市场、行业、个券与集中度贡献。"],
        "rebalance": ["优先处理超出风险预算的集中暴露，再比较替代资产与交易成本。"],
        "attribution": ["因子归因区分市场、行业、风格和个券贡献，不把单期收益视为稳定能力。"],
        "stress": ["压力测试覆盖增长下行、利率上行、流动性收缩和相关性同步上升。"],
        "correlation": ["市场压力下相关性可能显著上升，名义分散不等于风险分散。"],
        "tail": ["尾部风险关注杠杆、流动性、单一行业和无法快速退出的共同冲击。"],
        "thesis": ["每项持仓应有可验证的核心逻辑、催化剂、风险和退出条件。"],
        "alternatives": ["替代方案需在相同风险预算下比较预期回报、相关性、费用与流动性。"],
        "problem": [concentration],
        "action": ["先核对最大集中暴露是否超出组合风险预算。"],
    }
    lines = ["# 投资组合研究报告", "", f"**组合参考市值**：{total:,.2f} 元", ""]
    for section in contract.sections:
        lines.extend([f"## {section.heading}", "", *content.get(section.section_id, []), ""])
    lines.extend([DISCLAIMER, "投资有风险，组合调整需结合完整持仓与个人风险承受能力。"])
    report = "\n".join(lines).strip()
    violations = contract.validate(report)
    if violations:
        raise ValueError("；".join(violations))
    return build_delivery(report).report


def _single_lens_report(
    pack: Mapping[str, Any],
    lens_id: str,
    *,
    opinion: Mapping[str, Any] | None = None,
    heading_level: int = 1,
) -> str:
    definitions = load_lens_definitions()
    definition = definitions[lens_id]
    outline = LENS_REPORT_OUTLINES[lens_id]
    prefix = "#" * heading_level
    section_prefix = "#" * (heading_level + 1)
    lines = [
        f"{prefix} {definition.get('chinese_name')}投资框架",
        "",
        str(definition.get("core_philosophy")),
        "",
    ]
    questions = list(definition.get("key_questions") or [])
    for index, heading in enumerate(outline):
        lines.extend([f"{section_prefix} {heading}", ""])
        if index < len(questions):
            lines.append(f"框架问题：{questions[index]}")
        if index == len(outline) - 2:
            lines.append(f"估值方法：{definition.get('valuation_preference')}")
        preferred_modules = _lens_section_modules(heading)
        preferred_metrics = _lens_section_metrics(heading)
        section_analyses = _translated_lens_analyses(
            opinion or {},
            modules=preferred_modules,
            metrics=preferred_metrics,
            limit=2,
        )
        section_facts = _framework_facts(
            pack,
            modules=preferred_modules
            or tuple((opinion or {}).get("required_modules") or ()),
            limit=2,
        )
        section_support = list(
            dict.fromkeys(
                [
                    *section_analyses,
                    *(fact[2:] if fact.startswith("- ") else fact for fact in section_facts),
                ]
            )
        )
        if section_support:
            lines.append(section_support[0])
        lines.append("")
    lines.extend(
        [
            f"{section_prefix} 风险与证伪",
            "",
            f"风险焦点：{definition.get('risk_focus')}",
            *(f"- {item}" for item in definition.get("red_flags") or []),
            "",
            f"{section_prefix} 框架结论与失效条件",
            "",
            *(f"- {item}" for item in definition.get("output_rules") or []),
            "- 若关键经营、财务、价格或宏观事实与本框架的核心假设持续背离，应重新建立结论。",
        ]
    )
    return "\n".join(lines)


def compose_lens_report(
    pack: Mapping[str, Any],
    *,
    lens_mode: str,
    lenses: Iterable[str],
    opinions: Mapping[str, Mapping[str, Any]] | None = None,
    delivery_budget: str = "full",
) -> str:
    selected = tuple(lenses)
    definitions = load_lens_definitions()
    if not selected and lens_mode == "committee":
        selected = tuple(definitions)
    unknown = [lens_id for lens_id in selected if lens_id not in definitions]
    if unknown:
        raise KeyError(f"unknown lens: {', '.join(unknown)}")
    title = f"# {pack.get('name') or pack.get('symbol')}（{pack.get('symbol')}）专家投资框架研究"
    lines = [title, "", f"**数据截止日期**：{pack.get('trade_date')}", ""]
    if lens_mode == "single":
        lines.append(
            _single_lens_report(
                pack,
                selected[0],
                opinion=(opinions or {}).get(selected[0]),
                heading_level=2,
            )
        )
    elif lens_mode == "parallel":
        for lens_id in selected:
            lines.append(
                _single_lens_report(
                    pack,
                    lens_id,
                    opinion=(opinions or {}).get(lens_id),
                    heading_level=2,
                )
            )
            lines.append("")
        lines.extend(
            [
                "## 共同结论与关键分歧",
                "",
                "各框架共享同一组已验证事实，但对商业质量、周期、趋势和估值的权重不同。",
                *(f"- {definitions[lens_id]['chinese_name']}：{definitions[lens_id]['risk_focus']}" for lens_id in selected),
            ]
        )
    elif lens_mode == "adversarial":
        first, second = selected
        first_def, second_def = definitions[first], definitions[second]
        first_facts = _framework_facts(
            pack,
            modules=tuple(((opinions or {}).get(first) or {}).get("required_modules") or ()),
        )
        second_facts = _framework_facts(
            pack,
            modules=tuple(((opinions or {}).get(second) or {}).get("required_modules") or ()),
        )
        facts = list(dict.fromkeys([*first_facts, *second_facts]))
        first_claims = _translated_lens_claims((opinions or {}).get(first) or {})
        second_claims = _translated_lens_claims((opinions or {}).get(second) or {})
        first_analyses = _translated_lens_analyses((opinions or {}).get(first) or {})
        second_analyses = _translated_lens_analyses((opinions or {}).get(second) or {})
        first_support = list(
            dict.fromkeys(
                [
                    *first_analyses,
                    *first_claims,
                    *(fact[2:] if fact.startswith("- ") else fact for fact in first_facts),
                ]
            )
        )
        second_support = list(
            dict.fromkeys(
                [
                    *second_analyses,
                    *second_claims,
                    *(fact[2:] if fact.startswith("- ") else fact for fact in second_facts),
                ]
            )
        )
        first_scopes = {
            str(item.get("scope")): str(item.get("direction"))
            for item in ((opinions or {}).get(first) or {}).get("publishable_claims") or []
        }
        second_scopes = {
            str(item.get("scope")): str(item.get("direction"))
            for item in ((opinions or {}).get(second) or {}).get("publishable_claims") or []
        }
        conflicts = [
            scope
            for scope in first_scopes.keys() & second_scopes.keys()
            if first_scopes[scope] != second_scopes[scope]
        ]
        lines.extend(
            [
                "## 争议焦点",
                "",
                f"{first_def['chinese_name']}强调“{first_def['core_philosophy']}”；"
                f"{second_def['chinese_name']}强调“{second_def['core_philosophy']}”。",
                "",
                f"## {first_def['chinese_name']}的核心判断",
                "",
                first_def["valuation_preference"],
                *(claim if claim.startswith("- ") else f"- {claim}" for claim in first_support[:5]),
                "",
                f"## {second_def['chinese_name']}的核心判断",
                "",
                second_def["valuation_preference"],
                *(claim if claim.startswith("- ") else f"- {claim}" for claim in second_support[:5]),
                "",
                "## 双方共同认可的事实",
                "",
                *facts,
                "",
                "## 真正存在冲突的假设",
                "",
                *(
                    [
                        f"- 双方对“{_LENS_SCOPE_LABELS.get(scope, '同一投资问题')}”形成相反判断。"
                        for scope in conflicts
                    ]
                    or [
                        f"- {first_def['key_questions'][0]}",
                        f"- {second_def['key_questions'][0]}",
                    ]
                ),
                "",
                "## 哪些证据更支持哪一方",
                "",
                "经营、现金流与估值证据主要检验长期价值框架；"
                "价格、资金、政策和预期变化主要检验动态反馈框架。"
                "当两类证据指向不同时，应按各自持有周期保留分歧，而不是取平均值。",
                "",
                "## 尚未解决的问题",
                "",
                "双方分歧只有在对应关键问题获得新的权威事实后才能收敛，不以折中值替代验证。",
                "",
                "## 决定胜负的未来信号",
                "",
                *(f"- {item}" for item in [first_def["red_flags"][0], second_def["red_flags"][0]]),
                "",
                "## 综合投资含义",
                "",
                "两种框架适用的持有周期和风险容忍度不同；投资者应选择与自身决策周期一致的验证信号。",
            ]
        )
    else:
        names = "、".join(definitions[lens_id]["chinese_name"] for lens_id in selected)
        facts = _framework_facts(pack)
        lines.extend(
            [
                "## 投资问题与研究范围",
                "",
                f"本次由 {names} 从各自投资框架审视同一组公开事实。",
                "",
                "## 投委会核心结论",
                "",
                _general_conclusion(pack, "fund" if pack.get("asset_type") == "fund" else "company"),
                "",
                "## 主要共识",
                "",
                *facts,
                "",
                "## 关键分歧",
                "",
                *(f"- {definitions[lens_id]['chinese_name']}：{definitions[lens_id]['valuation_preference']}" for lens_id in selected),
                "",
                "## 最有力的多方证据",
                "",
                *facts,
                "",
                "## 最有力的反方证据",
                "",
                *(f"- {definitions[lens_id]['red_flags'][0]}" for lens_id in selected[:6]),
                "",
                "## 估值与情景",
                "",
                "估值只采用当前证据可复算的方法，并分别检验悲观、基准与乐观假设。",
                "",
                "## 风险审查",
                "",
                *(f"- {definitions[lens_id]['risk_focus']}" for lens_id in selected[:6]),
                "",
                "## 决策与行动条件",
                "",
                "只有核心逻辑、价格补偿和组合风险同时满足时，才进入个性化行动评估。",
                "",
                "## 结论失效条件",
                "",
                "关键经营、财务、价格或宏观事实持续背离当前共识时，本轮结论失效并需重新研究。",
            ]
        )
    if delivery_budget == "concise":
        lines.append("\n以上为完整专家框架的精简交付，未改变其问题定义与证据门槛。")
    lines.extend(["", DISCLAIMER, "投资有风险，决策需结合自身目标与风险承受能力。"])
    return build_delivery("\n".join(lines)).report
