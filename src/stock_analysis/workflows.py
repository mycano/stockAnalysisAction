"""User-facing scenario workflows over deterministic Evidence Packs."""

from __future__ import annotations

from typing import Any

from .company_evidence import build_company_evidence
from .research_reports import compose_general_report


def build_stock_review(symbol: str, trade_date: str) -> dict[str, Any]:
    return build_company_evidence(symbol, trade_date)


def render_stock_review(pack: dict[str, Any], title: str = "公司研究") -> str:
    del title
    return compose_general_report(pack, scene="company", depth="quick")


def render_price_move(
    pack: dict[str, Any],
    *,
    window_type: str = "single-session",
    start_date: str | None = None,
    event: str | None = None,
    depth: str = "standard",
) -> str:
    del window_type, start_date, event
    return compose_general_report(pack, scene="price_move", depth=depth)


def render_earnings_review(pack: dict[str, Any], *, depth: str = "standard") -> str:
    return compose_general_report(pack, scene="earnings", depth=depth)
