"""Evidence-gap driven query planning and bounded mode budgets."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import AcquisitionBudget, EvidenceQuery

MODE_BUDGETS = {
    "quick": AcquisitionBudget(max_queries=3, max_documents=5),
    "standard": AcquisitionBudget(max_queries=8, max_documents=20),
    "deep": AcquisitionBudget(max_queries=20, max_documents=50),
    "lens": AcquisitionBudget(max_queries=20, max_documents=50),
}


def budget_for(mode: str) -> AcquisitionBudget:
    try:
        return MODE_BUDGETS[mode]
    except KeyError as exc:
        raise ValueError(f"unsupported evidence mode: {mode}") from exc


def plan_queries(
    requests: Iterable[dict[str, Any]],
    *,
    trade_date: str,
    mode: str,
) -> tuple[EvidenceQuery, ...]:
    budget = budget_for(mode)
    result: list[EvidenceQuery] = []
    for request in requests:
        query = str(request.get("query") or "").strip()
        module = str(request.get("module") or "").strip()
        if not query or not module:
            continue
        topics = "、".join(str(item) for item in request.get("topics") or [])
        result.append(
            EvidenceQuery(
                module=module,
                research_question=topics or query,
                query=query,
                preferred_domains=tuple(
                    str(item)
                    for item in request.get("preferred_domains") or []
                    if "." in str(item)
                ),
                trade_date=trade_date,
            )
        )
        if len(result) >= budget.max_queries:
            break
    return tuple(result)
