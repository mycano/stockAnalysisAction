"""Portable investment-thesis state with immutable versions and audit events."""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def thesis_dir() -> Path:
    return Path(os.environ.get("STOCK_ANALYSIS_THESIS_DIR", "~/.stock_analysis/theses")).expanduser()


def _safe_symbol(symbol: str) -> str:
    return "".join(char for char in symbol.upper() if char.isalnum() or char in {".", "-"})


def thesis_path(symbol: str) -> Path:
    """Return the compatibility latest pointer; immutable versions live beside it."""
    return thesis_dir() / f"{_safe_symbol(symbol)}.json"


def thesis_history_dir(symbol: str) -> Path:
    return thesis_dir() / f"{_safe_symbol(symbol)}.history"


def _version_number(version: int | str) -> int:
    match = re.fullmatch(r"(?:v|thesis_v)?0*([1-9][0-9]*)", str(version).strip(), re.IGNORECASE)
    if not match:
        raise ValueError("thesis version must be a positive integer")
    return int(match.group(1))


def thesis_version_path(symbol: str, version: int | str) -> Path:
    return thesis_history_dir(symbol) / f"thesis_v{_version_number(version):04d}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _snapshot(company: dict[str, Any]) -> dict[str, Any]:
    evidence = company.get("_meta") or {}
    return {
        "trade_date": company.get("trade_date"),
        "coverage": evidence.get("coverage"),
        "available_modules": evidence.get("available_modules") or [],
        "missing_modules": evidence.get("missing_modules") or [],
    }


def _persist_version(document: dict[str, Any], event_type: str, changes: list[str]) -> Path:
    """Persist a new immutable version, then update the compatibility latest pointer."""
    symbol = str(document["symbol"])
    version = int(document["version"])
    version_path = thesis_version_path(symbol, version)
    if version_path.exists():
        raise FileExistsError(f"thesis version already exists: {version_path}")
    _write_json(version_path, document)

    # Plan §9: every mutation has a separate append-only audit event.
    event = {
        "schema_version": "1.0",
        "event_type": event_type,
        "symbol": symbol,
        "version": version,
        "recorded_at": document["updated_at"],
        "changes": changes,
        "version_path": str(version_path),
    }
    event_path = thesis_history_dir(symbol) / "events" / f"{version:04d}-{event_type}.json"
    if event_path.exists():
        raise FileExistsError(f"thesis audit event already exists: {event_path}")
    _write_json(event_path, event)
    _write_json(thesis_path(symbol), document)
    return thesis_path(symbol)


def create_thesis(company: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    path = thesis_path(str(company["symbol"]))
    if path.exists() or thesis_version_path(str(company["symbol"]), 1).exists():
        raise ValueError("投资论文已存在；请明确选择更新、复核或失效操作")
    created_at = _now()
    evidence = company["_meta"]
    document = {
        "schema_version": "2.0",
        "version": 1,
        "symbol": company["symbol"],
        "name": company.get("name") or company["symbol"],
        "created_at": created_at,
        "updated_at": created_at,
        "status": "evidence_insufficient" if evidence["missing_modules"] else "under_review",
        "thesis": {
            "why_watch": [],
            "core_assumptions": [],
            "supporting_facts": company.get("financial_facts") or [],
            "counter_evidence": [],
            "key_metrics": [fact["metric"] for fact in company.get("financial_facts") or []],
            "invalidation_conditions": [],
            "valuation_conditions": [],
            "next_review": None,
        },
        "evidence_snapshot": _snapshot(company),
    }
    return document, _persist_version(document, "create", ["创建 thesis_v0001"])


def _evidence_changes(previous: dict[str, Any], company: dict[str, Any]) -> list[str]:
    current = company.get("_meta") or {}
    changes: list[str] = []
    if previous.get("trade_date") != company.get("trade_date"):
        changes.append(f"证据日期：{previous.get('trade_date') or '无'} → {company.get('trade_date')}")
    if previous.get("coverage") != current.get("coverage"):
        changes.append(f"证据覆盖：{previous.get('coverage')}% → {current.get('coverage')}%")
    if previous.get("missing_modules") != current.get("missing_modules"):
        changes.append("证据模块可用性发生变化")
    return changes


def _append_version(
    company: dict[str, Any],
    *,
    event_type: str,
    status: str | None = None,
    reason: str | None = None,
) -> tuple[dict[str, Any] | None, Path, list[str]]:
    path = thesis_path(str(company["symbol"]))
    if not path.exists():
        return None, path, ["尚未创建投资论文，请先明确创建一份新论文"]
    previous_document = json.loads(path.read_text(encoding="utf-8"))
    previous_version = int(previous_document.get("version") or 1)
    previous_version_path = thesis_version_path(str(company["symbol"]), previous_version)
    if not previous_version_path.exists():
        # Plan §9 migration: preserve a pre-v2 latest file before appending anything new.
        migrated = deepcopy(previous_document)
        migrated["schema_version"] = "2.0"
        migrated["version"] = previous_version
        migrated.setdefault("updated_at", _now())
        _persist_version(
            migrated,
            "migrate",
            ["从 v1 latest 文件迁移为不可变历史；未改变论文内容"],
        )
        previous_document = migrated
    changes = _evidence_changes(previous_document.get("evidence_snapshot") or {}, company)
    if not changes:
        changes.append("未发现可由当前结构化证据自动判定的变化")
    document = deepcopy(previous_document)
    document["schema_version"] = "2.0"
    document["version"] = previous_version + 1
    document["updated_at"] = _now()
    document["evidence_snapshot"] = _snapshot(company)
    if status is not None:
        document["status"] = status
        changes.append(f"论文状态：{previous_document.get('status')} → {status}")
    if reason:
        changes.append(f"显式理由：{reason}")
    return document, _persist_version(document, event_type, changes), changes


def review_thesis(company: dict[str, Any]) -> tuple[dict[str, Any] | None, Path, list[str]]:
    return _append_version(company, event_type="review")


def update_thesis(
    company: dict[str, Any], reason: str | None = None
) -> tuple[dict[str, Any] | None, Path, list[str]]:
    return _append_version(company, event_type="update", reason=reason)


def invalidate_thesis(
    company: dict[str, Any], reason: str
) -> tuple[dict[str, Any] | None, Path, list[str]]:
    if not reason.strip():
        raise ValueError("thesis invalidation requires a non-empty reason")
    return _append_version(company, event_type="invalidate", status="invalidated", reason=reason)


def compare_theses(symbol: str, from_version: int | str, to_version: int | str) -> dict[str, Any]:
    from_number = _version_number(from_version)
    to_number = _version_number(to_version)
    before_path = thesis_version_path(symbol, from_version)
    after_path = thesis_version_path(symbol, to_version)
    if not before_path.exists() or not after_path.exists():
        missing = [
            str(number)
            for number, path in ((from_number, before_path), (to_number, after_path))
            if not path.exists()
        ]
        raise ValueError(f"投资论文版本不存在：{', '.join(missing)}")
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))
    changed_fields = [
        field
        for field in ("status", "thesis", "evidence_snapshot")
        if before.get(field) != after.get(field)
    ]
    return {
        "schema_version": "1.0",
        "symbol": symbol,
        "from_version": from_number,
        "to_version": to_number,
        "changed_fields": changed_fields,
        "from": before,
        "to": after,
    }
