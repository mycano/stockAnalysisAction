"""Data models for the HostRequest -> ResolvedRequest -> Workflow boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class HostRequest:
    """A structured request produced by a host integration."""

    # Plan §4: the host owns intent structuring; production routing receives no free text.
    schema_version: str
    command: str
    arguments: dict[str, Any]
    source: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> HostRequest:
        if not isinstance(value, Mapping):
            raise ValueError("HostRequest must be a JSON object")
        unexpected = set(value) - {"schema_version", "command", "arguments", "source", "request_id"}
        if unexpected:
            raise ValueError(f"HostRequest has unexpected fields: {', '.join(sorted(unexpected))}")
        schema_version = value.get("schema_version")
        command = value.get("command")
        arguments = value.get("arguments")
        source = value.get("source", {})
        request_id = value.get("request_id")
        if schema_version != "2.0":
            raise ValueError("HostRequest.schema_version must be '2.0'")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("HostRequest.command must be a non-empty string")
        if not isinstance(arguments, Mapping):
            raise ValueError("HostRequest.arguments must be a JSON object")
        if not isinstance(source, Mapping):
            raise ValueError("HostRequest.source must be a JSON object")
        unexpected_source = set(source) - {"host", "entrypoint", "locale"}
        if unexpected_source:
            raise ValueError(
                f"HostRequest.source has unexpected fields: {', '.join(sorted(unexpected_source))}"
            )
        if request_id is not None and (not isinstance(request_id, str) or not request_id.strip()):
            raise ValueError("HostRequest.request_id must be a non-empty string when provided")
        return cls(
            schema_version=schema_version,
            command=command.removeprefix("/"),
            arguments=dict(arguments),
            source=dict(source),
            request_id=request_id,
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.request_id is None:
            result.pop("request_id")
        return result


@dataclass(frozen=True)
class ResolvedRequest:
    """The deterministic decision consumed by the workflow execution layer."""

    schema_version: str
    command_id: str
    command: str
    route: str
    workflow_id: str
    arguments: dict[str, Any]
    argv: list[str]
    reason_codes: list[str]
    output_contract: dict[str, Any]
    blocked: bool
    block_reasons: list[str]
    request_id: str | None = None
    redirect: dict[str, Any] | None = None
    catalog_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.request_id is None:
            result.pop("request_id")
        return result

    @property
    def execution_card(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "route": self.route,
            "workflow_id": self.workflow_id,
            "reason_codes": list(self.reason_codes),
            "argv": list(self.argv),
            "output_contract": dict(self.output_contract),
            "blocked": self.blocked,
            "block_reasons": list(self.block_reasons),
            "redirect": dict(self.redirect) if self.redirect else None,
        }


# Compatibility name used by the protocol design. A route decision is the
# resolved request handed to the workflow layer; there is no second mutable model.
RouteDecision = ResolvedRequest
