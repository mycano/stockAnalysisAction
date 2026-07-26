import json
from pathlib import Path

import pytest

from stock_analysis import app
from stock_analysis.agent.catalog import load_catalog
from stock_analysis.agent.cli import run_agent
from stock_analysis.agent.models import HostRequest
from stock_analysis.agent.router import AgentRouter, RequestError, parse_debug_input
from stock_analysis.agent.runtime import WorkflowResult, execute_workflow

_ROUTE_FIXTURES = json.loads(
    (Path(__file__).parents[1] / "agent-entrypoints" / "fixtures" / "route-cases.json").read_text(
        encoding="utf-8"
    )
)
_ROUTE_CASES = [
    pytest.param(command, category, case, id=case["id"])
    for command, categories in _ROUTE_FIXTURES["commands"].items()
    for category, cases in categories.items()
    for case in cases
]


@pytest.fixture()
def catalog_path(tmp_path):
    def command(name, *, required=None, defaults=None, routes=None):
        routes = routes or ["default"]
        workflows = {}
        for route in routes:
            market = {
                "market": "daily",
                "snapshot": "stock",
                "analyze": "stock-review",
                "earnings": "earnings",
                "move": "price-move",
                "screen": "screen",
                "portfolio": "portfolio",
                "thesis": "thesis-review",
            }[name]
            argv = ["stock-analysis", "--market", market]
            if name in {"snapshot", "analyze", "earnings", "move", "thesis"}:
                argv.extend(["--symbol", "{asset}"])
            if name == "screen":
                argv.extend(
                    [
                        "--fiscal-year",
                        "{fiscal_year}",
                        "--universe-file",
                        "{universe_file}",
                        "--filter",
                        "{filters}",
                        "--sort",
                        "{sort}",
                        "--limit",
                        "{limit}",
                    ]
                )
                if route == "explore":
                    argv = []
            workflows[route] = {
                "workflow_id": f"{name}-{route}",
                "argv": argv,
                "output_contract": {"stdout_required": True},
            }
        return {
            "id": name,
            "command_id": name,
            "command": name,
            "request_schema": {
                "required": required or [],
                "properties": {"asset": {"type": "string"}},
            },
            "defaults": defaults or {},
            "routing": {"default_route": routes[0]},
            "workflows": workflows,
        }

    payload = {
        "schema_version": "2.0",
        "commands": [
            command("market", routes=["daily", "global"]),
            command("snapshot", required=["asset"], routes=["facts"]),
            command(
                "analyze",
                required=["asset"],
                defaults={"depth": "standard"},
                routes=["standard", "quick", "deep"],
            ),
            command(
                "earnings",
                required=["asset"],
                defaults={"mode": "standard"},
                routes=["standard", "facts", "thesis-impact"],
            ),
            command(
                "move",
                required=["asset"],
                defaults={"window_type": "single-day"},
                routes=["single-day", "multi-day", "event-window"],
            ),
            command("screen", routes=["execute", "explore"]),
            command(
                "portfolio",
                defaults={"action": "review"},
                routes=["review", "import", "stress", "compare"],
            ),
            command("thesis", required=["asset"], routes=["review", "create", "update", "compare", "invalidate"]),
        ],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def request(command, **arguments):
    return HostRequest(
        schema_version="2.0",
        command=command,
        arguments=arguments,
        source={"host": "pytest"},
    )


@pytest.mark.parametrize(("command", "category", "case"), _ROUTE_CASES)
def test_canonical_route_fixtures(command, category, case):
    del category
    payload = case["request"] if "request" in case else {
        "schema_version": "2.0",
        "command": command,
        "arguments": case["arguments"],
    }
    expected = case["expected"]
    if expected == "invalid":
        with pytest.raises((RequestError, ValueError)):
            AgentRouter().resolve(HostRequest.from_mapping(payload))
        return

    resolved = AgentRouter().resolve(HostRequest.from_mapping(payload))
    if expected == "blocked":
        assert resolved.blocked
    elif expected == "limited":
        assert not resolved.output_contract["complete_conclusion_allowed"]
    elif expected.startswith("redirect:"):
        assert resolved.redirect is not None
        assert resolved.redirect["to"] == expected.split(":", 1)[1]
    elif expected.startswith("route:"):
        assert resolved.route == expected.split(":", 1)[1]
        assert not resolved.blocked
    elif expected == "route":
        assert not resolved.blocked
        assert resolved.argv
    elif expected == "clarify_or_block":
        assert resolved.blocked or resolved.argv
    elif expected in {"clarify_or_default", "clarify_or_route"}:
        assert resolved.blocked or resolved.route
    elif expected == "redirect_or_clarify":
        assert resolved.redirect is not None or resolved.route or resolved.blocked
    else:
        raise AssertionError(f"unsupported fixture expectation: {expected}")


def test_analyze_defaults_to_standard_and_deep_capability_wins():
    router = AgentRouter()

    standard = router.resolve(request("analyze", asset="600519"))
    deep = router.resolve(
        request("analyze", asset="600519", depth="quick", capabilities=["reverse_valuation"])
    )

    assert standard.route == "standard"
    assert "ANALYZE_STANDARD_DEFAULT" in standard.reason_codes
    assert deep.route == "deep"
    assert deep.arguments["depth"] == "deep"
    assert "ANALYZE_DEEP_CAPABILITY" in deep.reason_codes


def test_explicit_lens_is_independent_from_general_depth():
    router = AgentRouter()

    resolved = router.resolve(
        request(
            "analyze",
            asset="600519",
            depth="quick",
            research_mode="lens",
            lens_mode="single",
            lens="buffett",
        )
    )

    assert resolved.route == "lens"
    assert resolved.arguments["research_mode"] == "lens"
    assert resolved.arguments["general_mode"] is None
    assert resolved.arguments["lens_mode"] == "single"
    assert "--depth" not in resolved.argv
    assert resolved.argv[resolved.argv.index("--lens") + 1] == "buffett"


def test_adversarial_lens_requires_exactly_two_frameworks():
    router = AgentRouter()

    valid = router.resolve(
        request(
            "analyze",
            asset="600519",
            research_mode="lens",
            lens_mode="adversarial",
            lenses=["buffett", "soros"],
        )
    )
    invalid = router.resolve(
        request(
            "analyze",
            asset="600519",
            research_mode="lens",
            lens_mode="adversarial",
            lenses=["buffett"],
        )
    )

    assert not valid.blocked
    assert valid.argv[valid.argv.index("--lenses") + 1] == "buffett,soros"
    assert invalid.blocked
    assert "ADVERSARIAL_LENS_REQUIRES_TWO_FRAMEWORKS" in invalid.block_reasons


@pytest.mark.parametrize(
    ("command", "arguments", "target"),
    [
        ("market", {"asset": "600519"}, "analyze"),
        ("market", {"asset": "600519", "intent": "move"}, "move"),
        ("snapshot", {"asset": "600519", "intent": "valuation"}, "analyze"),
        ("snapshot", {"asset": "600519", "intent": "earnings"}, "earnings"),
        ("analyze", {"asset": "600519", "intent": "move"}, "move"),
    ],
)
def test_cross_command_redirects_are_explicit(command, arguments, target):
    resolved = AgentRouter().resolve(request(command, **arguments))

    assert resolved.command == target
    assert resolved.redirect["from"] == command
    assert resolved.redirect["to"] == target
    assert resolved.redirect["reason_code"] in resolved.reason_codes


def test_screen_requires_structured_confirmed_criteria(catalog_path):
    router = AgentRouter(catalog_path)

    explore = router.resolve(request("screen", query="高ROE公司"))
    execute = router.resolve(
        request(
            "screen",
            mode="execute",
            universe_file="/tmp/universe.json",
            fiscal_year=2025,
            filters=[
                {
                    "field": "roe_weighted",
                    "operator": "gt",
                    "value": 8,
                    "unit": "percent",
                    "missing": "unknown",
                }
            ],
            sort={"field": "roe_weighted", "direction": "desc"},
            limit=20,
            confirmed=True,
        )
    )

    assert explore.route == "explore"
    assert explore.blocked
    assert "SCREEN_CONFIRMATION_REQUIRED" in explore.block_reasons
    assert not explore.argv
    assert execute.route == "execute"
    assert not execute.blocked
    assert execute.argv[-4:] == ["--sort", "roe_weighted:desc", "--limit", "20"]


def test_screen_complete_but_unconfirmed_request_does_not_execute(catalog_path):
    resolved = AgentRouter(catalog_path).resolve(
        request(
            "screen",
            mode="execute",
            universe_file="/tmp/universe.json",
            fiscal_year=2025,
            filters=[
                {
                    "field": "roe_weighted",
                    "operator": "gt",
                    "value": 8,
                    "unit": "percent",
                    "missing": "unknown",
                }
            ],
            sort={"field": "roe_weighted", "direction": "desc"},
            limit=20,
            confirmed=False,
        )
    )

    assert resolved.route == "explore"
    assert resolved.blocked
    assert not resolved.argv
    assert "SCREEN_CONFIRMATION_REQUIRED" in resolved.block_reasons


def test_explicit_analyze_depth_precedes_natural_language_signal(catalog_path):
    resolved = AgentRouter(catalog_path).resolve(
        request("analyze", asset="600519", depth="deep", intent="move")
    )

    assert resolved.command == "analyze"
    assert resolved.route == "deep"
    assert resolved.redirect is None
    assert "ANALYZE_DEEP_EXPLICIT" in resolved.reason_codes


def test_quick_fund_analysis_uses_fund_research_report_path():
    resolved = AgentRouter().resolve(
        request("analyze", asset="512480", asset_type="fund", depth="quick")
    )

    assert resolved.route == "quick"
    assert resolved.argv[2:4] == ["research", "--symbol"]
    assert resolved.argv[resolved.argv.index("--asset-type") + 1] == "fund"
    assert resolved.argv[resolved.argv.index("--depth") + 1] == "quick"


@pytest.mark.parametrize("status", ["partial", "stale", "missing"])
def test_portfolio_incomplete_holdings_prohibit_complete_conclusion(catalog_path, status):
    resolved = AgentRouter(catalog_path).resolve(
        request("portfolio", action="review", holdings_status=status)
    )

    assert not resolved.blocked
    assert resolved.output_contract["complete_conclusion_allowed"] is False
    assert resolved.output_contract["holdings_status"] == status


def test_move_contract_has_five_causal_categories(catalog_path):
    resolved = AgentRouter(catalog_path).resolve(
        request("move", asset="600519", window_type="event-window", event="earnings")
    )

    assert resolved.route == "event-window"
    assert resolved.output_contract["causal_categories"] == [
        "confirmed_trigger",
        "plausibly_related",
        "market_wide_factor",
        "unsupported_speculation",
        "unknown",
    ]
    assert "MOVE_CAUSAL_BOUNDARY_ENFORCED" in resolved.reason_codes


@pytest.mark.parametrize(
    ("arguments", "expected_window"),
    [
        (
            {
                "asset": "600519",
                "window_type": "multi-session",
                "start_date": "20260720",
                "end_date": "20260726",
            },
            "multi-session",
        ),
        (
            {
                "asset": "600519",
                "window_type": "event-window",
                "event": "earnings",
                "end_date": "20260726",
            },
            "event-window",
        ),
    ],
)
def test_move_window_boundaries_reach_workflow_argv(arguments, expected_window):
    resolved = AgentRouter().resolve(request("move", **arguments))

    assert not resolved.blocked
    assert ["--window-type", expected_window] == resolved.argv[
        resolved.argv.index("--window-type") : resolved.argv.index("--window-type") + 2
    ]
    assert resolved.argv[resolved.argv.index("--date") + 1] == "20260726"


def test_thesis_requires_action_and_update_is_append_only(catalog_path):
    router = AgentRouter(catalog_path)

    missing = router.resolve(request("thesis", asset="600519"))
    update = router.resolve(request("thesis", asset="600519", action="update"))

    assert missing.blocked
    assert "THESIS_ACTION_REQUIRED" in missing.block_reasons
    assert not update.blocked
    assert update.output_contract["history_mode"] == "append_only"
    assert update.output_contract["silent_overwrite"] is False


def test_thesis_compare_requires_two_explicit_versions(catalog_path):
    resolved = AgentRouter(catalog_path).resolve(
        request("thesis", asset="600519", action="compare")
    )

    assert resolved.blocked
    assert resolved.block_reasons[-2:] == [
        "THESIS_COMPARE_FROM_VERSION_REQUIRED",
        "THESIS_COMPARE_TO_VERSION_REQUIRED",
    ]


def test_argv_values_are_not_shell_interpreted(catalog_path):
    dangerous = "600519; touch /tmp/should-not-exist"
    resolved = AgentRouter(catalog_path).resolve(request("analyze", asset=dangerous))

    assert resolved.argv == ["stock-analysis", "--market", "stock-review", "--symbol", dangerous]


def test_debug_input_accepts_only_explicit_fixture_syntax():
    parsed = parse_debug_input('/analyze 600519 depth=quick capabilities=["audit"]')

    assert parsed.command == "analyze"
    assert parsed.arguments == {
        "asset": "600519",
        "depth": "quick",
        "capabilities": ["audit"],
    }
    assert parsed.source["host"] == "debug-fixture"
    with pytest.raises(RequestError, match="explicit"):
        parse_debug_input("分析一下贵州茅台")


def test_run_writes_manifest_and_validates_output(catalog_path, tmp_path):
    host_request = request("snapshot", asset="600519")
    resolved = AgentRouter(catalog_path).resolve(host_request)
    manifest_path = tmp_path / "run_manifest.json"

    result, manifest = execute_workflow(
        host_request,
        resolved,
        manifest_path=manifest_path,
        executor=lambda argv: WorkflowResult(0, f"ran {argv[-1]}\n", ""),
    )

    assert result is not None
    assert manifest["status"] == "completed"
    assert manifest["output_validation"]["valid"]
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["execution_card"]["argv"] == resolved.argv


def test_run_rejects_output_missing_required_sections(catalog_path, tmp_path):
    host_request = request("move", asset="600519")
    resolved = AgentRouter(catalog_path).resolve(host_request)
    contract = dict(resolved.output_contract)
    contract["required_sections"] = ["confirmed_trigger", "unknown"]
    resolved = type(resolved)(**{**resolved.to_dict(), "output_contract": contract})

    _, manifest = execute_workflow(
        host_request,
        resolved,
        manifest_path=tmp_path / "run_manifest.json",
        executor=lambda argv: WorkflowResult(0, "unknown\n", ""),
    )

    assert manifest["status"] == "failed"
    assert manifest["output_validation"]["checks"][-2:] == [
        {"name": "section:confirmed_trigger", "passed": False},
        {"name": "section:unknown", "passed": True},
    ]


def test_app_dispatches_agent_route_with_structured_request(catalog_path, capsys):
    payload = json.dumps(
        {
            "schema_version": "2.0",
            "command": "analyze",
            "arguments": {"asset": "600519"},
        }
    )

    assert app.run(["agent", "--catalog", str(catalog_path), "route", "--request", payload]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["route"] == "standard"
    assert output["argv"][-1] == "600519"


def test_agent_run_hides_internal_stderr_and_manifest_path(monkeypatch, tmp_path, capsys):
    payload = json.dumps(
        {
            "schema_version": "2.0",
            "command": "snapshot",
            "arguments": {"asset": "600519"},
        }
    )
    monkeypatch.setattr(
        "stock_analysis.agent.cli.execute_workflow",
        lambda *args, **kwargs: (
            WorkflowResult(0, "# 个股速览\n\n研究结果。\n", "STOCK_ANALYSIS_WORKSPACE=/tmp/internal"),
            {"status": "completed"},
        ),
    )

    assert run_agent([
        "run",
        "--request",
        payload,
        "--manifest",
        str(tmp_path / "manifest.json"),
    ]) == 0

    captured = capsys.readouterr()
    assert "个股速览" in captured.out
    assert "STOCK_ANALYSIS_WORKSPACE" not in captured.out
    assert captured.err == ""


def test_agent_run_refuses_engineering_payload(monkeypatch, tmp_path, capsys):
    payload = json.dumps(
        {
            "schema_version": "2.0",
            "command": "snapshot",
            "arguments": {"asset": "600519"},
        }
    )
    monkeypatch.setattr(
        "stock_analysis.agent.cli.execute_workflow",
        lambda *args, **kwargs: (
            WorkflowResult(0, "RouteDecision 已通过", ""),
            {"status": "completed"},
        ),
    )

    assert run_agent([
        "run",
        "--request",
        payload,
        "--manifest",
        str(tmp_path / "manifest.json"),
    ]) == 1

    output = capsys.readouterr().out
    assert "RouteDecision" not in output
    assert "不会向用户展示工程数据" in output


def test_catalog_loader_rejects_duplicate_command_ids(tmp_path):
    path = Path(tmp_path) / "catalog.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "commands": [{"id": "analyze"}, {"id": "analyze"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unique"):
        load_catalog(path)
