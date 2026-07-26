"""CLI facade for catalog routing, execution, and diagnostics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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

    print(json.dumps(resolved.execution_card, ensure_ascii=False, indent=2), file=sys.stderr)
    result, manifest = execute_workflow(request, resolved, manifest_path=args.manifest)
    if result is not None:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
    print(f"Run Manifest: {Path(args.manifest).resolve()}", file=sys.stderr)
    if manifest["status"] == "blocked":
        return 2
    return 0 if manifest["status"] == "completed" else 1


def _command_label(command: dict[str, object]) -> str:
    return str(command.get("command") or command.get("id") or command.get("command_id") or "")
