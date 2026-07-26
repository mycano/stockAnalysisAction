"""CLI facade for catalog routing, execution, and diagnostics."""

from __future__ import annotations

import argparse
import json

from ..presentation import build_delivery
from .catalog import CatalogError, load_catalog
from .router import AgentRouter, RequestError, load_host_request, parse_debug_input
from .runtime import execute_workflow


def build_agent_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stock-analysis agent")
    parser.add_argument("--catalog", help="Override canonical agent-entrypoints/catalog.json")
    subparsers = parser.add_subparsers(dest="agent_command", required=True)
    for name in ("route", "run"):
        command = subparsers.add_parser(name)
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument("--request", help="HostRequest JSON string or JSON file")
        source.add_argument(
            "--input",
            help="DEBUG/FIXTURE ONLY: explicit '/command key=value' syntax; never used by host entrypoints",
        )
        if name == "run":
            command.add_argument("--manifest", default="run_manifest.json")
            command.add_argument(
                "--debug",
                action="store_true",
                help="Show internal routing and diagnostics for explicit developer inspection",
            )
    subparsers.add_parser("doctor")
    return parser


def run_agent(argv: list[str]) -> int:
    parser = build_agent_parser()
    args = parser.parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
        if args.agent_command == "doctor":
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "schema_version": catalog.schema_version,
                        "catalog": str(catalog.path),
                        "catalog_hash": catalog.catalog_hash,
                        "commands": [_command_label(item) for item in catalog.commands],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        request = parse_debug_input(args.input) if args.input is not None else load_host_request(args.request)
        resolved = AgentRouter(catalog).resolve(request)
    except (CatalogError, RequestError, ValueError) as exc:
        parser.error(str(exc))

    if args.agent_command == "route":
        print(json.dumps(resolved.to_dict(), ensure_ascii=False, indent=2))
        return 2 if resolved.blocked else 0

    result, manifest = execute_workflow(request, resolved, manifest_path=args.manifest)
    if manifest["status"] == "blocked":
        print(_natural_block_message(resolved.block_reasons))
        return 2
    if result is not None:
        if result.stdout:
            if args.debug:
                print(result.stdout, end="")
            else:
                try:
                    print(build_delivery(result.stdout).report)
                except ValueError:
                    print("报告交付检查未通过，内部执行结果已保留，但不会向用户展示工程数据。")
                    return 1
        if args.debug:
            import sys
            from pathlib import Path

            print(json.dumps(resolved.execution_card, ensure_ascii=False, indent=2), file=sys.stderr)
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
            print(f"Run Manifest: {Path(args.manifest).resolve()}", file=sys.stderr)
    if manifest["status"] != "completed" and not args.debug:
        print("本次研究执行未完成；已取得的内部记录会保留，未验证内容不会作为结论发布。")
    return 0 if manifest["status"] == "completed" else 1


def _command_label(command: dict[str, object]) -> str:
    return str(command.get("command") or command.get("id") or command.get("command_id") or "")


def _natural_block_message(reasons: list[str]) -> str:
    if any("ASSET" in reason for reason in reasons):
        return "请补充需要研究的股票、基金或指数名称与代码。"
    if any("MOVE_START_DATE" in reason or "MOVE_END_DATE" in reason for reason in reasons):
        return "请补充异动分析的起止日期。"
    if any("MOVE_EVENT" in reason for reason in reasons):
        return "请说明需要核验的具体事件。"
    if any("SCREEN" in reason for reason in reasons):
        return "请明确股票池、报告期、筛选条件、排序方式和结果数量后再执行筛选。"
    if any("HOLDINGS" in reason for reason in reasons):
        return "请提供完整、可核对的持仓信息后再进行组合结论或压力测试。"
    if any("LENS" in reason for reason in reasons):
        return "请明确要采用的投资专家框架，以及并列、对抗或投委会方式。"
    return "当前请求还缺少会实质影响研究结果的信息，请补充研究对象、范围或必要条件。"
