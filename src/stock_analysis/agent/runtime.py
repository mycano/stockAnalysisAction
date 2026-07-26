"""Workflow execution and auditable run manifest generation."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import HostRequest, ResolvedRequest


@dataclass(frozen=True)
class WorkflowResult:
    returncode: int
    stdout: str
    stderr: str


Executor = Callable[[Sequence[str]], WorkflowResult]


def subprocess_executor(argv: Sequence[str]) -> WorkflowResult:
    completed = subprocess.run(list(argv), check=False, capture_output=True, text=True)
    return WorkflowResult(completed.returncode, completed.stdout, completed.stderr)


def execute_workflow(
    request: HostRequest,
    resolved: ResolvedRequest,
    *,
    manifest_path: str | Path = "run_manifest.json",
    executor: Executor = subprocess_executor,
) -> tuple[WorkflowResult | None, dict[str, Any]]:
    started = datetime.now(timezone.utc)
    result: WorkflowResult | None = None
    error: str | None = None
    if resolved.blocked:
        status = "blocked"
    elif not resolved.argv:
        status = "failed"
        error = "resolved workflow has no argv"
    else:
        try:
            result = executor(tuple(resolved.argv))
            status = "completed" if result.returncode == 0 else "failed"
        except OSError as exc:
            status = "failed"
            error = str(exc)
    completed = datetime.now(timezone.utc)
    validation = _validate_output(resolved, result)
    if status == "completed" and not validation["valid"]:
        status = "failed"
    manifest = {
        "schema_version": "2.0",
        "request": request.to_dict(),
        "resolved_request": resolved.to_dict(),
        "execution_card": resolved.execution_card,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "status": status,
        "returncode": result.returncode if result is not None else None,
        "error": error,
        "output_validation": validation,
    }
    path = Path(manifest_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result, manifest


def _validate_output(resolved: ResolvedRequest, result: WorkflowResult | None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    if result is None:
        return {"valid": False, "checks": [{"name": "workflow_executed", "passed": False}]}
    checks.append({"name": "exit_code_zero", "passed": result.returncode == 0})
    contract = resolved.output_contract
    if contract.get("stdout_required", True):
        checks.append({"name": "stdout_non_empty", "passed": bool(result.stdout.strip())})
    for section in contract.get("required_sections") or []:
        checks.append(
            {
                "name": f"section:{section}",
                "passed": str(section) in result.stdout,
            }
        )
    workspace = _workspace_from_stdout(result.stdout)
    for artifact in contract.get("required_artifacts") or []:
        try:
            artifact_name = str(artifact).format(**resolved.arguments)
        except KeyError:
            checks.append({"name": f"artifact:{artifact}", "passed": False, "path": None})
            continue
        artifact_path = Path(artifact_name)
        if not artifact_path.is_file() and workspace is not None:
            artifact_path = workspace / artifact_name
        checks.append(
            {
                "name": f"artifact:{artifact}",
                "passed": artifact_path.is_file(),
                "path": str(artifact_path),
            }
        )
    return {"valid": all(item["passed"] for item in checks), "checks": checks}


def _workspace_from_stdout(stdout: str) -> Path | None:
    for line in reversed(stdout.splitlines()):
        prefix = "Research Workspace:"
        if line.startswith(prefix):
            value = line[len(prefix) :].strip()
            return Path(value) if value else None
    return None
