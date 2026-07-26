#!/usr/bin/env python3
"""Install generated stock-analysis entrypoints without overwriting user files."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PACKAGED_ASSET_ROOT = Path(__file__).resolve().parent / "entrypoints"
ROOT = (
    REPOSITORY_ROOT
    if (REPOSITORY_ROOT / "agent-entrypoints" / "catalog.json").is_file()
    else PACKAGED_ASSET_ROOT
)
MANIFEST_NAME = "agent-install-manifest.json"
MANAGED_BY = "stock-analysis-agent-installer"
MANIFEST_SCHEMA_VERSION = 1
GENERATED_SCHEMA_VERSION = "2.0"
HOSTS = ("codex", "claude")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class InstallError(RuntimeError):
    """An installation cannot proceed without risking user-owned data."""


@dataclass(frozen=True)
class Artifact:
    host: str
    source: Path
    relative_destination: Path
    kind: str
    alias: bool = False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_path(path: Path) -> str:
    if path.is_symlink():
        raise InstallError(f"不支持符号链接入口：{path}")
    if path.is_file():
        return _sha256_file(path)
    if not path.is_dir():
        raise InstallError(f"入口不存在或类型不受支持：{path}")
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob("*") if item.is_file() or item.is_symlink())
    for item in files:
        if item.is_symlink():
            raise InstallError(f"入口目录包含符号链接：{item}")
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(_sha256_file(item)))
    return digest.hexdigest()


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def _safe_relative_path(raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise InstallError("manifest 中存在无效路径")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise InstallError(f"manifest 路径越界：{raw}")
    return path


def _catalog_path(root: Path) -> Path:
    repository_path = root / "agent-entrypoints" / "catalog.json"
    return repository_path if repository_path.is_file() else root / "catalog.json"


def _catalog_entrypoints(catalog_path: Path) -> tuple[dict[str, tuple[str, str, bool]], str]:
    try:
        raw = catalog_path.read_bytes()
        catalog = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise InstallError(f"无法读取 canonical catalog：{catalog_path}: {error}") from error
    required_top_level = {
        "schema_version",
        "protocol_version",
        "protocol_id",
        "architecture",
        "commands",
        "compatibility",
    }
    if not isinstance(catalog, dict) or not required_top_level.issubset(catalog):
        raise InstallError("canonical catalog 缺少 v2 必需字段")
    commands = catalog["commands"]
    compatibility = catalog["compatibility"]
    if not isinstance(commands, list) or not isinstance(compatibility, dict):
        raise InstallError("canonical catalog 的 commands/compatibility 类型无效")
    if not isinstance(compatibility.get("legacy_entrypoints"), list) or not isinstance(
        compatibility.get("operational_entrypoints"), list
    ):
        raise InstallError("canonical catalog 缺少 compatibility entrypoints")
    command_ids: dict[str, str] = {}
    for command in commands:
        if not isinstance(command, dict):
            raise InstallError("canonical catalog command 必须是对象")
        command_id = command.get("command_id")
        entrypoint_id = command.get("id")
        if not isinstance(command_id, str) or not command_id:
            raise InstallError("canonical catalog command_id 无效")
        if not isinstance(entrypoint_id, str) or not entrypoint_id:
            raise InstallError("canonical catalog command id 无效")
        if entrypoint_id in command_ids:
            raise InstallError(f"canonical catalog command id 重复：{entrypoint_id}")
        command_ids[entrypoint_id] = command_id
    if len(command_ids) != 8:
        raise InstallError(f"canonical catalog 必须定义八个正式命令，实际为 {len(command_ids)}")
    entrypoints = {
        entrypoint_id: (command_id, entrypoint_id, True)
        for entrypoint_id, command_id in command_ids.items()
    }
    for legacy in compatibility["legacy_entrypoints"]:
        if not isinstance(legacy, dict):
            raise InstallError("canonical catalog legacy_entrypoint 必须是对象")
        entrypoint_id = legacy.get("id")
        target_id = legacy.get("command")
        if not isinstance(entrypoint_id, str) or target_id not in command_ids:
            raise InstallError("canonical catalog legacy_entrypoint 无效")
        if entrypoint_id in entrypoints:
            raise InstallError(f"canonical catalog entrypoint id 重复：{entrypoint_id}")
        entrypoints[entrypoint_id] = (command_ids[target_id], target_id, False)
    for operational in compatibility["operational_entrypoints"]:
        if not isinstance(operational, dict):
            raise InstallError("canonical catalog operational_entrypoint 必须是对象")
        entrypoint_id = operational.get("id")
        command_id = operational.get("command_id")
        if not isinstance(entrypoint_id, str) or not isinstance(command_id, str):
            raise InstallError("canonical catalog operational_entrypoint 无效")
        if entrypoint_id in entrypoints:
            raise InstallError(f"canonical catalog entrypoint id 重复：{entrypoint_id}")
        entrypoints[entrypoint_id] = (command_id, entrypoint_id, False)
    return entrypoints, f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _verify_generated_entrypoints(
    root: Path, entrypoints: dict[str, tuple[str, str, bool]], catalog_hash: str
) -> None:
    for entrypoint_id, (command_id, routed_id, is_formal) in sorted(entrypoints.items()):
        skill_directory = _safe_stem(entrypoint_id) if is_formal else entrypoint_id
        paths = (
            root / "codex-skills" / skill_directory / "SKILL.md",
            root / "codex-prompts" / f"{entrypoint_id}.md",
            root / "claude-commands" / f"{entrypoint_id}.md",
        )
        for path in paths:
            if not path.is_file():
                raise InstallError(f"缺少 catalog 命令的生成入口：{path}")
            metadata = _frontmatter(path)
            expected = {
                "managed_by": "stock-analysis",
                "schema_version": GENERATED_SCHEMA_VERSION,
                "command_id": command_id,
                "catalog_hash": catalog_hash,
                "x-stock-analysis-managed": "true",
                "x-stock-analysis-schema": "agent-entrypoint/v2",
                "x-stock-analysis-command": routed_id,
                "x-stock-analysis-catalog-hash": catalog_hash,
            }
            mismatches = [
                f"{key}={metadata.get(key)!r}"
                for key, value in expected.items()
                if metadata.get(key) != value
            ]
            if mismatches:
                raise InstallError(f"生成入口 metadata 无效：{path} ({', '.join(mismatches)})")


def _verify_protocol_schemas(root: Path) -> None:
    directory = root / "agent-entrypoints" / "schemas"
    if not directory.is_dir():
        directory = root / "schemas"
    required = {
        "host-request.schema.json",
        "resolved-request.schema.json",
        "route-decision.schema.json",
        "filter.schema.json",
        "sort.schema.json",
    }
    documents: dict[str, dict[str, Any]] = {}
    for name in sorted(required):
        path = directory / name
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise InstallError(f"协议 schema 不可用：{path}: {error}") from error
        if not isinstance(document, dict):
            raise InstallError(f"协议 schema 必须是 JSON 对象：{path}")
        documents[name] = document
    host = documents["host-request.schema.json"]
    resolved = documents["resolved-request.schema.json"]
    if host.get("properties", {}).get("schema_version", {}).get("const") != "2.0":
        raise InstallError("HostRequest schema_version 与 agent-entrypoint/v2 不一致")
    commands = host.get("properties", {}).get("command", {}).get("enum")
    if not isinstance(commands, list) or len(commands) != 8:
        raise InstallError("HostRequest schema 必须声明八个正式命令")
    resolved_required = set(resolved.get("required") or [])
    if not {"catalog_hash", "argv", "output_contract", "blocked"} <= resolved_required:
        raise InstallError("ResolvedRequest schema 缺少运行协议必需字段")


def _safe_stem(stem: str) -> str:
    return stem if stem.startswith("stock-analysis-") else f"stock-analysis-{stem}"


def _artifacts(
    root: Path,
    selected_hosts: Iterable[str],
    entrypoints: dict[str, tuple[str, str, bool]],
) -> dict[str, list[Artifact]]:
    selected = set(selected_hosts)
    result: dict[str, list[Artifact]] = {host: [] for host in selected}
    if "codex" in selected:
        skill_sources = [
            root / "codex-skills" / (_safe_stem(entrypoint_id) if metadata[2] else entrypoint_id)
            for entrypoint_id, metadata in sorted(entrypoints.items())
        ]
        for source in skill_sources:
            result["codex"].append(
                Artifact("codex", source, Path("skills") / _safe_stem(source.name), "directory")
            )
        for entrypoint_id in sorted(entrypoints):
            source = root / "codex-prompts" / f"{entrypoint_id}.md"
            safe_name = f"{_safe_stem(source.stem)}.md"
            result["codex"].append(
                Artifact("codex", source, Path("prompts") / safe_name, "file")
            )
            if safe_name != source.name:
                result["codex"].append(
                    Artifact("codex", source, Path("prompts") / source.name, "file", alias=True)
                )
    if "claude" in selected:
        for entrypoint_id in sorted(entrypoints):
            source = root / "claude-commands" / f"{entrypoint_id}.md"
            safe_name = f"{_safe_stem(source.stem)}.md"
            result["claude"].append(
                Artifact("claude", source, Path("commands") / safe_name, "file")
            )
            if safe_name != source.name:
                result["claude"].append(
                    Artifact("claude", source, Path("commands") / source.name, "file", alias=True)
                )
    return result


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _package_version(root: Path) -> str:
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        match = re.search(
            r'^version\s*=\s*"([^"]+)"\s*$',
            pyproject.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        if match:
            return match.group(1)
    try:
        return importlib.metadata.version("stock-analysis")
    except importlib.metadata.PackageNotFoundError as error:
        raise InstallError("无法确定 stock-analysis package version") from error


def _cli_version(executable: str) -> str | None:
    try:
        completed = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        completed = None
    if completed is not None and completed.returncode == 0:
        match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", completed.stdout)
        if match:
            return match.group(1)
    return None


def _new_manifest(catalog_hash: str, package_version: str) -> dict[str, Any]:
    now = _timestamp()
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "managed_by": MANAGED_BY,
        "package_version": package_version,
        "catalog_hash": catalog_hash,
        "installed_at": now,
        "updated_at": now,
        "targets": {},
    }


def _validate_manifest(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InstallError("manifest 必须是 JSON 对象")
    if value.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise InstallError("manifest schema_version 不受支持")
    if value.get("managed_by") != MANAGED_BY:
        raise InstallError("manifest managed_by 无效")
    if not isinstance(value.get("package_version"), str) or not value["package_version"]:
        raise InstallError("manifest package_version 无效")
    if not isinstance(value.get("catalog_hash"), str):
        raise InstallError("manifest catalog_hash 无效")
    for timestamp_name in ("installed_at", "updated_at"):
        timestamp = value.get(timestamp_name)
        if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
            raise InstallError(f"manifest {timestamp_name} 无效")
    targets = value.get("targets")
    if not isinstance(targets, dict) or any(host not in HOSTS for host in targets):
        raise InstallError("manifest targets 无效")
    for host, target in targets.items():
        if not isinstance(target, dict) or target.get("host") != host:
            raise InstallError(f"manifest target metadata 无效：{host}")
        if not isinstance(target.get("root"), str) or not Path(target["root"]).is_absolute():
            raise InstallError(f"manifest target root 无效：{host}")
        entries = target.get("entries")
        if not isinstance(entries, list):
            raise InstallError(f"manifest entries 无效：{host}")
        seen: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise InstallError(f"manifest entry 无效：{host}")
            relative = _safe_relative_path(entry.get("path")).as_posix()
            if relative in seen:
                raise InstallError(f"manifest entry 路径重复：{relative}")
            seen.add(relative)
            if entry.get("kind") not in {"file", "directory"}:
                raise InstallError(f"manifest entry kind 无效：{relative}")
            if not isinstance(entry.get("sha256"), str) or not HASH_RE.fullmatch(entry["sha256"]):
                raise InstallError(f"manifest entry sha256 无效：{relative}")
            if not isinstance(entry.get("source"), str):
                raise InstallError(f"manifest entry source 无效：{relative}")
            if not isinstance(entry.get("alias"), bool):
                raise InstallError(f"manifest entry alias 无效：{relative}")
    return value


class AgentEntrypointInstaller:
    # Plan §12: installation is manifest-driven and never claims unmanaged files.
    def __init__(
        self,
        *,
        root: Path = ROOT,
        codex_home: Path | None = None,
        claude_config_dir: Path | None = None,
        state_home: Path | None = None,
    ) -> None:
        self.root = root.resolve()
        self.codex_home = (
            codex_home
            or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
        ).resolve()
        self.claude_config_dir = (
            claude_config_dir
            or Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))).expanduser()
        ).resolve()
        self.state_home = (
            state_home
            or Path(
                os.environ.get("STOCK_ANALYSIS_HOME", str(Path.home() / ".stock-analysis"))
            ).expanduser()
        ).resolve()
        self.manifest_path = self.state_home / MANIFEST_NAME

    def _host_root(self, host: str) -> Path:
        return self.codex_home if host == "codex" else self.claude_config_dir

    def _load_manifest(
        self, catalog_hash: str, package_version: str, *, required: bool = False
    ) -> dict[str, Any]:
        if not self.manifest_path.exists():
            if required:
                raise InstallError(f"未找到安装 manifest：{self.manifest_path}")
            return _new_manifest(catalog_hash, package_version)
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise InstallError(f"无法读取安装 manifest：{error}") from error
        return _validate_manifest(value)

    @staticmethod
    def _target_entry_map(target: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        if target is None:
            return {}
        return {entry["path"]: entry for entry in target["entries"]}

    @staticmethod
    def _assert_managed_unchanged(root: Path, entry: dict[str, Any]) -> None:
        path = root / _safe_relative_path(entry["path"])
        if not path.exists():
            return
        actual_kind = "directory" if path.is_dir() else "file"
        if actual_kind != entry["kind"] or _sha256_path(path) != entry["sha256"]:
            raise InstallError(f"托管入口已被用户修改，拒绝覆盖或删除：{path}")

    def install(self, selected_hosts: Iterable[str], *, dry_run: bool = False) -> list[str]:
        entrypoints, catalog_hash = _catalog_entrypoints(_catalog_path(self.root))
        package_version = _package_version(self.root)
        _verify_generated_entrypoints(self.root, entrypoints, catalog_hash)
        _verify_protocol_schemas(self.root)
        hosts = tuple(selected_hosts)
        generated = _artifacts(self.root, hosts, entrypoints)
        manifest = self._load_manifest(catalog_hash, package_version)
        old_targets = manifest["targets"]
        selected_entries: dict[str, list[dict[str, Any]]] = {}
        skipped_aliases: list[Path] = []

        # Preflight every selected host before changing any host.
        for host in hosts:
            root = self._host_root(host)
            old_target = old_targets.get(host)
            old_root = Path(old_target["root"]) if old_target else root
            old_entries = self._target_entry_map(old_target)
            for entry in old_entries.values():
                self._assert_managed_unchanged(old_root, entry)
            new_entries: list[dict[str, Any]] = []
            for artifact in generated[host]:
                relative = artifact.relative_destination.as_posix()
                destination = root / artifact.relative_destination
                old_entry = old_entries.get(relative) if old_root == root else None
                if destination.exists() and old_entry is None:
                    if artifact.alias:
                        skipped_aliases.append(destination)
                        continue
                    raise InstallError(f"目标已存在且不受 stock-analysis 管理：{destination}")
                new_entries.append(
                    {
                        "path": relative,
                        "kind": artifact.kind,
                        "sha256": _sha256_path(artifact.source),
                        "source": artifact.source.relative_to(self.root).as_posix(),
                        "alias": artifact.alias,
                    }
                )
            selected_entries[host] = new_entries

        actions: list[str] = []
        for path in skipped_aliases:
            actions.append(f"跳过冲突短别名 {path}")
        for host in hosts:
            root = self._host_root(host)
            old_target = old_targets.get(host)
            old_root = Path(old_target["root"]) if old_target else root
            old_entries = self._target_entry_map(old_target)
            new_map = {entry["path"]: entry for entry in selected_entries[host]}
            generated_map = {
                artifact.relative_destination.as_posix(): artifact for artifact in generated[host]
            }
            for relative, _entry in old_entries.items():
                if old_root != root or relative not in new_map:
                    destination = old_root / _safe_relative_path(relative)
                    actions.append(f"移除旧托管入口 {destination}")
                    if not dry_run and destination.exists():
                        if destination.is_dir():
                            shutil.rmtree(destination)
                        else:
                            destination.unlink()
            for relative, _entry in new_map.items():
                artifact = generated_map[relative]
                destination = root / artifact.relative_destination
                actions.append(f"安装 {destination}")
                if dry_run:
                    continue
                if destination.exists():
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                destination.parent.mkdir(parents=True, exist_ok=True)
                if artifact.kind == "directory":
                    shutil.copytree(artifact.source, destination)
                else:
                    shutil.copy2(artifact.source, destination)
            if not dry_run:
                old_targets[host] = {
                    "host": host,
                    "root": str(root),
                    "entries": selected_entries[host],
                }
        if not dry_run:
            manifest["package_version"] = package_version
            manifest["catalog_hash"] = catalog_hash
            manifest["updated_at"] = _timestamp()
            _atomic_json_write(self.manifest_path, manifest)
            actions.append(f"写入 manifest {self.manifest_path}")
        else:
            actions.append("dry-run：未修改文件")
        return actions

    def doctor(self, selected_hosts: Iterable[str]) -> tuple[bool, list[str]]:
        entrypoints, catalog_hash = _catalog_entrypoints(_catalog_path(self.root))
        package_version = _package_version(self.root)
        messages: list[str] = []
        try:
            _verify_generated_entrypoints(self.root, entrypoints, catalog_hash)
            _verify_protocol_schemas(self.root)
            manifest = self._load_manifest(catalog_hash, package_version, required=True)
        except InstallError as error:
            return False, [str(error)]
        healthy = True
        executable = shutil.which("stock-analysis")
        if executable is None:
            healthy = False
            messages.append("找不到 stock-analysis CLI 可执行文件")
        else:
            messages.append(f"stock-analysis CLI：{executable}")
        installed_version = _cli_version(executable) if executable else None
        if installed_version != package_version:
            healthy = False
            messages.append(
                f"CLI package 版本不匹配：installed={installed_version!r}, expected={package_version!r}"
            )
        if manifest["package_version"] != package_version:
            healthy = False
            messages.append(
                "安装 manifest package_version 与当前 stock-analysis 版本不一致，请重新安装"
            )
        if manifest["catalog_hash"] != catalog_hash:
            healthy = False
            messages.append("安装版本与当前 canonical catalog hash 不一致，请重新安装")
        for host in selected_hosts:
            target = manifest["targets"].get(host)
            if target is None:
                healthy = False
                messages.append(f"{host} 尚未安装")
                continue
            root = Path(target["root"])
            recorded = self._target_entry_map(target)
            required_paths = {
                artifact.relative_destination.as_posix()
                for artifact in _artifacts(self.root, (host,), entrypoints)[host]
                if not artifact.alias
            }
            missing_required = sorted(required_paths - set(recorded))
            if missing_required:
                healthy = False
                messages.extend(
                    f"manifest 缺少必需 {host} 入口 {relative}" for relative in missing_required
                )
            for entry in target["entries"]:
                path = root / _safe_relative_path(entry["path"])
                if not path.exists():
                    healthy = False
                    messages.append(f"缺少托管入口 {path}")
                    continue
                try:
                    actual_hash = _sha256_path(path)
                except InstallError as error:
                    healthy = False
                    messages.append(str(error))
                    continue
                if actual_hash != entry["sha256"]:
                    healthy = False
                    messages.append(f"托管入口内容已变化 {path}")
                source = self.root / _safe_relative_path(entry["source"])
                if not source.exists() or _sha256_path(source) != entry["sha256"]:
                    healthy = False
                    messages.append(f"生成入口与安装 manifest 漂移 {source}")
            if not any(
                message.startswith(("缺少", "托管", "manifest 缺少", "生成入口"))
                and str(root) in message
                for message in messages
            ):
                messages.append(f"{host} 入口检查完成：{root}")
        return healthy, messages

    def uninstall(self, selected_hosts: Iterable[str], *, dry_run: bool = False) -> list[str]:
        _, catalog_hash = _catalog_entrypoints(_catalog_path(self.root))
        package_version = _package_version(self.root)
        manifest = self._load_manifest(catalog_hash, package_version, required=True)
        targets = manifest["targets"]
        hosts = tuple(selected_hosts)
        for host in hosts:
            target = targets.get(host)
            if target is None:
                continue
            root = Path(target["root"])
            for entry in target["entries"]:
                self._assert_managed_unchanged(root, entry)
        actions: list[str] = []
        for host in hosts:
            target = targets.get(host)
            if target is None:
                actions.append(f"{host} 未安装")
                continue
            root = Path(target["root"])
            for entry in reversed(target["entries"]):
                path = root / _safe_relative_path(entry["path"])
                actions.append(f"卸载 {path}")
                if not dry_run and path.exists():
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
            if not dry_run:
                del targets[host]
        if dry_run:
            actions.append("dry-run：未修改文件")
        elif targets:
            _atomic_json_write(self.manifest_path, manifest)
            actions.append(f"更新 manifest {self.manifest_path}")
        else:
            self.manifest_path.unlink()
            actions.append(f"删除 manifest {self.manifest_path}")
            try:
                self.state_home.rmdir()
            except OSError:
                pass
        return actions


def _selected_hosts(value: str) -> tuple[str, ...]:
    return HOSTS if value == "all" else (value,)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action")
    for action in ("install", "doctor", "uninstall", "dry-run"):
        command = subparsers.add_parser(action)
        command.add_argument("target", choices=("codex", "claude", "all"), nargs="?", default="all")
        if action in {"install", "uninstall"}:
            command.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    # Backward compatibility with scripts/install-agent-entrypoints.sh codex|claude|all.
    if not arguments:
        arguments = ["install", "all"]
    elif arguments[0] in {"codex", "claude", "all"}:
        arguments.insert(0, "install")
    parsed = _parser().parse_args(arguments)
    installer = AgentEntrypointInstaller()
    target = getattr(parsed, "target", "all")
    hosts = _selected_hosts(target)
    try:
        if parsed.action == "doctor":
            healthy, messages = installer.doctor(hosts)
            for message in messages:
                print(message)
            return 0 if healthy else 1
        if parsed.action == "uninstall":
            actions = installer.uninstall(hosts, dry_run=parsed.dry_run)
        else:
            dry_run = parsed.action == "dry-run" or getattr(parsed, "dry_run", False)
            actions = installer.install(hosts, dry_run=dry_run)
        for action in actions:
            print(action)
        return 0
    except InstallError as error:
        print(f"安装器错误：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
