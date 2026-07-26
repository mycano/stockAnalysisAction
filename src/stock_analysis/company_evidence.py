"""Company-level Evidence Pack built from deterministic public-market inputs.

The market M1-M6 pack answers what happened in the market.  This module keeps
company research separate so an Agent cannot mistake a market proxy for a
company fact.  Empty sections are explicit evidence gaps, never positive data.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .calculators import market_cap
from .execution_costs import build_execution_cost_model
from .expectations import build_expectation_model
from .external_evidence import ExternalEvidencePlane, build_default_plane
from .external_evidence.planner import plan_queries
from .futu_public import fetch_futu_public_pulse
from .global_markets import fetch_yahoo_financials
from .integrations import (
    fetch_a_share_financial_snapshot,
    fetch_a_share_order_book_snapshot,
    fetch_a_share_price_volume,
    fetch_company_disclosures,
    fetch_global_price_volume,
    fetch_jp_kr_disclosures,
    fetch_jp_kr_financial_snapshot,
    fetch_single_quote,
)
from .lens_engine import load_lens_definitions, resolve_lens_ids
from .normalize import normalize_code
from .primary_disclosures import load_issuer_primary_facts
from .research_claims import build_evidence_integrity_audit
from .sec_filings import fetch_sec_financials
from .source_outcome import capture_source

COMPANY_MODULES = {
    "C1": "商业质量",
    "C2": "财务质量",
    "C3": "增长质量",
    "C4": "护城河证据",
    "C5": "管理层与资本配置",
    "C6": "估值与安全边际",
    "C7": "风险与反证",
    "C8": "催化剂与论文跟踪",
}

DEEP_PEER_UNIVERSES = {
    "600519": ("000858", "000568", "600809"),
    "300750": ("300014", "002460", "300207"),
    "603986": ("300223", "688018", "688385"),
}
def _issuer_primary_facts(symbol: str, trade_date: str) -> dict[str, list[dict[str, Any]]]:
    """Extract verified issuer facts through the generic catalog-driven PDF adapter."""

    return load_issuer_primary_facts(normalize_code(symbol), trade_date)


def _market_for(symbol: str, quote_market: str) -> str:
    if quote_market:
        return quote_market
    normalized = normalize_code(symbol)
    if normalized.endswith(".HK"):
        return "hk"
    if normalized.endswith(".T"):
        return "jp"
    if normalized.endswith((".KS", ".KQ")):
        return "kr"
    return "a" if normalized.isdigit() else "us"


def _financial_facts(financials: dict[str, Any]) -> list[dict[str, Any]]:
    periods = financials.get("periods") or []
    if not periods:
        return []
    latest = _latest_material_period(periods)
    fact_keys = (
        "revenue",
        "gross_profit",
        "operating_profit",
        "parent_netprofit",
        "parent_net_profit",
        "total_assets",
        "total_liabilities",
        "stockholders_equity",
        "total_debt",
        "roe_weighted",
        "gross_margin",
        "basic_eps",
        "bps",
        "debt_asset_ratio",
        "operating_cash_flow",
        "free_cash_flow_lite",
        "capital_expenditure",
        "cash_dividends_paid",
        "share_repurchases",
        "total_shares",
        "shares_outstanding",
        "issued_shares",
        "net_cash_invest",
        "net_cash_finance",
    )
    facts = []
    for key in fact_keys:
        value = latest.get(key)
        if value is None:
            continue
        facts.append(
            {
                "metric": key,
                "period": latest.get("report_date") or latest.get("period") or "unknown",
                "value": value,
                "currency": latest.get("_currency") or "CNY",
                "accounting_basis": "reported",
                "scope": "consolidated",
                "source_type": latest.get("_source_type") or "structured_public_disclosure",
                "source": latest.get("_source") or "eastmoney_datacenter",
                "url": latest.get("_source_url"),
                "confidence": (
                    "conditional" if latest.get("publication_date_status") == "missing"
                    else "primary" if latest.get("_source_type") == "regulator_primary_xbrl"
                    else "secondary"
                ),
                "notice_date": latest.get("notice_date"),
            }
        )
    return facts


def _period_fact(metric: str, value: Any, period: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "metric": metric,
        "period": period.get("report_date") or period.get("period_label") or "unknown",
        "value": value,
        "currency": period.get("_currency") or "CNY",
        "accounting_basis": "reported",
        "scope": "consolidated",
        "source_type": period.get("_source_type") or "structured_public_disclosure",
        "source": period.get("_source") or "eastmoney_datacenter",
        "url": period.get("_source_url"),
        "confidence": (
            "conditional" if period.get("publication_date_status") == "missing"
            else "primary" if period.get("_source_type") == "regulator_primary_xbrl"
            else "secondary"
        ),
        "notice_date": period.get("notice_date"),
        **extra,
    }


def _growth_facts(financials: dict[str, Any]) -> list[dict[str, Any]]:
    periods = financials.get("periods") or []
    if not periods:
        return []
    latest = _latest_material_period(periods)
    latest_label = str(latest.get("period_label") or "")
    prior_label = latest_label.replace(str(latest.get("report_date") or "")[:4], str(int(str(latest.get("report_date"))[:4]) - 1), 1)
    prior = next((row for row in periods[1:] if row.get("period_label") == prior_label), None)
    result = []
    for metric in ("revenue", "parent_net_profit"):
        value = latest.get(metric)
        if value is not None:
            result.append(_period_fact(metric, value, latest))
        prior_value = prior.get(metric) if prior else None
        if value is not None and prior_value not in (None, 0):
            result.append(
                _period_fact(
                    f"{metric}_yoy_pct",
                    (float(value) / float(prior_value) - 1) * 100,
                    latest,
                    source_type="derived_from_structured_public_disclosure",
                    confidence="conditional",
                    comparison_period=prior.get("report_date"),
                )
            )
    return result


def _valuation_facts(financials: dict[str, Any], quote_fact: dict[str, Any]) -> list[dict[str, Any]]:
    price = quote_fact.get("value")
    if price is None:
        return []
    annual = next(
        (row for row in financials.get("periods") or [] if str(row.get("period_label") or "").endswith("FY")),
        None,
    )
    if not annual:
        return []
    eps = annual.get("basic_eps")
    bps = annual.get("bps")
    result = []
    ttm_eps, ttm_period = _ttm_eps(financials)
    if ttm_eps not in (None, 0):
        result.append(
            _period_fact(
                "pe_ttm",
                float(price) / float(ttm_eps),
                {**annual, "report_date": quote_fact.get("period") or ttm_period},
                source_type="derived_valuation",
                confidence="conditional",
                formula="market_quote / derived_ttm_eps",
                calculation_basis="latest_fiscal_year_eps + latest_interim_eps - prior_comparable_interim_eps",
            )
        )
        for multiple in (15, 18, 22):
            result.append(
                _period_fact(
                    f"scenario_price_{multiple}x_pe",
                    float(ttm_eps) * multiple,
                    {**annual, "report_date": quote_fact.get("period") or ttm_period},
                    source_type="derived_valuation",
                    confidence="conditional",
                    formula=f"derived_ttm_eps * {multiple}",
                    calculation_basis="latest_fiscal_year_eps + latest_interim_eps - prior_comparable_interim_eps",
                )
            )
    if eps not in (None, 0):
        result.append(
            _period_fact(
                "pe_static_proxy",
                float(price) / float(eps),
                annual,
                source_type="derived_valuation",
                confidence="conditional",
                formula="market_quote / latest_disclosed_fiscal_year_basic_eps",
            )
        )
        if ttm_eps in (None, 0):
            for multiple in (15, 18, 22):
                result.append(
                    _period_fact(
                        f"scenario_price_{multiple}x_pe",
                        float(eps) * multiple,
                        annual,
                        source_type="derived_valuation",
                        confidence="conditional",
                        formula=f"latest_disclosed_fiscal_year_basic_eps * {multiple}",
                    )
                )
    if bps not in (None, 0):
        result.append(
            _period_fact(
                "pb_reported_proxy",
                float(price) / float(bps),
                annual,
                source_type="derived_valuation",
                confidence="conditional",
                formula="market_quote / latest_disclosed_fiscal_year_bps",
            )
        )
    return result


def _ttm_eps(financials: dict[str, Any]) -> tuple[float | None, str | None]:
    """Derive a trailing-twelve-month EPS from comparable cumulative periods."""

    periods = financials.get("periods") or []
    annual = next(
        (row for row in periods if str(row.get("period_label") or "").endswith("FY")),
        None,
    )
    if not annual or annual.get("basic_eps") in (None, 0):
        return None, None
    latest = periods[0] if periods else annual
    latest_label = str(latest.get("period_label") or "")
    if latest is annual or latest_label.endswith("FY"):
        return float(annual["basic_eps"]), str(annual.get("report_date") or "")
    latest_year = str(latest.get("report_date") or "")[:4]
    if not latest_year.isdigit() or latest.get("basic_eps") is None:
        return float(annual["basic_eps"]), str(annual.get("report_date") or "")
    prior_label = latest_label.replace(latest_year, str(int(latest_year) - 1), 1)
    prior = next(
        (row for row in periods[1:] if str(row.get("period_label") or "") == prior_label),
        None,
    )
    if not prior or prior.get("basic_eps") is None:
        return float(annual["basic_eps"]), str(annual.get("report_date") or "")
    ttm_eps = float(annual["basic_eps"]) + float(latest["basic_eps"]) - float(prior["basic_eps"])
    if ttm_eps <= 0:
        return None, None
    return ttm_eps, str(latest.get("report_date") or annual.get("report_date") or "")


def _business_quality_facts(financials: dict[str, Any]) -> list[dict[str, Any]]:
    periods = financials.get("periods") or []
    if not periods:
        return []
    latest = _latest_material_period(periods)
    revenue = latest.get("revenue")
    profit = latest.get("parent_net_profit")
    cash_flow = latest.get("operating_cash_flow")
    result = []
    if revenue not in (None, 0) and profit is not None:
        result.append(_period_fact(
            "parent_net_margin_pct", float(profit) / float(revenue) * 100, latest,
            source_type="derived_business_quality", confidence="conditional",
            formula="parent_net_profit / revenue",
        ))
    if profit not in (None, 0) and cash_flow is not None:
        result.append(_period_fact(
            "operating_cash_conversion_pct", float(cash_flow) / float(profit) * 100, latest,
            source_type="derived_business_quality", confidence="conditional",
            formula="operating_cash_flow / parent_net_profit",
        ))
    return result


def _moat_proxy_facts(financials: dict[str, Any]) -> list[dict[str, Any]]:
    annual = [
        row for row in financials.get("periods") or []
        if str(row.get("period_label") or "").endswith("FY")
    ]
    margins = [float(row["gross_margin"]) for row in annual if row.get("gross_margin") is not None]
    if not margins:
        return []
    latest = annual[0]
    result = [_period_fact(
        "annual_gross_margin_pct", margins[0], latest,
        source_type="observable_moat_proxy", confidence="conditional",
        interpretation="持续高毛利可作为定价权代理，但不能单独证明品牌或竞争优势",
    )]
    if len(margins) >= 2:
        result.append(_period_fact(
            "annual_gross_margin_range_pct", max(margins) - min(margins), latest,
            source_type="observable_moat_proxy", confidence="conditional",
            sample_size=len(margins),
            formula="max(annual_gross_margin) - min(annual_gross_margin)",
        ))
    return result


def _disclosure_facts(financials: dict[str, Any]) -> list[dict[str, Any]]:
    facts = []
    for key, disclosure_type in (("forecasts", "earnings_forecast"), ("earnings_flash", "earnings_flash")):
        for row in (financials.get(key) or {}).get("rows") or []:
            facts.append(
                {
                    "title": row.get("title") or disclosure_type,
                    "type": row.get("type") or disclosure_type,
                    "period": row.get("report_date"),
                    "published_at": row.get("notice_date"),
                    "summary": row.get("summary"),
                    "lower": row.get("lower"),
                    "upper": row.get("upper"),
                    "source": "eastmoney_datacenter",
                    "source_type": "structured_public_disclosure",
                    "confidence": "secondary",
                    "category": "financial_disclosure",
                }
            )
    return facts


def _evidence_id(module: str, item: dict[str, Any]) -> str:
    canonical = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"{module}:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"


def _identify_evidence(sections: dict[str, dict[str, Any]]) -> None:
    by_metric: dict[str, list[dict[str, Any]]] = {}
    for module, section in sections.items():
        identified = []
        for raw in section["evidence"]:
            item = dict(raw)
            if not item.get("validation_status"):
                item["validation_status"] = (
                    "conditional"
                    if item.get("confidence") == "conditional"
                    or item.get("source_type") in {"public_announcement_index", "news_sample"}
                    else "accepted"
                )
            item["evidence_id"] = _evidence_id(module, item)
            identified.append(item)
            if item.get("metric"):
                by_metric.setdefault(str(item["metric"]), []).append(item)
        section["evidence"] = identified
    for section in sections.values():
        for item in section["evidence"]:
            input_metrics = item.pop("calculation_input_metrics", None)
            if not input_metrics:
                continue
            item["calculation_input_evidence_ids"] = [
                by_metric[str(metric)][-1]["evidence_id"]
                for metric in input_metrics
                if by_metric.get(str(metric))
            ]


def _section(available: bool, evidence: list[dict[str, Any]], gaps: list[str], **extra: Any) -> dict[str, Any]:
    return {"available": available, "evidence": evidence, "gaps": gaps, **extra}


def _latest_material_period(periods: list[dict[str, Any]]) -> dict[str, Any]:
    material = {
        "revenue", "parent_net_profit", "operating_cash_flow", "total_assets", "gross_profit",
    }
    return next((row for row in periods if len(material & set(row)) >= 2), periods[0])


def derive_market_cap_fact(
    quote_fact: dict[str, Any],
    share_facts: list[dict[str, Any]],
    *,
    trade_date: str,
) -> dict[str, Any] | None:
    """Derive market cap only from a valid price and disclosed share count."""

    price = quote_fact.get("value")
    price_period = "".join(character for character in str(quote_fact.get("period") or "") if character.isdigit())[:8]
    if price is None or not price_period or price_period > trade_date:
        return None
    candidates = [
        item
        for item in share_facts
        if item.get("metric") in {"total_shares", "shares_outstanding", "issued_shares"}
        and item.get("value") not in (None, 0)
    ]
    dated_candidates = []
    for shares in candidates:
        disclosed = "".join(
            character
            for character in str(
                shares.get("published_at")
                or shares.get("notice_date")
                or shares.get("period")
                or ""
            )
            if character.isdigit()
        )[:8]
        if not disclosed or disclosed > trade_date:
            continue
        dated_candidates.append((disclosed, shares))
    for disclosed, shares in sorted(dated_candidates, key=lambda item: item[0], reverse=True):
        derived = market_cap(price, shares["value"])
        if derived is None or derived <= Decimal("0"):
            continue
        share_metric = str(shares["metric"])
        return {
            "metric": "total_market_cap",
            "period": price_period,
            "value": float(derived),
            "currency": quote_fact.get("currency"),
            "unit": quote_fact.get("currency"),
            "source": "deterministic_derived_metric",
            "source_type": "derived_valuation",
            "confidence": "conditional",
            "validation_status": "accepted",
            "formula": f"market_quote * {share_metric}",
            "calculation_input_metrics": ["market_quote", share_metric],
            "share_count_asof": disclosed,
            "derivation_status": "derived_verified",
        }
    return None


def _financial_quality_gaps(financials: dict[str, Any]) -> list[str]:
    periods = financials.get("periods") or []
    if not periods:
        return ["财务披露字段不足"]
    latest = _latest_material_period(periods)
    required = {
        "revenue": "利润表收入",
        "parent_net_profit": "净利润",
        "total_assets": "总资产",
        "total_liabilities": "总负债",
        "operating_cash_flow": "经营现金流",
        "capital_expenditure": "资本开支",
        "free_cash_flow_lite": "自由现金流-lite",
    }
    missing = [label for metric, label in required.items() if latest.get(metric) is None]
    annual_cash_years = sum(
        str(row.get("period_label") or "").endswith("FY") and row.get("operating_cash_flow") is not None
        for row in periods
    )
    gaps = [f"最新期仍缺：{', '.join(missing)}"] if missing else []
    if annual_cash_years < 3:
        gaps.append(f"长期现金流仅覆盖 {annual_cash_years} 个年度，至少 3 年后才可评估稳定性")
    if financials.get("_source_type") == "secondary_aggregated_financial":
        gaps.append("聚合财务缺少可验证公告日期，需发行人/交易所原文复核")
    return gaps


def build_company_evidence(
    symbol: str,
    trade_date: str,
    expectations: dict[str, Any] | None = None,
    reached_primary: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Create a C1-C8 pack without making investment assertions.

    A-share financial facts retain their structured disclosure route. US facts
    prefer SEC XBRL. Other global aggregator rows remain conditional until an
    issuer-primary filing supplies a publication date.
    """

    quote_outcome = capture_source("market_quote", lambda: fetch_single_quote(symbol, trade_date), None)
    quote = quote_outcome.value
    normalized = normalize_code(quote.symbol if quote else symbol)
    market = _market_for(normalized, quote.market if quote else "")
    financial_source = "eastmoney_datacenter" if market == "a" else f"{market}_public_financials"
    financials_outcome = capture_source(
        financial_source,
        lambda: (
            fetch_a_share_financial_snapshot(normalized, trade_date)
            if market == "a"
            else fetch_sec_financials(normalized, trade_date)
            if market == "us"
            else fetch_jp_kr_financial_snapshot(normalized, trade_date)
            if market in {"jp", "kr"}
            else fetch_yahoo_financials(normalized, trade_date)
            if market == "hk"
            else {}
        ),
        {},
    )
    financials = financials_outcome.value
    price_volume_outcome = capture_source(
        "price_volume",
        lambda: (
            fetch_a_share_price_volume(normalized, trade_date)
            if market == "a"
            else fetch_global_price_volume(normalized, trade_date)
            if market in {"hk", "us", "jp", "kr"}
            else {}
        ),
        {},
    )
    price_volume = price_volume_outcome.value
    microstructure_outcome = capture_source(
        "order_book",
        lambda: (
            fetch_a_share_order_book_snapshot(normalized, trade_date)
            if market == "a"
            else {"available": False, "symbol": normalized, "reason": "market-specific order book not connected"}
        ),
        lambda exc: {"available": False, "symbol": normalized, "reason": str(exc)},
    )
    microstructure = microstructure_outcome.value
    execution_cost_model = build_execution_cost_model(
        symbol=normalized,
        price_volume=price_volume,
        microstructure=microstructure,
        market=market,
        currency=(quote.currency if quote else price_volume.get("currency")),
    )
    pulse: dict[str, Any] = {}
    pulse_outcome = None
    if quote and quote.name:
        pulse_outcome = capture_source(
            "futu_public",
            lambda: fetch_futu_public_pulse(normalized, quote.name, market),
            lambda exc: {"available": False, "reason": str(exc)},
        )
        pulse = pulse_outcome.value
    disclosures_outcome = capture_source(
        "Futu 免登录公告搜索",
        lambda: (
            fetch_jp_kr_disclosures(normalized, trade_date)
            if market in {"jp", "kr"}
            else fetch_company_disclosures(normalized, quote.name if quote else normalized, trade_date)
        ),
        lambda exc: {
            "available": False,
            "rows": [],
            "reason": str(exc),
            "_source": "Futu 免登录公告搜索",
        },
    )
    disclosures = disclosures_outcome.value

    facts = _financial_facts(financials)
    issuer_primary = _issuer_primary_facts(normalized, trade_date)
    for module, items in (reached_primary or {}).items():
        if module in issuer_primary:
            issuer_primary[module].extend(dict(item) for item in items)
    primary_disclosures = _disclosure_facts(financials)
    quote_fact = {
        "metric": "market_quote",
        "period": quote.trade_date if quote else trade_date,
        "value": quote.price if quote else None,
        "currency": quote.currency if quote else None,
        "source_type": "market_quote",
        "source": quote.source if quote else None,
        "confidence": "primary" if quote and quote.price is not None else "unavailable",
    }
    quality_metrics = {
        "roe_weighted", "gross_margin", "operating_cash_flow", "free_cash_flow_lite",
        "debt_asset_ratio", "total_assets", "total_liabilities", "stockholders_equity",
        "total_debt", "capital_expenditure",
    }
    quality_evidence = [item for item in facts if item["metric"] in quality_metrics]
    for period in financials.get("periods") or []:
        if not str(period.get("period_label") or "").endswith("FY"):
            continue
        for metric in ("operating_cash_flow", "capital_expenditure", "free_cash_flow_lite"):
            if period.get(metric) is not None:
                quality_evidence.append(_period_fact(metric, period[metric], period, history_role="long_term_cash_flow"))
    business_evidence = _business_quality_facts(financials) + issuer_primary["C1"]
    moat_evidence = _moat_proxy_facts(financials) + issuer_primary["C4"]
    growth_evidence = _growth_facts(financials)
    valuation_evidence = [quote_fact] if quote_fact["value"] is not None else []
    share_facts = [
        item
        for item in [
            *facts,
            *(issuer_primary.get("C2") or []),
            *(issuer_primary.get("C5") or []),
        ]
        if item.get("metric") in {"total_shares", "shares_outstanding", "issued_shares"}
    ]
    valuation_evidence.extend(dict(item) for item in share_facts)
    for metric, value in (
        ("pe_ttm", quote.pe if quote else None),
        ("pb", quote.pb if quote else None),
        ("total_market_cap", quote.total_market_cap if quote else None),
        ("float_market_cap", quote.float_market_cap if quote else None),
    ):
        if value is None:
            continue
        valuation_evidence.append(
            {
                "metric": metric,
                "period": quote.trade_date or trade_date,
                "value": value,
                "currency": quote.currency if "market_cap" in metric else None,
                "source": quote.source,
                "source_type": "market_valuation_snapshot",
                "confidence": "primary",
            }
        )
    if quote and quote.total_market_cap is None:
        derived_market_cap = derive_market_cap_fact(
            quote_fact,
            share_facts,
            trade_date=trade_date,
        )
        if derived_market_cap is not None:
            valuation_evidence.append(derived_market_cap)
    valuation_evidence.extend(_valuation_facts(financials, quote_fact))
    expectation_model = build_expectation_model(
        (
            quote.total_market_cap
            if quote and quote.total_market_cap is not None
            else next(
                (
                    item["value"]
                    for item in valuation_evidence
                    if item.get("metric") == "total_market_cap"
                ),
                None,
            )
        ),
        expectations,
    )
    for row in expectation_model.get("market_implied") or []:
        multiple = row["multiple"]
        suffix = str(int(multiple)) if float(multiple).is_integer() else str(multiple).replace(".", "_")
        valuation_evidence.append({
            "metric": f"implied_net_profit_{suffix}x",
            "period": expectation_model.get("valuation_year") or "valuation_horizon_not_supplied",
            "value": row["implied_net_profit"],
            "currency": expectation_model.get("currency") or (quote.currency if quote else None),
            "source": "market_cap_expectations_bridge",
            "source_type": "derived_market_implied_expectation",
            "confidence": "conditional",
            "formula": "total_market_cap / assumed_valuation_multiple",
        })
    forward_model = expectation_model.get("forward_model") or {}
    for index, item in enumerate(forward_model.get("product_lines") or [], start=1):
        slug = "".join(char.lower() if char.isalnum() else "_" for char in str(item["name"])).strip("_") or str(index)
        for field in ("revenue", "net_profit"):
            valuation_evidence.append({
                "metric": f"forward_product_{slug}_{field}",
                "period": expectation_model.get("valuation_year") or "valuation_horizon_not_supplied",
                "value": item[field],
                "currency": expectation_model.get("currency"),
                "source": "user_supplied_research_assumption",
                "source_type": "derived_forward_product_model",
                "confidence": "conditional",
                "formula": item["formula"],
            })
    for index, item in enumerate(forward_model.get("segments") or [], start=1):
        slug = "".join(char.lower() if char.isalnum() else "_" for char in str(item["name"])).strip("_") or str(index)
        valuation_evidence.append({
            "metric": f"forward_segment_{slug}_value",
            "period": expectation_model.get("valuation_year") or "valuation_horizon_not_supplied",
            "value": item["value"],
            "currency": expectation_model.get("currency"),
            "source": "user_supplied_research_assumption",
            "source_type": "derived_forward_sotp",
            "confidence": "conditional",
            "formula": item["formula"],
        })
    bridge = expectation_model.get("sotp_bridge") or {}
    if forward_model.get("forward_net_profit") is not None:
        valuation_evidence.append({
            "metric": "forward_net_profit",
            "period": expectation_model.get("valuation_year") or "valuation_horizon_not_supplied",
            "value": forward_model["forward_net_profit"],
            "currency": expectation_model.get("currency"),
            "source": "user_supplied_research_assumption",
            "source_type": "forward_valuation_assumption",
            "confidence": "conditional",
        })
    if forward_model.get("segments"):
        valuation_evidence.append({
            "metric": "sotp_residual_value",
            "period": expectation_model.get("valuation_year") or "valuation_horizon_not_supplied",
            "value": bridge.get("residual_value"),
            "currency": expectation_model.get("currency"),
            "source": "market_cap_expectations_bridge",
            "source_type": "derived_forward_reverse_reconciliation",
            "confidence": "conditional",
            "formula": bridge.get("formula"),
            "reconciliation_status": bridge.get("status"),
        })
    for row in expectation_model.get("expectation_gap") or []:
        multiple = row["multiple"]
        suffix = str(int(multiple)) if float(multiple).is_integer() else str(multiple).replace(".", "_")
        valuation_evidence.append({
            "metric": f"expectation_gap_{suffix}x",
            "period": expectation_model.get("valuation_year") or "valuation_horizon_not_supplied",
            "value": row["gap"],
            "currency": expectation_model.get("currency"),
            "source": "forward_reverse_expectations_bridge",
            "source_type": "derived_forward_reverse_reconciliation",
            "confidence": "conditional",
            "formula": "forward_net_profit - market_implied_net_profit",
        })
    option_value = expectation_model.get("option_value") or {}
    for field in ("required_net_profit", "required_revenue"):
        if option_value.get(field) is None:
            continue
        valuation_evidence.append({
            "metric": f"option_{field}",
            "period": expectation_model.get("valuation_year") or "valuation_horizon_not_supplied",
            "value": option_value[field],
            "currency": expectation_model.get("currency"),
            "source": "market_cap_expectations_bridge",
            "source_type": "derived_option_value_requirement",
            "confidence": "conditional",
            "formula": option_value.get("formula"),
        })
    price_metrics = (price_volume.get("metrics") or {}) if price_volume else {}
    execution_evidence = [
        {
            "metric": "execution_cost_model_status",
            "value": execution_cost_model.get("model_status"),
            "source": "公开盘口、日线成交额与交易成本情景模型",
            "source_type": "execution_scenario",
            "confidence": "conditional",
        }
    ]
    for scenario in execution_cost_model.get("scenarios") or []:
        order_value = int(scenario["order_value_cny"] / 10_000)
        execution_evidence.append({
            "metric": f"execution_round_trip_cost_{order_value}w_bps",
            "value": scenario["round_trip_cost_bps"],
            "source": "公开盘口、20日成交额与平方根冲击模型",
            "source_type": "execution_scenario",
            "confidence": "conditional",
        })
    event_evidence = []
    if pulse.get("event_title"):
        event_evidence.append(
            {
                "title": pulse.get("event_title"),
                "url": pulse.get("evidence_url"),
                "tone": pulse.get("news_tone"),
                "sample_count": pulse.get("news_count"),
                "source": "futu_public",
                "source_type": "news_sample",
            }
        )
    disclosure_rows = [dict(row) for row in disclosures.get("rows") or []]
    capital_allocation = [row for row in disclosure_rows if row.get("category") == "capital_allocation"]
    governance = [row for row in disclosure_rows if row.get("category") == "governance"]
    annual_period = next(
        (row for row in financials.get("periods") or [] if str(row.get("period_label") or "").endswith("FY")),
        {},
    )
    financing_facts = [
        _period_fact(metric, annual_period[metric], annual_period)
        for metric in (
            "net_cash_invest", "net_cash_finance", "capital_expenditure",
            "cash_dividends_paid", "share_repurchases",
        )
        if annual_period.get(metric) is not None
    ]
    management_evidence = governance + capital_allocation + financing_facts + issuer_primary["C5"]
    monitoring_evidence = [
        {
            "metric": item["metric"],
            "value": item.get("baseline"),
            "period": item.get("next_check_date") or trade_date,
            "view_change_condition": item["view_change_condition"],
            "source": item.get("source") or "user_supplied_research_assumption",
            "source_type": "thesis_monitoring_trigger",
            "confidence": "conditional",
        }
        for item in expectation_model.get("monitoring") or []
    ]
    financial_gap = (
        "免费免登录聚合财务缺少可验证的公告日期；需公司 IR、TDnet、DART 或其他一手原文补齐"
        if market in {"jp", "kr"}
        else "港股免费聚合三表缺少公告日期；需 HKEXnews 或公司 IR 原文确认"
        if market == "hk"
        else "SEC Company Facts 未返回研究截止日前的可用标准化事实"
        if market == "us"
        else "财务披露字段不足"
    )
    no_management_gap = "尚未接入经核验的管理层、回购、分红、增减持和治理事件源"
    sections = {
        "C1": _section(bool(business_evidence), business_evidence, ["收入分部、客户集中度和渠道经营数据仍需原始披露复核"]),
        "C2": _section(
            bool(quality_evidence),
            quality_evidence,
            _financial_quality_gaps(financials) if quality_evidence else [financial_gap],
        ),
        "C3": _section(bool(growth_evidence or primary_disclosures), growth_evidence + primary_disclosures, [] if growth_evidence or primary_disclosures else [financial_gap]),
        "C4": _section(bool(moat_evidence), moat_evidence, ["毛利率仅为护城河代理，品牌、份额、批价和渠道库存仍需一手经营证据"]),
        "C5": _section(bool(management_evidence), management_evidence, [] if management_evidence else [no_management_gap]),
        "C6": _section(
            len(valuation_evidence) > 1,
            valuation_evidence,
            [
                "市场隐含利润已按估值倍数反推；未提供 expectations 文件时，正向分部模型、SOTP 对账与预期差仍为空"
                if expectation_model.get("status") == "market_implied_only"
                else "历史估值分位和同行比较尚未齐备"
            ],
            expectation_model=expectation_model,
        ),
        "C7": _section(
            bool(price_metrics or event_evidence or governance or issuer_primary["C7"]),
            [{"metric": key, "value": value, "source": price_volume.get("source")} for key, value in price_metrics.items()]
            + execution_evidence
            + event_evidence
            + governance
            + issuer_primary["C7"],
            ["尚未取得可核验的公司级监管、诉讼或治理风险披露"] if not governance else [],
        ),
        "C8": _section(
            bool(event_evidence or disclosure_rows or primary_disclosures or issuer_primary["C8"] or monitoring_evidence),
            event_evidence + disclosure_rows + primary_disclosures + issuer_primary["C8"] + monitoring_evidence,
            ["尚未建立该标的的持久化论文或催化剂日历"] if not event_evidence and not disclosure_rows and not primary_disclosures and not issuer_primary["C8"] and not monitoring_evidence else [],
            monitoring=expectation_model.get("monitoring") or [],
        ),
    }
    _identify_evidence(sections)
    available = [key for key, value in sections.items() if value["available"]]
    missing = [key for key, value in sections.items() if not value["available"]]
    primary_requests = _primary_evidence_requests(sections, market, normalized, quote.name if quote else normalized)
    result = {
        "schema_version": "1.2",
        "symbol": normalized,
        "name": quote.name if quote else normalized,
        "market": market,
        "trade_date": trade_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "quote": quote_fact,
        "financial_facts": facts,
        "financial_history": financials.get("periods") or [],
        "price_volume": price_volume,
        "microstructure": microstructure,
        "execution_cost_model": execution_cost_model,
        "expectation_model": expectation_model,
        "modules": sections,
        "_meta": {
            "available_modules": available,
            "missing_modules": missing,
            "coverage": round(len(available) / len(COMPANY_MODULES) * 100, 1),
            "source_events": [
                quote_outcome.event(available=quote_fact["value"] is not None, source=quote.source if quote else "quote"),
                financials_outcome.event(available=bool(facts)),
                (pulse_outcome.event(available=bool(event_evidence)) if pulse_outcome else {"source": "futu_public", "status": "unavailable"}),
                disclosures_outcome.event(
                    available=bool(disclosure_rows),
                    source=disclosures.get("_source") or "Futu 免登录公告搜索",
                ),
                price_volume_outcome.event(available=bool(price_volume)),
                microstructure_outcome.event(available=bool(microstructure.get("available"))),
                {"source": "issuer_primary_disclosure", "status": "ok" if any(issuer_primary.values()) else "unavailable"},
                {"source": "execution_cost_model", "status": "ok" if execution_cost_model.get("available") else "unavailable"},
                {"source": "expectations_model", "status": expectation_model.get("status")},
                {
                    "source": "builtin_external_evidence",
                    "status": "recommended" if primary_requests else "not_needed",
                    "reason": "stock-analysis can search and read bounded public sources; only validated originals become primary evidence",
                },
            ],
            "primary_evidence_requests": primary_requests,
        },
    }
    result["_meta"].update(
        build_evidence_integrity_audit(
            sections,
            requested_symbol=normalize_code(symbol),
            resolved_symbol=(
                quote.symbol
                if quote
                else financials.get("symbol")
                or price_volume.get("symbol")
                or disclosures.get("symbol")
                or (
                    normalized
                    if any(section.get("evidence") for section in sections.values())
                    else None
                )
            ),
            trade_date=trade_date,
        )
    )
    from .company_lens import freeze_company_evidence

    result["_meta"]["evidence_snapshot_id"] = freeze_company_evidence(result)["snapshot_id"]
    return result


def enrich_company_evidence_from_web(
    pack: dict[str, Any],
    *,
    mode: str = "standard",
    lens_ids: tuple[str, ...] | list[str] | None = None,
    plane: ExternalEvidencePlane | None = None,
) -> dict[str, Any]:
    """Collect bounded public documents for explicit Company Evidence gaps."""

    enriched = copy.deepcopy(pack)
    requests = list((enriched.get("_meta") or {}).get("primary_evidence_requests") or [])
    lens_requests = _lens_evidence_requests(enriched, tuple(lens_ids or ()))
    requests.extend(lens_requests)
    queries = plan_queries(requests, trade_date=str(enriched["trade_date"]), mode=mode)
    evidence, events = (plane or build_default_plane()).collect(queries, mode=mode)
    meta = enriched["_meta"]
    meta["external_documents"] = [
        {
            **item.to_internal_dict(),
            "module": item.module,
            "evidence_type": item.evidence_type,
            "document_id": f"doc:{item.content_hash.removeprefix('sha256:')[:20]}",
            "publication_policy": "discovery_only_until_fact_extracted",
        }
        for item in evidence
        if item.module in enriched["modules"]
    ]
    for document in evidence:
        if document.module not in enriched["modules"]:
            continue
        for extracted in document.extracted_facts:
            row = {
                **extracted,
                "source": document.url,
                "source_type": "external_primary_disclosure",
                "published_at": document.published_at,
                "retrieved_at": document.retrieved_at,
                "content_hash": document.content_hash,
                "verification": document.verification,
            }
            row["evidence_id"] = _evidence_id(document.module, row)
            enriched["modules"][document.module]["evidence"].append(row)
            enriched["modules"][document.module]["available"] = True
    meta["lens_evidence_requests"] = lens_requests
    meta["source_events"] = [
        event
        for event in meta.get("source_events") or []
        if event.get("source") != "builtin_external_evidence"
    ]
    meta["source_events"].extend(events)
    meta["available_modules"] = [
        code for code, section in enriched["modules"].items() if section["available"]
    ]
    meta["missing_modules"] = [
        code for code, section in enriched["modules"].items() if not section["available"]
    ]
    meta["coverage"] = round(
        len(meta["available_modules"]) / len(COMPANY_MODULES) * 100,
        1,
    )
    return enriched


def enrich_company_peer_comparison(pack: dict[str, Any]) -> dict[str, Any]:
    """Attach comparable-company facts for Deep reports without polluting core modules."""

    enriched = copy.deepcopy(pack)
    peer_codes = DEEP_PEER_UNIVERSES.get(str(enriched.get("symbol") or ""), ())
    rows: list[dict[str, Any]] = []
    for code in peer_codes:
        quote_outcome = capture_source(
            f"peer_quote:{code}",
            lambda code=code: fetch_single_quote(code, str(enriched["trade_date"])),
            None,
        )
        financial_outcome = capture_source(
            f"peer_financial:{code}",
            lambda code=code: fetch_a_share_financial_snapshot(
                code,
                str(enriched["trade_date"]),
            ),
            {},
        )
        quote = quote_outcome.value
        periods = financial_outcome.value.get("periods") or []
        latest = _latest_material_period(periods) if periods else {}
        if quote is None and not latest:
            continue
        peer_ttm_eps, _ = _ttm_eps(financial_outcome.value)
        derived_pe = (
            float(quote.price) / peer_ttm_eps
            if quote is not None
            and quote.price is not None
            and peer_ttm_eps not in (None, 0)
            else None
        )
        derived_pb = (
            float(quote.price) / float(latest["bps"])
            if quote is not None
            and quote.price is not None
            and latest.get("bps") not in (None, 0)
            else None
        )
        rows.append(
            {
                "symbol": code,
                "name": quote.name if quote else code,
                "period": latest.get("report_date") or latest.get("period") or latest.get("period_label"),
                "revenue": latest.get("revenue"),
                "parent_net_profit": latest.get("parent_net_profit"),
                "roe_weighted": latest.get("roe_weighted"),
                "pe_ttm": quote.pe if quote and quote.pe is not None else derived_pe,
                "pb": quote.pb if quote and quote.pb is not None else derived_pb,
                "sources": [
                    quote.source if quote else None,
                    financial_outcome.value.get("_source"),
                ],
            }
        )
    enriched["_meta"]["peer_comparison"] = rows
    enriched["_meta"]["source_events"].extend(
        {
            "source": f"peer_comparison:{row['symbol']}",
            "status": "ok",
        }
        for row in rows
    )
    return enriched


def _lens_evidence_requests(
    pack: dict[str, Any],
    lens_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Turn explicit expert-framework questions into bounded evidence requests."""

    if not lens_ids:
        return []
    lens_ids = resolve_lens_ids(lens_ids)
    definitions = load_lens_definitions()
    market = str(pack.get("market") or "")
    domains = {
        "a": ["cninfo.com.cn", "sse.com.cn", "szse.cn"],
        "hk": ["hkexnews.hk"],
        "us": ["sec.gov"],
        "jp": ["release.tdnet.info", "edinet-fsa.go.jp"],
        "kr": ["dart.fss.or.kr", "kind.krx.co.kr"],
    }.get(market, [])
    module_by_lens = {
        "buffett": "C1",
        "munger": "C5",
        "duan_yongping": "C1",
        "zhang_kun": "C4",
        "graham": "C6",
        "dalio": "C7",
        "klarman": "C7",
        "lynch": "C3",
        "o_neil": "C7",
        "wood": "C1",
        "soros": "C8",
        "livermore": "C7",
        "minervini": "C7",
        "simons": "C7",
        "feng_liu": "C8",
    }
    requests: list[dict[str, Any]] = []
    for lens_id in lens_ids:
        definition = definitions.get(lens_id)
        if not definition:
            continue
        questions = [str(item) for item in definition.get("key_questions") or []]
        requests.append(
            {
                "module": module_by_lens[lens_id],
                "topics": questions,
                "preferred_domains": domains,
                "query": (
                    f"{pack.get('name') or pack.get('symbol')} {pack.get('symbol')} "
                    f"{questions[0]} 年报 公告"
                ),
                "accepted_sources": ["issuer", "exchange", "regulator"],
            }
        )
    return requests


def _primary_evidence_requests(
    sections: dict[str, dict[str, Any]], market: str, symbol: str, name: str,
) -> list[dict[str, Any]]:
    domains = {
        "a": ["cninfo.com.cn", "sse.com.cn", "szse.cn", "issuer IR"],
        "hk": ["hkexnews.hk", "issuer IR"],
        "us": ["sec.gov", "issuer IR"],
        "jp": ["release.tdnet.info", "disclosure2.edinet-fsa.go.jp", "issuer IR"],
        "kr": ["dart.fss.or.kr", "kind.krx.co.kr", "issuer IR"],
    }.get(market, ["issuer IR", "exchange or regulator"])
    topics = {
        "C1": ["segment revenue", "segment profit", "channel inventory", "demand indicators"],
        "C2": ["three statements", "operating cash flow", "capital expenditure", "free cash flow"],
        "C4": ["market share", "pricing", "wholesale price", "customer retention", "competitive risks"],
        "C5": ["governance", "buyback", "dividend", "capital allocation", "management incentives"],
        "C7": ["risk factors", "regulatory actions", "litigation", "bear case evidence"],
        "C8": ["guidance", "catalysts", "earnings calendar", "thesis disconfirming events"],
    }
    requests_out = []
    for module, wanted in topics.items():
        section = sections[module]
        if module == "C2" and section.get("available") and market in {"a", "us"}:
            continue
        requests_out.append(
            {
                "module": module,
                "topics": wanted,
                "preferred_domains": domains,
                "query": f"{name} {symbol} {' '.join(wanted[:2])} annual report results announcement",
                "cutoff_rule": "published_at must be on or before trade_date",
                "accepted_sources": ["issuer", "exchange", "regulator"],
            }
        )
    return requests_out
