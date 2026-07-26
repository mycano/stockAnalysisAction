"""CLI orchestration for stock, fund, thesis, and recoverable research commands."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .presentation import build_delivery


@dataclass(frozen=True)
class ResearchCommandServices:
    build_company_evidence: Callable[..., dict[str, Any]]
    build_fund_evidence: Callable[..., dict[str, Any]]
    build_company_workspace: Callable[..., tuple[dict[str, Any], Path]]
    build_fund_workspace: Callable[..., tuple[dict[str, Any], Path]]
    render_stock_review: Callable[[dict[str, Any]], str]
    render_earnings_review: Callable[..., str]
    render_price_move: Callable[..., str]
    create_thesis: Callable[..., tuple[dict[str, Any], Path]]
    review_thesis: Callable[..., tuple[dict[str, Any] | None, Path, list[str]]]
    update_thesis: Callable[..., tuple[dict[str, Any] | None, Path, list[str]]]
    invalidate_thesis: Callable[..., tuple[dict[str, Any] | None, Path, list[str]]]
    compare_theses: Callable[..., dict[str, Any]]
    render_thesis_create: Callable[[dict[str, Any], Path], str]
    render_thesis_review: Callable[[dict[str, Any] | None, Path, list[str]], str]
    load_reached_primary_evidence: Callable[..., dict[str, list[dict[str, Any]]]]
    enrich_company_evidence_from_web: Callable[..., dict[str, Any]] | None = None
    enrich_fund_evidence_from_web: Callable[..., dict[str, Any]] | None = None
    enrich_company_peer_comparison: Callable[..., dict[str, Any]] | None = None


def _user_limitations(
    pack: dict[str, Any],
    *,
    fund: bool,
    include_valuation: bool = True,
) -> tuple[str, ...]:
    """Return concise research boundaries for display outside the report body."""

    if fund:
        return (
            "基金持仓与规模采用最近公开披露口径，不代表报告日的实时持仓。",
        )
    if not include_valuation:
        return ()
    accepted = {"accepted", "strongly_supported", "supported", "derived_verified"}
    market_cap_available = any(
        item.get("metric") == "total_market_cap"
        and item.get("value") is not None
        and str(item.get("validation_status") or "").lower() in accepted
        for section in (pack.get("modules") or {}).values()
        for item in section.get("evidence") or []
    )
    if market_cap_available:
        return ()
    return (
        "本次未取得可独立验证的最新总市值，因此未发布依赖总市值的精确绝对估值；"
        "报告仍保留相对估值、经营判断与价格观察条件。",
    )


def _print_user_report(
    report: str,
    pack: dict[str, Any],
    *,
    fund: bool,
    include_valuation: bool = True,
) -> None:
    sys.stdout.write(
        build_delivery(
            report,
            limitations=_user_limitations(
                pack,
                fund=fund,
                include_valuation=include_valuation,
            ),
        ).render()
    )


def _load_expectations(args: argparse.Namespace, parser: argparse.ArgumentParser, *, fund: bool) -> dict[str, Any] | None:
    if not args.expectations_file:
        return None
    if fund:
        parser.error("--expectations-file currently supports company research only")
    try:
        value = json.loads(Path(args.expectations_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read --expectations-file: {exc}")
    if not isinstance(value, dict):
        parser.error("--expectations-file must contain a JSON object")
    return value


def run_research_command(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
    trade_date: str,
    services: ResearchCommandServices,
) -> int:
    if not args.symbol:
        parser.error(f"--symbol is required when --market {args.market}")
    research_is_fund = args.market == "research" and (
        args.asset_type == "fund"
        or (args.asset_type == "auto" and str(args.symbol).startswith(("5", "15", "16")))
    )
    expectations = _load_expectations(args, parser, fund=research_is_fund)
    reached_primary = None
    if args.primary_evidence_file:
        if research_is_fund:
            parser.error("--primary-evidence-file supports company research only")
        try:
            reached_primary = services.load_reached_primary_evidence(
                args.primary_evidence_file,
                symbol=args.symbol,
                trade_date=trade_date,
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(f"cannot read --primary-evidence-file: {exc}")
    try:
        if research_is_fund:
            pack = services.build_fund_evidence(args.symbol, trade_date)
        elif expectations is not None or reached_primary is not None:
            company_options: dict[str, Any] = {}
            if expectations is not None:
                company_options["expectations"] = expectations
            if reached_primary is not None:
                company_options["reached_primary"] = reached_primary
            pack = services.build_company_evidence(
                args.symbol,
                trade_date,
                **company_options,
            )
        else:
            pack = services.build_company_evidence(args.symbol, trade_date)
    except ValueError as exc:
        parser.error(f"invalid research assumptions: {exc}")
    requested_lenses = tuple(item.strip() for item in (args.lenses or "").split(",") if item.strip())
    if args.lens and not requested_lenses:
        requested_lenses = (args.lens,)
    research_mode = getattr(args, "research_mode", "general")
    if getattr(args, "external_evidence", "auto") != "off":
        evidence_mode = (
            "lens" if research_mode == "lens" else getattr(args, "depth", "standard")
        )
        if research_is_fund and services.enrich_fund_evidence_from_web is not None:
            pack = services.enrich_fund_evidence_from_web(pack, mode=evidence_mode)
        elif not research_is_fund and services.enrich_company_evidence_from_web is not None:
            pack = services.enrich_company_evidence_from_web(
                pack,
                mode=evidence_mode,
                lens_ids=requested_lenses,
            )
    if (
        not research_is_fund
        and getattr(args, "depth", "standard") == "deep"
        and services.enrich_company_peer_comparison is not None
    ):
        pack = services.enrich_company_peer_comparison(pack)

    if args.market == "stock-review":
        _print_user_report(services.render_stock_review(pack), pack, fund=False)
    elif args.market == "earnings":
        _print_user_report(
            services.render_earnings_review(pack, depth=getattr(args, "depth", "standard")),
            pack,
            fund=False,
        )
    elif args.market == "price-move":
        _print_user_report(
            services.render_price_move(
                pack,
                window_type=args.window_type,
                start_date=args.start_date,
                event=args.event,
                depth=getattr(args, "depth", "standard"),
            ),
            pack,
            fund=False,
            include_valuation=False,
        )
    elif args.market == "thesis-create":
        try:
            thesis, path = services.create_thesis(pack)
        except ValueError as exc:
            parser.error(str(exc))
        print(services.render_thesis_create(thesis, path))
    elif args.market in {"thesis-review", "thesis-update", "thesis-invalidate"}:
        if args.market == "thesis-review":
            thesis, path, changes = services.review_thesis(pack)
        elif args.market == "thesis-update":
            thesis, path, changes = services.update_thesis(pack, args.reason)
        else:
            if not args.reason:
                parser.error("--reason is required when --market thesis-invalidate")
            thesis, path, changes = services.invalidate_thesis(pack, args.reason)
        print(services.render_thesis_review(thesis, path, changes))
    elif args.market == "thesis-compare":
        if args.from_version is None or args.to_version is None:
            parser.error("--from-version and --to-version are required when --market thesis-compare")
        try:
            comparison = services.compare_theses(args.symbol, args.from_version, args.to_version)
        except ValueError as exc:
            parser.error(str(exc))
        changed_labels = {
            "status": "论文状态",
            "thesis": "核心投资逻辑",
            "evidence_snapshot": "证据快照",
        }
        changed = [
            changed_labels.get(str(field), "研究内容")
            for field in comparison.get("changed_fields") or []
        ]
        print(
            "\n".join(
                [
                    f"# 投资论文版本比较：{comparison['symbol']}",
                    "",
                    f"- 比较版本：{comparison['from_version']} → {comparison['to_version']}",
                    "- 发生变化的部分："
                    + ("、".join(changed) if changed else "未识别到结构化变化"),
                    "- 版本比较不会修改任何历史记录。",
                ]
            )
        )
    elif args.market == "research":
        lens_mode = getattr(args, "lens_mode", None) or getattr(args, "mode", None)
        try:
            if research_is_fund:
                manifest, workspace = services.build_fund_workspace(
                    pack,
                    root=args.workspace_dir,
                    research_question=args.research_question,
                    lenses=requested_lenses or None,
                    research_mode=research_mode,
                    general_mode=getattr(args, "depth", "standard"),
                    lens_mode=lens_mode,
                    delivery_budget=getattr(args, "delivery_budget", "full"),
                )
            else:
                manifest, workspace = services.build_company_workspace(
                    pack,
                    root=args.workspace_dir,
                    lenses=requested_lenses or None,
                    research_question=args.research_question,
                    research_mode=research_mode,
                    general_mode=getattr(args, "depth", "standard"),
                    lens_mode=lens_mode,
                    delivery_budget=getattr(args, "delivery_budget", "full"),
                )
        except (KeyError, ValueError) as exc:
            parser.error(str(exc))
        report_path = workspace / manifest["artifacts"]["institutional_report"]["path"]
        _print_user_report(
            report_path.read_text(encoding="utf-8"),
            pack,
            fund=research_is_fund,
        )
        if getattr(args, "emit_internal_path", False):
            print(f"STOCK_ANALYSIS_WORKSPACE={workspace}", file=sys.stderr)
    if args.emit_evidence:
        (Path.cwd() / f"company_evidence_{pack['symbol']}_{trade_date}.json").write_text(
            json.dumps(pack, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0
