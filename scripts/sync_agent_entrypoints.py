#!/usr/bin/env python3
"""Generate every supported Agent entrypoint from the canonical v2 catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = ROOT / "agent-entrypoints"
CATALOG = ENTRYPOINTS / "catalog.json"
TEMPLATES = ENTRYPOINTS / "templates"
SCHEMA_VERSION = "2.0"
COMMAND_IDS = (
    "market",
    "snapshot",
    "analyze",
    "earnings",
    "move",
    "screen",
    "portfolio",
    "thesis",
)


def _load_catalog() -> tuple[dict[str, Any], str]:
    raw = CATALOG.read_bytes()
    catalog = json.loads(raw)
    if catalog.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported catalog schema_version: {catalog.get('schema_version')!r}")
    commands = catalog.get("commands")
    if not isinstance(commands, list):
        raise ValueError("catalog commands must be a list")
    ids = tuple(command.get("id") for command in commands)
    if ids != COMMAND_IDS or len(ids) != len(set(ids)):
        raise ValueError(f"catalog commands must be the ordered eight-command protocol: {COMMAND_IDS!r}")
    for command in commands:
        if command.get("command_id") != f"stock-analysis.{command['id']}":
            raise ValueError(f"invalid command_id for {command['id']}")
        if not command.get("workflows"):
            raise ValueError(f"command {command['id']} has no workflows")
    return catalog, f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _template(name: str, values: dict[str, str]) -> str:
    rendered = (TEMPLATES / name).read_text(encoding="utf-8")
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    if re.search(r"\{\{[a-z_]+\}\}", rendered):
        raise ValueError(f"unresolved placeholder in {name}")
    return rendered


def _request_example(command: dict[str, Any], preset: dict[str, Any] | None = None) -> str:
    arguments = dict(preset or {})
    required = command["request_schema"].get("required", [])
    properties = command["request_schema"].get("properties", {})
    for key in required:
        if key in arguments:
            continue
        prop = properties[key]
        if "enum" in prop:
            arguments[key] = prop["enum"][0]
        elif prop.get("type") == "array":
            arguments[key] = []
        elif prop.get("type") == "integer":
            arguments[key] = prop.get("minimum", 1)
        elif key == "asset":
            arguments[key] = "<asset>"
        else:
            arguments[key] = f"<{key}>"
    request = {
        "schema_version": SCHEMA_VERSION,
        "command": command["id"],
        "arguments": arguments,
    }
    return json.dumps(request, ensure_ascii=False, separators=(",", ":"))


def _target_values(
    command: dict[str, Any],
    catalog_hash: str,
    host_target: str,
) -> dict[str, str]:
    command_id = command["command_id"]
    command_name = command["id"]
    output_contracts = sorted(
        {workflow["output_contract"]["description"] for workflow in command["workflows"].values()}
    )
    return {
        "name": f"stock-analysis-{command_name}",
        "description": command["summary"].replace('"', '\\"'),
        "schema_version": SCHEMA_VERSION,
        "command_id": command_id,
        "x_command": command_name,
        "catalog_hash": catalog_hash,
        "host_target": host_target,
        "heading": f"/{command_name}",
        "request_example": _request_example(command),
        "host_contract": command["host_contract"],
        "output_contract": "\n\n".join(output_contracts),
    }


def _canonical_destinations(command_id: str) -> dict[str, Path]:
    skill_name = f"stock-analysis-{command_id}"
    return {
        "codex-skill": ROOT / "codex-skills" / skill_name / "SKILL.md",
        "codex-prompt": ROOT / "codex-prompts" / f"{command_id}.md",
        "claude-command": ROOT / "claude-commands" / f"{command_id}.md",
        "generic-skill": ROOT / "generic-skills" / skill_name / "SKILL.md",
    }


def _legacy_destinations(legacy_id: str) -> dict[str, Path]:
    return {
        "codex-skill": ROOT / "codex-skills" / legacy_id / "SKILL.md",
        "codex-prompt": ROOT / "codex-prompts" / f"{legacy_id}.md",
        "claude-command": ROOT / "claude-commands" / f"{legacy_id}.md",
        "generic-skill": ROOT / "generic-skills" / legacy_id / "SKILL.md",
    }


def _operational_destinations(entrypoint_id: str) -> dict[str, Path]:
    return _legacy_destinations(entrypoint_id)


def _render_all(catalog: dict[str, Any], catalog_hash: str) -> dict[Path, str]:
    # Plan §11: every host artifact is derived from one catalog hash.
    outputs: dict[Path, str] = {}
    commands = {command["id"]: command for command in catalog["commands"]}

    for command in catalog["commands"]:
        for host_target, path in _canonical_destinations(command["id"]).items():
            values = _target_values(command, catalog_hash, host_target)
            outputs[path] = _template("command.md.tmpl", values)

    for legacy in catalog["compatibility"]["legacy_entrypoints"]:
        command = commands[legacy["command"]]
        for host_target, path in _legacy_destinations(legacy["id"]).items():
            values = {
                "name": legacy["id"],
                "description": (
                    f"已弃用的 /{legacy['id']} 兼容入口；转发到 /{command['id']}。"
                ),
                "schema_version": SCHEMA_VERSION,
                "command_id": command["command_id"],
                "x_command": command["id"],
                "catalog_hash": catalog_hash,
                "host_target": host_target,
                "heading": f"/{legacy['id']}（兼容）",
                "deprecated_since": legacy["deprecated_since"],
                "new_entrypoint": f"/{command['id']}",
                "request_example": _request_example(command, legacy.get("arguments")),
            }
            outputs[path] = _template("legacy.md.tmpl", values)

    for operational in catalog["compatibility"]["operational_entrypoints"]:
        for host_target, path in _operational_destinations(operational["id"]).items():
            values = {
                "name": operational["id"],
                "description": operational["summary"],
                "schema_version": SCHEMA_VERSION,
                "command_id": operational["command_id"],
                "x_command": operational["id"],
                "catalog_hash": catalog_hash,
                "host_target": host_target,
                "heading": f"/{operational['id']}",
                "argv": " ".join(operational["argv_template"]),
            }
            outputs[path] = _template("operational.md.tmpl", values)
    return outputs


def sync(check: bool) -> int:
    catalog, catalog_hash = _load_catalog()
    expected = _render_all(catalog, catalog_hash)
    stale = [
        path for path, content in expected.items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]
    if stale and check:
        print("Agent entrypoints are out of sync:")
        print("\n".join(str(path.relative_to(ROOT)) for path in stale))
        return 1
    for path in stale:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected[path], encoding="utf-8")
    print(
        f"{'Checked' if check else 'Synced'} {len(catalog['commands'])} commands "
        f"and {len(expected)} managed entrypoints ({catalog_hash})."
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    raise SystemExit(sync(parser.parse_args().check))
