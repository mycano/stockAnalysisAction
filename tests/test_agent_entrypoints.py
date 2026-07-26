import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "agent-entrypoints" / "catalog.json"
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
CATEGORIES = (
    "normal",
    "ambiguous",
    "cross_command",
    "missing_required",
    "mixed_language",
    "malicious",
)


def _catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _catalog_hash():
    return f"sha256:{hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()}"


def test_catalog_v2_is_the_single_eight_command_protocol():
    catalog = _catalog()

    assert catalog["schema_version"] == "2.0"
    assert catalog["protocol_id"] == "stock-analysis-agent"
    assert catalog["architecture"]["layers"] == [
        "HostRequest",
        "ResolvedRequest",
        "Workflow",
    ]
    assert tuple(command["id"] for command in catalog["commands"]) == COMMAND_IDS
    assert len({command["command_id"] for command in catalog["commands"]}) == 8

    for command in catalog["commands"]:
        assert command["command_id"] == f"stock-analysis.{command['id']}"
        assert command["request_schema"]["properties"]
        assert command["routing"]
        assert command["workflows"]
        assert isinstance(command["redirects"], list)
        for workflow in command["workflows"].values():
            assert isinstance(workflow["argv_template"], list)
            assert all(isinstance(token, str) for token in workflow["argv_template"])
            contract = workflow["output_contract"]
            assert set(("description", "stdout_required", "required_artifacts")) <= set(contract)
            assert isinstance(contract["required_artifacts"], list)


def test_protocol_schemas_encode_production_host_and_resolved_requests():
    schemas = ROOT / "agent-entrypoints" / "schemas"
    host = json.loads((schemas / "host-request.schema.json").read_text(encoding="utf-8"))
    resolved = json.loads((schemas / "resolved-request.schema.json").read_text(encoding="utf-8"))

    assert host["additionalProperties"] is False
    assert set(host["required"]) == {"schema_version", "command", "arguments"}
    assert "raw_input" not in host["properties"]
    assert host["properties"]["command"]["enum"] == list(COMMAND_IDS)
    assert "catalog_hash" in resolved["required"]
    assert resolved["properties"]["output_contract"]["type"] == ["object", "null"]
    redirect = resolved["properties"]["redirect"]
    assert redirect["required"] == ["from", "to", "reason_code"]


def test_catalog_preserves_p0_routing_and_output_safety_contracts():
    commands = {command["id"]: command for command in _catalog()["commands"]}

    analyze = commands["analyze"]
    assert analyze["defaults"]["depth"] == "standard"
    assert {
        "reverse_valuation",
        "multi_scenario",
        "committee",
        "historical_comparison",
        "full_audit",
        "fund_lookthrough",
        "position_decision",
    } == set(analyze["routing"]["deep_only_capabilities"])

    move = commands["move"]
    assert set(move["workflows"]) == {
        "single-session",
        "multi-session",
        "event-window",
    }
    for workflow in move["workflows"].values():
        assert workflow["output_contract"]["required_artifacts"] == []
        assert "用户可读" in workflow["output_contract"]["description"] or "事件窗口" in workflow["output_contract"]["description"]
        assert "required_sections" not in workflow["output_contract"]

    screen = commands["screen"]
    assert screen["defaults"]["mode"] == "explore"
    assert screen["workflows"]["explore"]["argv_template"] == []
    assert screen["defaults"]["confirmed"] is False

    portfolio = commands["portfolio"]
    assert portfolio["defaults"]["holdings_status"] == "missing"
    assert {"complete", "partial", "stale", "missing"} == set(
        portfolio["request_schema"]["properties"]["holdings_status"]["enum"]
    )

    thesis = commands["thesis"]
    assert thesis["routing"]["default_route"] is None
    assert {"from_version", "to_version", "reason"} <= set(
        thesis["request_schema"]["properties"]
    )
    assert thesis["workflows"]["compare"]["argv_template"] == [
        "stock-analysis",
        "--market",
        "thesis-compare",
        "--symbol",
        "{asset}",
        "--from-version",
        "{from_version}",
        "--to-version",
        "{to_version}",
        "--emit-evidence",
    ]
    for action in ("create", "review", "update", "compare", "invalidate"):
        assert f"thesis-{action}" in thesis["workflows"][action]["argv_template"]


def test_generated_entrypoints_have_identical_managed_metadata():
    expected_hash = _catalog_hash()
    for command_id in COMMAND_IDS:
        paths = (
            ROOT / "codex-skills" / f"stock-analysis-{command_id}" / "SKILL.md",
            ROOT / "codex-prompts" / f"{command_id}.md",
            ROOT / "claude-commands" / f"{command_id}.md",
            ROOT / "generic-skills" / f"stock-analysis-{command_id}" / "SKILL.md",
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            assert "x-stock-analysis-managed: true" in text
            assert 'x-stock-analysis-schema: "agent-entrypoint/v2"' in text
            assert f'x-stock-analysis-command: "{command_id}"' in text
            assert f'x-stock-analysis-catalog-hash: "{expected_hash}"' in text
            assert f'command_id: "stock-analysis.{command_id}"' in text
            assert "stock-analysis agent run --request" in text
            assert "stock-analysis agent route --request" not in text
            assert "向用户展示 `RouteDecision`" not in text
            assert "用户确认执行上下文" not in text
            assert "agent run --input" not in text


def test_generated_legacy_entries_only_forward_and_diagnose_stays_operational():
    compatibility = _catalog()["compatibility"]
    for legacy in compatibility["legacy_entrypoints"]:
        target = legacy["command"]
        text = (ROOT / "codex-prompts" / f"{legacy['id']}.md").read_text(
            encoding="utf-8"
        )
        assert "deprecated: true" in text
        assert f"转发到 `/{target}`" in text
        assert '"command":"' + target + '"' in text
        assert "stock-analysis agent run --request" in text

    diagnose = (ROOT / "codex-prompts" / "data-diagnose.md").read_text(
        encoding="utf-8"
    )
    assert "operational: true" in diagnose
    assert "stock-analysis-agent doctor all" in diagnose
    assert "HostRequest" in diagnose
    assert "不接受或模拟" in diagnose


def test_fixture_matrix_has_all_280_required_protocol_cases():
    path = ROOT / "agent-entrypoints" / "fixtures" / "route-cases.json"
    fixtures = json.loads(path.read_text(encoding="utf-8"))
    minimums = fixtures["category_minimums"]

    assert fixtures["schema_version"] == "2.0"
    assert tuple(fixtures["commands"]) == COMMAND_IDS
    ids = []
    for command_id, categories in fixtures["commands"].items():
        assert set(categories) == set(CATEGORIES)
        for category in CATEGORIES:
            cases = categories[category]
            assert len(cases) >= minimums[category], (command_id, category)
            for case in cases:
                assert case["id"].startswith(f"{command_id}-{category.split('_')[0]}-")
                assert "expected" in case
                assert "arguments" in case or "request" in case
                ids.append(case["id"])

    assert len(ids) == 280
    assert len(ids) == len(set(ids))


def test_generated_entrypoints_have_no_drift():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_agent_entrypoints.py"), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
