import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_agent_entrypoints.py"
SPEC = importlib.util.spec_from_file_location("install_agent_entrypoints", SCRIPT)
assert SPEC and SPEC.loader
installer_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = installer_module
SPEC.loader.exec_module(installer_module)

AgentEntrypointInstaller = installer_module.AgentEntrypointInstaller
InstallError = installer_module.InstallError

COMMANDS = ("market", "snapshot", "analyze", "earnings", "move", "screen", "portfolio", "thesis")


def _generated_text(entrypoint_id: str, command_id: str, catalog_hash: str) -> str:
    return f"""---
managed_by: stock-analysis
schema_version: "2.0"
command_id: {command_id}
catalog_hash: {catalog_hash}
x-stock-analysis-managed: true
x-stock-analysis-schema: agent-entrypoint/v2
x-stock-analysis-command: {entrypoint_id}
x-stock-analysis-catalog-hash: {catalog_hash}
---

# /{entrypoint_id}
"""


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    root.joinpath("pyproject.toml").write_text(
        '[project]\nname = "stock-analysis"\nversion = "4.17.0"\n',
        encoding="utf-8",
    )
    catalog = {
        "schema_version": "2.0",
        "protocol_version": "1.0",
        "protocol_id": "stock-analysis-agent",
        "architecture": {
            "request": "HostRequest",
            "decision": "ResolvedRequest",
            "execution": "Workflow",
        },
        "commands": [
            {
                "id": entrypoint_id,
                "command_id": f"stock-analysis.{entrypoint_id}",
            }
            for entrypoint_id in COMMANDS
        ],
        "compatibility": {
            "legacy_entrypoints": [],
            "operational_entrypoints": [{"id": "data-diagnose", "command_id": "data-diagnose"}],
        },
    }
    catalog_path = root / "agent-entrypoints" / "catalog.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    schemas = root / "agent-entrypoints" / "schemas"
    schemas.mkdir()
    schema_documents = {
        "host-request.schema.json": {
            "properties": {
                "schema_version": {"const": "2.0"},
                "command": {"enum": list(COMMANDS)},
            }
        },
        "resolved-request.schema.json": {
            "required": ["catalog_hash", "argv", "output_contract", "blocked"]
        },
        "route-decision.schema.json": {},
        "filter.schema.json": {},
        "sort.schema.json": {},
    }
    for name, document in schema_documents.items():
        (schemas / name).write_text(json.dumps(document), encoding="utf-8")
    catalog_hash = f"sha256:{hashlib.sha256(catalog_path.read_bytes()).hexdigest()}"
    for entrypoint_id in COMMANDS:
        command_id = f"stock-analysis.{entrypoint_id}"
        text = _generated_text(entrypoint_id, command_id, catalog_hash)
        skill = root / "codex-skills" / f"stock-analysis-{entrypoint_id}" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(text, encoding="utf-8")
        for directory in ("codex-prompts", "claude-commands"):
            path = root / directory / f"{entrypoint_id}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    auxiliary = root / "codex-skills" / "primary-evidence-reach" / "SKILL.md"
    auxiliary.parent.mkdir(parents=True)
    auxiliary.write_text("# Auxiliary Skill\n", encoding="utf-8")
    operational = _generated_text("data-diagnose", "data-diagnose", catalog_hash)
    operational_skill = root / "codex-skills" / "data-diagnose" / "SKILL.md"
    operational_skill.parent.mkdir(parents=True)
    operational_skill.write_text(operational, encoding="utf-8")
    for directory in ("codex-prompts", "claude-commands"):
        (root / directory / "data-diagnose.md").write_text(operational, encoding="utf-8")
    return root


def _installer(tmp_path: Path) -> AgentEntrypointInstaller:
    return AgentEntrypointInstaller(
        root=_project(tmp_path),
        codex_home=tmp_path / "codex",
        claude_config_dir=tmp_path / "claude",
        state_home=tmp_path / "state",
    )


def _manifest(instance: AgentEntrypointInstaller) -> dict:
    return json.loads(instance.manifest_path.read_text(encoding="utf-8"))


def test_install_all_uses_one_manifest_and_installs_safe_names_and_short_aliases(tmp_path):
    instance = _installer(tmp_path)

    actions = instance.install(("codex", "claude"))

    assert actions
    assert (tmp_path / "codex/skills/stock-analysis-market/SKILL.md").is_file()
    assert (tmp_path / "codex/skills/stock-analysis-primary-evidence-reach/SKILL.md").is_file()
    assert (tmp_path / "codex/prompts/stock-analysis-market.md").is_file()
    assert (tmp_path / "codex/prompts/market.md").is_file()
    assert (tmp_path / "claude/commands/stock-analysis-market.md").is_file()
    assert (tmp_path / "claude/commands/market.md").is_file()
    manifest = _manifest(instance)
    assert manifest["managed_by"] == "stock-analysis-agent-installer"
    assert manifest["package_version"] == "4.17.0"
    assert manifest["installed_at"].endswith("Z")
    assert manifest["updated_at"].endswith("Z")
    assert set(manifest["targets"]) == {"codex", "claude"}
    assert manifest["targets"]["codex"]["root"] == str((tmp_path / "codex").resolve())
    assert not (tmp_path / "codex/.stock-analysis-agent-entrypoints.json").exists()


@pytest.mark.parametrize(
    ("host", "conflict"),
    [
        ("codex", "codex/prompts/market.md"),
        ("claude", "claude/commands/market.md"),
    ],
)
def test_unmanaged_short_alias_conflict_is_preserved_and_safe_name_is_installed(
    tmp_path, host, conflict
):
    instance = _installer(tmp_path)
    conflict_path = tmp_path / conflict
    conflict_path.parent.mkdir(parents=True)
    conflict_path.write_text("user-owned\n", encoding="utf-8")

    actions = instance.install((host,))

    assert conflict_path.read_text(encoding="utf-8") == "user-owned\n"
    assert any("跳过冲突短别名" in action for action in actions)
    safe_path = conflict_path.with_name("stock-analysis-market.md")
    assert safe_path.is_file()
    entries = _manifest(instance)["targets"][host]["entries"]
    assert conflict_path.relative_to(tmp_path / host).as_posix() not in {
        entry["path"] for entry in entries
    }


def test_unmanaged_required_entry_aborts_before_any_changes(tmp_path):
    instance = _installer(tmp_path)
    conflict = tmp_path / "codex/prompts/stock-analysis-market.md"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("user-owned\n", encoding="utf-8")

    with pytest.raises(InstallError, match="不受 stock-analysis 管理"):
        instance.install(("codex",))

    assert conflict.read_text(encoding="utf-8") == "user-owned\n"
    assert not (tmp_path / "codex/skills").exists()
    assert not instance.manifest_path.exists()


def test_reinstall_is_idempotent_and_upgrades_unchanged_managed_files(tmp_path):
    instance = _installer(tmp_path)
    instance.install(("codex", "claude"))
    source = instance.root / "codex-prompts" / "market.md"
    source.write_text(source.read_text(encoding="utf-8") + "\nupgraded\n", encoding="utf-8")

    instance.install(("codex", "claude"))
    instance.install(("codex", "claude"))

    expected = source.read_text(encoding="utf-8")
    assert (tmp_path / "codex/prompts/market.md").read_text(encoding="utf-8") == expected
    assert (tmp_path / "codex/prompts/stock-analysis-market.md").read_text(encoding="utf-8") == expected
    healthy, messages = instance.doctor(("codex", "claude"))
    assert healthy, messages


def test_modified_managed_entry_blocks_upgrade_and_uninstall(tmp_path):
    instance = _installer(tmp_path)
    instance.install(("codex",))
    installed = tmp_path / "codex/prompts/stock-analysis-market.md"
    installed.write_text("locally modified\n", encoding="utf-8")

    with pytest.raises(InstallError, match="已被用户修改"):
        instance.install(("codex",))
    with pytest.raises(InstallError, match="已被用户修改"):
        instance.uninstall(("codex",))

    assert installed.read_text(encoding="utf-8") == "locally modified\n"
    assert instance.manifest_path.exists()


def test_dry_run_does_not_create_destinations_or_manifest(tmp_path):
    instance = _installer(tmp_path)

    actions = instance.install(("codex", "claude"), dry_run=True)

    assert actions[-1] == "dry-run：未修改文件"
    assert not (tmp_path / "codex").exists()
    assert not (tmp_path / "claude").exists()
    assert not instance.manifest_path.exists()


def test_install_rejects_missing_protocol_schema(tmp_path):
    instance = _installer(tmp_path)
    (instance.root / "agent-entrypoints/schemas/host-request.schema.json").unlink()

    with pytest.raises(InstallError, match="协议 schema 不可用"):
        instance.install(("codex",), dry_run=True)


def test_doctor_reports_missing_and_changed_entries(tmp_path):
    instance = _installer(tmp_path)
    instance.install(("codex",))
    (tmp_path / "codex/prompts/market.md").unlink()

    healthy, messages = instance.doctor(("codex", "claude"))

    assert not healthy
    assert any("缺少托管入口" in message for message in messages)
    assert "claude 尚未安装" in messages


def test_selective_uninstall_preserves_other_host_and_removes_manifest_last(tmp_path):
    instance = _installer(tmp_path)
    instance.install(("codex", "claude"))

    instance.uninstall(("codex",))

    assert not (tmp_path / "codex/skills/stock-analysis-market").exists()
    assert (tmp_path / "claude/commands/stock-analysis-market.md").exists()
    assert set(_manifest(instance)["targets"]) == {"claude"}

    instance.uninstall(("claude",))

    assert not (tmp_path / "claude/commands/stock-analysis-market.md").exists()
    assert not instance.manifest_path.exists()


def test_uninstall_dry_run_preserves_everything(tmp_path):
    instance = _installer(tmp_path)
    instance.install(("codex",))

    actions = instance.uninstall(("codex",), dry_run=True)

    assert actions[-1] == "dry-run：未修改文件"
    assert (tmp_path / "codex/skills/stock-analysis-market/SKILL.md").exists()
    assert instance.manifest_path.exists()


def test_environment_overrides_choose_cross_platform_config_roots(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "custom codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "custom claude"))
    monkeypatch.setenv("STOCK_ANALYSIS_HOME", str(tmp_path / "custom state"))

    instance = AgentEntrypointInstaller(root=_project(tmp_path))

    assert instance.codex_home == (tmp_path / "custom codex").resolve()
    assert instance.claude_config_dir == (tmp_path / "custom claude").resolve()
    assert instance.manifest_path == (tmp_path / "custom state" / "agent-install-manifest.json").resolve()


def test_corrupt_managed_metadata_is_rejected(tmp_path):
    instance = _installer(tmp_path)
    instance.state_home.mkdir(parents=True)
    instance.manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "managed_by": "another-tool",
                "catalog_hash": "sha256:x",
                "targets": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(InstallError, match="managed_by"):
        instance.install(("codex",))


def test_generated_metadata_must_match_raw_catalog_hash_and_command_id(tmp_path):
    instance = _installer(tmp_path)
    prompt = instance.root / "codex-prompts/market.md"
    prompt.write_text(
        prompt.read_text(encoding="utf-8").replace(
            "command_id: stock-analysis.market", "command_id: wrong"
        ),
        encoding="utf-8",
    )

    with pytest.raises(InstallError, match="metadata 无效"):
        instance.install(("codex",))
