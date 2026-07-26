"""Deterministic routing from structured host requests to workflow argv."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .catalog import AgentCatalog, load_catalog
from .models import HostRequest, ResolvedRequest


class RequestError(ValueError):
    """Raised when a host request cannot be parsed."""


_PLACEHOLDER = re.compile(r"^\{([a-zA-Z][a-zA-Z0-9_]*)\}$")
def load_host_request(value: str | Path | Mapping[str, Any]) -> HostRequest:
    if isinstance(value, Mapping):
        payload = value
    else:
        text = str(value)
        candidate = Path(text).expanduser()
        try:
            is_file = candidate.is_file()
        except OSError:
            is_file = False
        if is_file:
            try:
                text = candidate.read_text(encoding="utf-8")
            except OSError as exc:
                raise RequestError(f"cannot read HostRequest file: {exc}") from exc
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RequestError(f"HostRequest must be JSON or a JSON file: {exc}") from exc
    try:
        return HostRequest.from_mapping(payload)
    except ValueError as exc:
        raise RequestError(str(exc)) from exc


def parse_debug_input(value: str) -> HostRequest:
    """Parse the intentionally small debug/fixture syntax.

    This is deliberately not natural-language understanding. Accepted input is
    ``/command key=<json-or-string> ...`` with one optional positional asset.
    """

    import shlex

    try:
        tokens = shlex.split(value)
    except ValueError as exc:
        raise RequestError(f"invalid debug input: {exc}") from exc
    if not tokens:
        raise RequestError("debug --input must start with /command")
    command_token = tokens.pop(0)
    if not command_token.startswith("/") or len(command_token) == 1:
        raise RequestError("debug --input must use explicit '/command key=value' syntax")
    arguments: dict[str, Any] = {}
    for token in tokens:
        if "=" not in token:
            if "asset" in arguments:
                raise RequestError("debug --input allows only one positional asset")
            arguments["asset"] = token
            continue
        key, raw = token.split("=", 1)
        if not key or not key.replace("_", "").isalnum():
            raise RequestError(f"invalid debug argument name: {key}")
        try:
            arguments[key] = json.loads(raw)
        except json.JSONDecodeError:
            if raw.startswith("[") and raw.endswith("]"):
                arguments[key] = [
                    item.strip()
                    for item in raw[1:-1].split(",")
                    if item.strip()
                ]
            else:
                arguments[key] = raw
    return HostRequest(
        schema_version="2.0",
        command=command_token[1:],
        arguments=arguments,
        source={"host": "debug-fixture", "entrypoint": "--input"},
    )


class AgentRouter:
    """Catalog-backed deterministic router."""

    def __init__(self, catalog: AgentCatalog | str | Path | None = None):
        self.catalog = catalog if isinstance(catalog, AgentCatalog) else load_catalog(catalog)

    def resolve(self, request: HostRequest | Mapping[str, Any]) -> ResolvedRequest:
        # Plan §9: explicit parameters and required capabilities precede defaults.
        host_request = request if isinstance(request, HostRequest) else HostRequest.from_mapping(request)
        original = self.catalog.command(host_request.command)
        arguments = _apply_defaults(original, host_request.arguments)
        command_name = _command_name(original)
        if command_name == "analyze":
            arguments["_depth_explicit"] = "depth" in host_request.arguments
            arguments["_research_mode_explicit"] = "research_mode" in host_request.arguments
        route = _default_route(original)
        reasons = ["HOST_REQUEST_VALID"]
        blocks: list[str] = []
        _validate_required_supplied(original, host_request.arguments, blocks)
        _validate_safe_values(arguments, blocks)
        # Natural-language signals are consulted only after explicit routing fields.
        redirect_target, redirect_reason = (None, "")
        if not _has_explicit_routing_signal(command_name, host_request.arguments):
            redirect_target, redirect_reason = _catalog_redirect(original, arguments)
        if redirect_target:
            reasons.append(redirect_reason)
        else:
            handler = getattr(self, f"_resolve_{command_name.replace('-', '_')}", None)
            if handler is not None:
                route, redirect_target = handler(arguments, route, reasons, blocks)
        effective = original
        redirect = None
        if redirect_target:
            effective = self.catalog.command(redirect_target)
            redirect = {
                "from": command_name,
                "to": _command_name(effective),
                "reason_code": redirect_reason or reasons[-1],
            }
            arguments = _apply_defaults(effective, arguments)
            _validate_safe_values(arguments, blocks)
            route = self._resolve_redirected(effective, arguments, reasons, blocks)

        _validate_catalog_schema(effective, arguments, blocks)
        workflow = _select_workflow(effective, route)
        workflow_id = str(workflow.get("workflow_id") or f"{_command_name(effective)}-{route}")
        argv, missing = _render_argv(
            workflow.get("argv_template", workflow.get("argv")),
            arguments,
        )
        argv.extend(_render_optional_argv(workflow.get("optional_argv"), arguments))
        for name in missing:
            _block(blocks, f"MISSING_ARGV_VALUE:{name}")
        output_contract = _contract_object(
            workflow.get("output_contract", effective.get("output_contract"))
        )
        _enforce_output_contract(_command_name(effective), arguments, output_contract)
        if host_request.source.get("host") == "debug-fixture":
            reasons.append("DEBUG_FIXTURE_INPUT")

        return ResolvedRequest(
            schema_version="2.0",
            request_id=host_request.request_id,
            command_id=str(effective.get("command_id") or effective.get("id") or _command_name(effective)),
            command=_command_name(effective),
            route=route,
            workflow_id=workflow_id,
            arguments=arguments,
            argv=argv,
            reason_codes=_dedupe(reasons),
            output_contract=output_contract,
            blocked=bool(blocks),
            block_reasons=_dedupe(blocks),
            redirect=redirect,
            catalog_hash=self.catalog.catalog_hash,
        )

    def _resolve_redirected(
        self,
        command: dict[str, Any],
        arguments: dict[str, Any],
        reasons: list[str],
        blocks: list[str],
    ) -> str:
        name = _command_name(command)
        route = _default_route(command)
        handler = getattr(self, f"_resolve_{name.replace('-', '_')}", None)
        if handler is not None:
            route, nested_redirect = handler(arguments, route, reasons, blocks)
            if nested_redirect:
                _block(blocks, "NESTED_REDIRECT_NOT_ALLOWED")
        return route

    def _resolve_market(
        self,
        args: dict[str, Any],
        route: str,
        reasons: list[str],
        blocks: list[str],
    ) -> tuple[str, str | None]:
        del blocks
        market = str(args.get("market") or args.get("scope") or "").lower()
        session = str(args.get("session") or "").lower()
        if market in {"global", "world"}:
            reason = "MARKET_GLOBAL_EXPLICIT" if args.get("market") == "global" else "MARKET_GLOBAL_SCOPE"
            reasons.append(reason)
            route = _available_route(self.catalog.command("market"), "global", route)
        elif session in {"pre-market", "open", "intraday", "after-market", "close"}:
            reasons.append("MARKET_SESSION_ROUTE")
            route = _available_route(self.catalog.command("market"), session, route)
        else:
            reasons.append(_route_reason(self.catalog.command("market"), route, "MARKET_DEFAULT_ROUTE"))
        return route, None

    def _resolve_snapshot(
        self,
        args: dict[str, Any],
        route: str,
        reasons: list[str],
        blocks: list[str],
    ) -> tuple[str, str | None]:
        _require_asset(args, blocks)
        asset_type = str(args.get("asset_type") or "auto").lower()
        if asset_type == "fund":
            route = "fund"
            reasons.append(_route_reason(self.catalog.command("snapshot"), route, "SNAPSHOT_FUND"))
        else:
            route = "company"
            reasons.append(_route_reason(self.catalog.command("snapshot"), route, "SNAPSHOT_FACTS_ONLY"))
        return route, None

    def _resolve_analyze(
        self,
        args: dict[str, Any],
        route: str,
        reasons: list[str],
        blocks: list[str],
    ) -> tuple[str, str | None]:
        _require_asset(args, blocks)
        research_mode_explicit = bool(args.pop("_research_mode_explicit", False))
        requested_research_mode = str(args.get("research_mode") or "general").lower()
        requested_lenses = [
            str(item).strip()
            for item in (args.get("lenses") or [])
            if str(item).strip()
        ]
        single_lens = str(args.get("lens") or "").strip()
        lens_signal = bool(
            research_mode_explicit and requested_research_mode == "lens"
            or args.get("lens_mode")
            or single_lens
            or requested_lenses
        )
        if lens_signal:
            lens_mode = str(args.get("lens_mode") or "").lower()
            if not lens_mode:
                lens_mode = "single" if single_lens or len(requested_lenses) == 1 else "parallel"
            if lens_mode not in {"single", "parallel", "adversarial", "committee"}:
                _block(blocks, "INVALID_LENS_MODE")
            selected_count = len(requested_lenses) + (1 if single_lens and not requested_lenses else 0)
            if lens_mode == "single" and selected_count != 1:
                _block(blocks, "SINGLE_LENS_REQUIRES_ONE_FRAMEWORK")
            if lens_mode == "parallel" and selected_count < 2:
                _block(blocks, "PARALLEL_LENS_REQUIRES_MULTIPLE_FRAMEWORKS")
            if lens_mode == "adversarial" and selected_count != 2:
                _block(blocks, "ADVERSARIAL_LENS_REQUIRES_TWO_FRAMEWORKS")
            args["research_mode"] = "lens"
            args["general_mode"] = None
            args["lens_mode"] = lens_mode
            if requested_lenses:
                args["lenses_csv"] = ",".join(requested_lenses)
            route = "lens"
            reasons.append("ANALYZE_LENS_EXPLICIT")
            return route, None
        if requested_research_mode not in {"general", "lens"}:
            _block(blocks, "INVALID_RESEARCH_MODE")
        args["research_mode"] = "general"
        args["lens_mode"] = None
        args["lenses"] = []
        requested = str(args.get("depth") or "").lower()
        depth_explicit = bool(args.pop("_depth_explicit", False))
        capabilities = _normalized_values(args.get("capabilities"))
        routing = self.catalog.command("analyze").get("routing")
        configured = (
            routing.get("deep_only_capabilities")
            if isinstance(routing, Mapping)
            else []
        )
        deep_required = bool(capabilities & _normalized_values(configured))
        if deep_required:
            route = "deep"
            args["depth"] = "deep"
            args["general_mode"] = "deep"
            reasons.append("ANALYZE_DEEP_CAPABILITY")
        elif requested in {"quick", "standard", "deep"}:
            route = requested
            args["general_mode"] = requested
            reasons.append(
                f"ANALYZE_{requested.upper()}_EXPLICIT"
                if depth_explicit
                else "ANALYZE_STANDARD_DEFAULT"
            )
        elif requested:
            _block(blocks, "INVALID_ANALYZE_DEPTH")
        else:
            route = "standard"
            args["depth"] = "standard"
            args["general_mode"] = "standard"
            reasons.append("ANALYZE_STANDARD_DEFAULT")
        if route == "quick":
            args["quick_market"] = "fund" if args.get("asset_type") == "fund" else "stock-review"
        return route, None

    def _resolve_earnings(
        self,
        args: dict[str, Any],
        route: str,
        reasons: list[str],
        blocks: list[str],
    ) -> tuple[str, str | None]:
        _require_asset(args, blocks)
        mode = str(args.get("mode") or "standard").lower()
        if mode not in {"facts", "standard", "thesis-impact"}:
            _block(blocks, "INVALID_EARNINGS_MODE")
        else:
            route = mode
            args["mode"] = mode
            reasons.append(
                _route_reason(
                    self.catalog.command("earnings"),
                    route,
                    f"EARNINGS_MODE_{mode.upper().replace('-', '_')}",
                )
            )
        if not args.get("period") and not args.get("fiscal_period"):
            reasons.append("EARNINGS_PERIOD_UNSPECIFIED")
        if not args.get("comparison_period"):
            reasons.append("EARNINGS_COMPARISON_UNSPECIFIED")
        return route, None

    def _resolve_move(
        self,
        args: dict[str, Any],
        route: str,
        reasons: list[str],
        blocks: list[str],
    ) -> tuple[str, str | None]:
        _require_asset(args, blocks)
        window = str(args.get("window_type") or args.get("window") or "single-session").lower()
        aliases = {
            "day": "single-session",
            "single": "single-session",
            "single-day": "single-session",
            "multi": "multi-session",
            "multi-day": "multi-session",
            "event": "event-window",
        }
        window = aliases.get(window, window)
        if window not in {"single-session", "multi-session", "event-window"}:
            _block(blocks, "INVALID_MOVE_WINDOW")
        else:
            route = window
            args["window_type"] = window
            reasons.append(
                _route_reason(
                    self.catalog.command("move"),
                    route,
                    f"MOVE_WINDOW_{window.upper().replace('-', '_')}",
                )
            )
        if window == "multi-session":
            if not args.get("start_date"):
                _block(blocks, "MOVE_START_DATE_REQUIRED")
            if not args.get("end_date"):
                _block(blocks, "MOVE_END_DATE_REQUIRED")
        elif window == "event-window":
            if not args.get("event"):
                _block(blocks, "MOVE_EVENT_REQUIRED")
            if not args.get("end_date"):
                _block(blocks, "MOVE_END_DATE_REQUIRED")
        reasons.append("MOVE_CAUSAL_BOUNDARY_ENFORCED")
        return route, None

    def _resolve_screen(
        self,
        args: dict[str, Any],
        route: str,
        reasons: list[str],
        blocks: list[str],
    ) -> tuple[str, str | None]:
        if not args.get("fiscal_year") and str(args.get("period") or "").isdigit():
            args["fiscal_year"] = int(args["period"])
        filters = args.get("filters")
        _validate_screen_structures(args, blocks)
        structured = (
            bool(args.get("universe_file") or args.get("universe"))
            and bool(args.get("fiscal_year") or args.get("period"))
            and isinstance(filters, list)
            and bool(filters)
            and bool(args.get("sort"))
            and args.get("limit") is not None
        )
        mode = str(args.get("mode") or ("execute" if structured else "explore")).lower()
        if mode == "explore":
            route = "explore"
            reasons.append("SCREEN_EXPLORE_ROUTE")
            _block(
                blocks,
                "SCREEN_CONFIRMATION_REQUIRED"
                if not args.get("confirmed")
                else "SCREEN_EXECUTION_MODE_REQUIRED",
            )
        elif not structured:
            route = "explore"
            reasons.append("SCREEN_EXPLORE_ROUTE")
            _block(blocks, "SCREEN_STRUCTURED_CRITERIA_REQUIRED")
            if not args.get("confirmed"):
                _block(blocks, "SCREEN_CONFIRMATION_REQUIRED")
        elif not args.get("confirmed"):
            route = "explore"
            reasons.append("SCREEN_AWAITING_CONFIRMATION")
            _block(blocks, "SCREEN_CONFIRMATION_REQUIRED")
        else:
            route = "execute"
            reasons.append(
                _route_reason(
                    self.catalog.command("screen"),
                    route,
                    "SCREEN_STRUCTURED_EXECUTION",
                )
            )
        return route, None

    def _resolve_portfolio(
        self,
        args: dict[str, Any],
        route: str,
        reasons: list[str],
        blocks: list[str],
    ) -> tuple[str, str | None]:
        action = str(args.get("action") or "review").lower()
        if action not in {"review", "import", "stress", "compare"}:
            _block(blocks, "INVALID_PORTFOLIO_ACTION")
        else:
            route = action
            args["action"] = action
            reasons.append(
                _route_reason(
                    self.catalog.command("portfolio"),
                    route,
                    f"PORTFOLIO_ACTION_{action.upper()}",
                )
            )
        status = str(args.get("holdings_status") or "missing").lower()
        args["holdings_status"] = status
        if status not in {"complete", "partial", "stale", "missing"}:
            _block(blocks, "INVALID_HOLDINGS_STATUS")
        elif status != "complete":
            reasons.append(f"PORTFOLIO_HOLDINGS_{status.upper()}")
            if action in {"stress", "compare"}:
                _block(blocks, "PORTFOLIO_COMPLETE_CONCLUSION_PROHIBITED")
        else:
            reasons.append("PORTFOLIO_HOLDINGS_COMPLETE")
        if action == "import" and not args.get("holdings_json"):
            _block(blocks, "PORTFOLIO_IMPORT_REQUIRES_HOLDINGS")
        return route, None

    def _resolve_thesis(
        self,
        args: dict[str, Any],
        route: str,
        reasons: list[str],
        blocks: list[str],
    ) -> tuple[str, str | None]:
        _require_asset(args, blocks)
        action = str(args.get("action") or "").lower()
        if not action:
            _block(blocks, "THESIS_ACTION_REQUIRED")
            return route, None
        if action not in {"create", "review", "update", "compare", "invalidate"}:
            _block(blocks, "INVALID_THESIS_ACTION")
            return route, None
        route = action
        args["action"] = action
        if action == "compare":
            if not args.get("from_version"):
                _block(blocks, "THESIS_COMPARE_FROM_VERSION_REQUIRED")
            if not args.get("to_version"):
                _block(blocks, "THESIS_COMPARE_TO_VERSION_REQUIRED")
        elif action == "invalidate" and not args.get("reason"):
            _block(blocks, "THESIS_INVALIDATION_REASON_REQUIRED")
        reasons.extend(
            [
                _route_reason(
                    self.catalog.command("thesis"),
                    route,
                    f"THESIS_ACTION_{action.upper()}",
                ),
                "THESIS_HISTORY_APPEND_ONLY",
            ]
        )
        return route, None


def _command_name(command: Mapping[str, Any]) -> str:
    return str(command.get("command") or command.get("id") or command.get("command_id") or "").removeprefix("/")


def _catalog_redirect(
    command: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> tuple[str | None, str]:
    intent = _intent(arguments)
    for redirect in command.get("redirects") or []:
        if not isinstance(redirect, Mapping):
            continue
        expected = _normalized_values(
            redirect.get("when_intents") or redirect.get("when_intent")
        )
        required_capabilities = _normalized_values(redirect.get("when_any_capability"))
        matches = bool(expected and intent in expected)
        matches = matches or bool(
            required_capabilities
            and required_capabilities & _normalized_values(arguments.get("capabilities"))
        )
        matches = matches or bool(redirect.get("when_asset") and arguments.get("asset"))
        if matches:
            return (
                str(redirect.get("command") or "") or None,
                str(redirect.get("reason_code") or "CATALOG_REDIRECT"),
            )
    return None, ""


def _has_explicit_routing_signal(command: str, arguments: Mapping[str, Any]) -> bool:
    """Implement Plan §9 precedence: explicit routing parameters outrank NL signals."""
    fields = {
        "market": {"market", "scope", "session", "depth"},
        "snapshot": {"asset_type"},
        "analyze": {
            "asset_type",
            "depth",
            "capabilities",
            "research_mode",
            "general_mode",
            "lens_mode",
            "lens",
            "lenses",
        },
        "earnings": {"mode", "period", "fiscal_period", "comparison_period", "depth"},
        "move": {"window_type", "window", "start_date", "end_date", "event", "depth"},
        "screen": {"mode", "filters", "sort", "confirmed", "depth"},
        "portfolio": {"action", "holdings_status", "depth"},
        "thesis": {"action", "from_version", "to_version", "reason"},
    }
    return any(field in arguments for field in fields.get(command, set()))


def _route_reason(command: Mapping[str, Any], route: str, fallback: str) -> str:
    routing = command.get("routing")
    rules = routing.get("rules") if isinstance(routing, Mapping) else None
    for rule in rules or []:
        if isinstance(rule, Mapping) and rule.get("route") == route and rule.get("reason_code"):
            return str(rule["reason_code"])
    return fallback


def _contract_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        return {"description": value, "stdout_required": True, "required_artifacts": []}
    return {}


def _apply_defaults(command: Mapping[str, Any], supplied: Mapping[str, Any]) -> dict[str, Any]:
    defaults = command.get("defaults")
    result = dict(defaults) if isinstance(defaults, Mapping) else {}
    result.update(supplied)
    if "symbol" in result and "asset" not in result:
        result["asset"] = result["symbol"]
    return result


def _default_route(command: Mapping[str, Any]) -> str:
    routing = command.get("routing")
    if isinstance(routing, Mapping) and routing.get("default_route"):
        return str(routing["default_route"])
    defaults = command.get("defaults")
    if isinstance(defaults, Mapping):
        for name in ("depth", "mode", "action", "window_type"):
            if defaults.get(name):
                return str(defaults[name])
    workflows = command.get("workflows")
    if isinstance(workflows, Mapping) and workflows:
        return str(next(iter(workflows)))
    return "default"


def _available_route(command: Mapping[str, Any], requested: str, fallback: str) -> str:
    workflows = command.get("workflows")
    return requested if isinstance(workflows, Mapping) and requested in workflows else fallback


def _select_workflow(command: Mapping[str, Any], route: str) -> dict[str, Any]:
    workflows = command.get("workflows")
    if isinstance(workflows, Mapping):
        value = workflows.get(route)
        if isinstance(value, dict):
            return value
        default = workflows.get(_default_route(command))
        if isinstance(default, dict):
            return default
        for item in workflows.values():
            if isinstance(item, dict):
                return item
    if isinstance(workflows, list):
        for item in workflows:
            if isinstance(item, dict) and str(item.get("route") or "") == route:
                return item
        for item in workflows:
            if isinstance(item, dict):
                return item
    return {"workflow_id": f"{_command_name(command)}-{route}", "argv": []}


def _render_argv(template: Any, arguments: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    if not isinstance(template, list):
        return [], []
    rendered: list[str] = []
    missing: list[str] = []
    for raw in template:
        if not isinstance(raw, str):
            continue
        match = _PLACEHOLDER.match(raw)
        if not match:
            rendered.append(raw)
            continue
        name = match.group(1)
        value = arguments.get(name)
        if value is None or value == "" or value == []:
            missing.append(name)
            if rendered and rendered[-1].startswith("-"):
                rendered.pop()
            continue
        if isinstance(value, list):
            flag = rendered.pop() if rendered and rendered[-1].startswith("-") else None
            for item in value:
                if flag:
                    rendered.append(flag)
                rendered.append(_argv_value(item, name=name))
        elif isinstance(value, bool):
            if not value and rendered and rendered[-1].startswith("-"):
                rendered.pop()
        else:
            rendered.append(_argv_value(value, name=name))
    return rendered, missing


def _render_optional_argv(optional: Any, arguments: Mapping[str, Any]) -> list[str]:
    if not isinstance(optional, Mapping):
        return []
    rendered: list[str] = []
    for name, template in optional.items():
        if arguments.get(str(name)) in (None, "", [], False):
            continue
        tokens = template if isinstance(template, list) else [template]
        values, _ = _render_argv(tokens, arguments)
        rendered.extend(values)
    return rendered


def _argv_value(value: Any, *, name: str | None = None) -> str:
    if name == "filters" and isinstance(value, Mapping):
        field = value.get("field")
        operator = value.get("operator") or value.get("op")
        filter_value = value.get("value")
        if field and operator and filter_value is not None:
            unit = "%" if value.get("unit") == "percent" else ""
            return f"{field}:{operator}:{filter_value}{unit}"
    if name == "sort" and isinstance(value, Mapping):
        field = value.get("field")
        direction = value.get("direction") or value.get("order")
        if field and direction:
            return f"{field}:{direction}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _validate_catalog_schema(command: Mapping[str, Any], arguments: Mapping[str, Any], blocks: list[str]) -> None:
    schema = command.get("request_schema")
    if not isinstance(schema, Mapping):
        return
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return
    for name, spec in properties.items():
        if name not in arguments or not isinstance(spec, Mapping):
            continue
        value = arguments[name]
        if value in ("", []) and name in set(schema.get("required") or []):
            continue
        if _command_name(command) == "screen" and name == "filters" and value == []:
            continue
        expected = spec.get("type")
        expected_types = expected if isinstance(expected, list) else [expected]
        valid = expected is None or any(
            _matches_json_type(value, item) for item in expected_types if item
        )
        if not valid:
            raise RequestError(f"INVALID_ARGUMENT_TYPE:{name}")
        allowed = spec.get("enum")
        if isinstance(allowed, list) and value not in allowed:
            raise RequestError(f"INVALID_ARGUMENT_VALUE:{name}")
        if isinstance(value, str):
            if spec.get("minLength") is not None and len(value) < int(spec["minLength"]):
                raise RequestError(f"INVALID_ARGUMENT_LENGTH:{name}")
            if spec.get("maxLength") is not None and len(value) > int(spec["maxLength"]):
                raise RequestError(f"INVALID_ARGUMENT_LENGTH:{name}")
            if spec.get("pattern") and re.fullmatch(str(spec["pattern"]), value) is None:
                raise RequestError(f"INVALID_ARGUMENT_PATTERN:{name}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if spec.get("minimum") is not None and value < spec["minimum"]:
                raise RequestError(f"ARGUMENT_BELOW_MINIMUM:{name}")
            if spec.get("maximum") is not None and value > spec["maximum"]:
                raise RequestError(f"ARGUMENT_ABOVE_MAXIMUM:{name}")
        if isinstance(value, list):
            if spec.get("minItems") is not None and len(value) < int(spec["minItems"]):
                raise RequestError(f"TOO_FEW_ARGUMENT_ITEMS:{name}")
            if spec.get("maxItems") is not None and len(value) > int(spec["maxItems"]):
                raise RequestError(f"TOO_MANY_ARGUMENT_ITEMS:{name}")
            if spec.get("uniqueItems"):
                serialized = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
                if len(serialized) != len(set(serialized)):
                    raise RequestError(f"DUPLICATE_ARGUMENT_ITEMS:{name}")


def _validate_required_supplied(
    command: Mapping[str, Any],
    supplied: Mapping[str, Any],
    blocks: list[str],
) -> None:
    schema = command.get("request_schema")
    if not isinstance(schema, Mapping):
        return
    for name in schema.get("required") or []:
        if supplied.get(str(name)) in (None, "", []):
            _block(blocks, f"MISSING_REQUIRED_ARGUMENT:{name}")


def _validate_safe_values(arguments: Mapping[str, Any], blocks: list[str]) -> None:
    asset = arguments.get("asset")
    if isinstance(asset, str) and _unsafe_text(asset):
        _block(blocks, "UNSAFE_ASSET")
    universe = arguments.get("universe_file")
    if isinstance(universe, str) and (".." in Path(universe).parts or _unsafe_text(universe)):
        _block(blocks, "UNSAFE_UNIVERSE_PATH")
    holdings = arguments.get("holdings_json")
    if isinstance(holdings, str) and _unsafe_text(holdings):
        _block(blocks, "UNSAFE_HOLDINGS_INPUT")
    filters = arguments.get("filters")
    if isinstance(filters, list):
        for index, item in enumerate(filters):
            if isinstance(item, Mapping) and _unsafe_text(str(item.get("field") or "")):
                _block(blocks, f"UNSAFE_SCREEN_FILTER:{index}")


def _unsafe_text(value: str) -> bool:
    return (
        any(token in value for token in (";", "`", "$(", "\x00", "\n", "\r"))
        or ".." in Path(value).parts
    )


def _matches_json_type(value: Any, expected: Any) -> bool:
    return {
        "array": isinstance(value, list),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "object": isinstance(value, Mapping),
        "string": isinstance(value, str),
    }.get(str(expected), True)


def _validate_screen_structures(arguments: Mapping[str, Any], blocks: list[str]) -> None:
    filters = arguments.get("filters")
    if isinstance(filters, list):
        for index, item in enumerate(filters):
            if isinstance(item, str):
                continue
            if not isinstance(item, Mapping):
                _block(blocks, f"INVALID_SCREEN_FILTER:{index}")
                continue
            required = {"field", "operator", "value", "unit", "missing"}
            if not required.issubset(item):
                _block(blocks, f"INCOMPLETE_SCREEN_FILTER:{index}")
            if item.get("operator") not in {"gt", "gte", "lt", "lte", "eq", "neq"}:
                _block(blocks, f"INVALID_SCREEN_FILTER_OPERATOR:{index}")
            if item.get("unit") not in {"number", "percent", "currency", "ratio"}:
                _block(blocks, f"INVALID_SCREEN_FILTER_UNIT:{index}")
            if item.get("missing") not in {"unknown", "exclude"}:
                _block(blocks, f"INVALID_SCREEN_MISSING_POLICY:{index}")
            if not isinstance(item.get("value"), (int, float)) or isinstance(item.get("value"), bool):
                _block(blocks, f"INVALID_SCREEN_FILTER_VALUE:{index}")
    sort = arguments.get("sort")
    if sort is not None and (
        not isinstance(sort, Mapping)
        or not sort.get("field")
        or sort.get("direction") not in {"asc", "desc"}
    ):
        _block(blocks, "INVALID_SCREEN_SORT")


def _enforce_output_contract(command: str, arguments: Mapping[str, Any], contract: dict[str, Any]) -> None:
    if command == "move":
        contract.setdefault(
            "causal_categories",
            [
                "confirmed_trigger",
                "plausibly_related",
                "market_wide_factor",
                "unsupported_speculation",
                "unknown",
            ],
        )
        contract.setdefault("causal_claims_must_be_evidence_backed", True)
    elif command == "portfolio":
        contract["holdings_status"] = arguments.get("holdings_status", "missing")
        contract["complete_conclusion_allowed"] = arguments.get("holdings_status") == "complete"
    elif command == "thesis":
        contract.setdefault("history_mode", "append_only")
        contract.setdefault("silent_overwrite", False)
    elif command == "snapshot":
        contract.setdefault("facts_only", True)


def _intent(arguments: Mapping[str, Any]) -> str:
    return str(arguments.get("intent") or arguments.get("task") or "").strip().lower().replace("_", "-")


def _normalized_values(value: Any) -> set[str]:
    values: Iterable[Any] = value if isinstance(value, list) else [value] if value else []
    return {str(item).strip().lower().replace("_", "-") for item in values}


def _require_asset(arguments: Mapping[str, Any], blocks: list[str]) -> None:
    if not arguments.get("asset"):
        _block(blocks, "ASSET_REQUIRED")


def _block(blocks: list[str], reason: str) -> None:
    if reason not in blocks:
        blocks.append(reason)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
