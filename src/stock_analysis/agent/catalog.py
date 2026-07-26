"""Loading and validating the canonical agent entrypoint catalog."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CatalogError(ValueError):
    """Raised when the canonical protocol catalog is unavailable or invalid."""


@dataclass(frozen=True)
class AgentCatalog:
    path: Path
    payload: dict[str, Any]
    catalog_hash: str

    @property
    def schema_version(self) -> str:
        return str(self.payload.get("schema_version") or "2.0")

    @property
    def commands(self) -> list[dict[str, Any]]:
        commands = self.payload.get("commands")
        if not isinstance(commands, list):
            raise CatalogError("catalog.commands must be an array")
        return [item for item in commands if isinstance(item, dict)]

    def command(self, name: str) -> dict[str, Any]:
        normalized = name.removeprefix("/")
        for item in self.commands:
            names = {
                str(item.get("id") or ""),
                str(item.get("command_id") or ""),
                str(item.get("command") or "").removeprefix("/"),
            }
            if normalized in names:
                return item
        raise CatalogError(f"unknown agent command: {name}")


def default_catalog_path() -> Path:
    override = os.environ.get("STOCK_ANALYSIS_AGENT_CATALOG")
    if override:
        return Path(override).expanduser()
    candidates = [
        Path.cwd() / "agent-entrypoints" / "catalog.json",
        Path(__file__).resolve().parents[3] / "agent-entrypoints" / "catalog.json",
        Path(__file__).resolve().parent / "entrypoints" / "catalog.json",
        Path(__file__).resolve().parent / "catalog.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def load_catalog(path: str | Path | None = None) -> AgentCatalog:
    catalog_path = Path(path).expanduser() if path is not None else default_catalog_path()
    try:
        raw = catalog_path.read_bytes()
        payload = json.loads(raw)
    except OSError as exc:
        raise CatalogError(f"cannot read agent catalog {catalog_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"invalid agent catalog JSON {catalog_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CatalogError("agent catalog must be a JSON object")
    if payload.get("schema_version") != "2.0":
        raise CatalogError("agent catalog schema_version must be '2.0'")
    commands = payload.get("commands")
    if not isinstance(commands, list) or not commands:
        raise CatalogError("agent catalog must define commands")
    identifiers = [str(item.get("id") or item.get("command_id") or "") for item in commands if isinstance(item, dict)]
    if any(not item for item in identifiers) or len(identifiers) != len(set(identifiers)):
        raise CatalogError("agent catalog command ids must be non-empty and unique")
    return AgentCatalog(
        path=catalog_path.resolve(),
        payload=payload,
        catalog_hash=f"sha256:{hashlib.sha256(raw).hexdigest()}",
    )
