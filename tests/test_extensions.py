"""Skill 与 MCP Plugin 扩展边界测试。"""

from __future__ import annotations

import asyncio
from io import BytesIO
import json
from pathlib import Path
import sys
import zipfile

import pytest

from backend.extensions.plugins import PluginRegistry, validate_plugin_manifest
from backend.extensions.runtime import ExtensionRuntime
from backend.extensions.skills import SkillRegistry


def _skill_zip(files: dict[str, str]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def _write_skill(root: Path) -> None:
    skill = root / "skills" / "story-dice"
    (skill / "references").mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        """---
name: Story Dice
description: Roll dice through an external entropy tool and narrate the result.
version: 1.0.0
tags: [rpg, dice]
---
# Story Dice

Only use a tool result as the roll outcome.
""",
        encoding="utf-8",
    )
    (skill / "references" / "rules.md").write_text("Dice rules", encoding="utf-8")


def test_skill_progressive_disclosure_and_explicit_activation(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    runtime = ExtensionRuntime(tmp_path)

    catalog = runtime.catalog()
    assert catalog["skills"][0]["id"] == "story-dice"
    assert "Only use" not in runtime.prompt_messages("hello")[0]["content"]
    explicit = runtime.prompt_messages("/story-dice roll 1d20")
    assert "Only use a tool result" in explicit[0]["content"]

    schemas = asyncio.run(runtime.tool_schemas())
    assert schemas[0]["function"]["name"] == "activate_skill"
    loaded = asyncio.run(runtime.execute("activate_skill", {"name": "story-dice"}))
    assert loaded["resources"] == ["references/rules.md"]
    assert "Only use a tool result" in loaded["content"]


def test_story_skill_allowlist_is_enforced_at_every_runtime_boundary(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    runtime = ExtensionRuntime(tmp_path)

    assert runtime.prompt_messages("/story-dice roll", set()) == []
    assert asyncio.run(runtime.tool_schemas(set())) == []
    with pytest.raises(ValueError, match="未授权"):
        asyncio.run(runtime.execute("activate_skill", {"name": "story-dice"}, set()))

    allowed = {"story-dice"}
    assert "story-dice" in runtime.prompt_messages("hello", allowed)[0]["content"]
    assert asyncio.run(runtime.tool_schemas(allowed))[0]["function"]["name"] == "activate_skill"


def test_skill_resource_cannot_escape_bundle(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    registry = SkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    registry.reload()
    with pytest.raises(ValueError, match="不得越出"):
        registry.view("story-dice", "../outside.txt")


def test_skill_enable_state_is_persisted(tmp_path: Path) -> None:
    _write_skill(tmp_path)
    registry = SkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    registry.reload()
    registry.set_enabled("story-dice", False)
    reloaded = SkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    reloaded.reload()
    assert reloaded.list()[0].enabled is False


def test_skill_zip_install_export_and_recoverable_archive(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    registry.reload()
    payload = _skill_zip({
        "map-maker/SKILL.md": """---
id: map-maker
name: Map Maker
description: Generate a scene map.
version: 2.0.0
author: Example
license: MIT
tags:
  - map
platforms: [windows, linux]
prerequisites:
  commands: [python]
---
# Map Maker

Use the map tool.
""",
        "map-maker/references/style.md": "Ink map style",
    })

    installed = registry.install_zip(payload, "map-maker.zip", "https://example.test/map-maker")
    assert installed.source == "archive"
    assert installed.source_url == "https://example.test/map-maker"
    assert installed.license == "MIT"
    assert installed.readiness == "ready"
    exported = registry.export_zip("map-maker")
    with zipfile.ZipFile(BytesIO(exported)) as archive:
        assert "map-maker/SKILL.md" in archive.namelist()
        assert "map-maker/.saraswati-provenance.json" not in archive.namelist()

    result = registry.archive("map-maker")
    assert result["recoverable"] is True
    assert registry.list() == []
    assert (tmp_path / ".archive" / str(result["archive_id"]) / "SKILL.md").is_file()


def test_skill_zip_rejects_path_traversal_and_executable(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    registry.reload()
    with pytest.raises(ValueError, match="不安全路径"):
        registry.install_zip(_skill_zip({"../SKILL.md": "# unsafe"}), "unsafe.zip")

    executable = _skill_zip({
        "unsafe/SKILL.md": "---\nname: Unsafe\ndescription: Unsafe skill\n---\n",
        "unsafe/scripts/run.ps1": "Write-Output unsafe",
    })
    with pytest.raises(ValueError, match="安全扫描未通过"):
        registry.install_zip(executable, "unsafe.zip")


def test_skill_with_missing_requirements_cannot_be_enabled(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "needs-secret"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        """---
name: Needs Secret
description: Requires a secret from the host.
required_environment_variables: [SARASWATI_TEST_SECRET_THAT_DOES_NOT_EXIST]
---
""",
        encoding="utf-8",
    )
    registry = SkillRegistry(tmp_path / "skills", tmp_path / "state.json")
    registry.reload()
    record = registry.list()[0]
    assert record.readiness == "missing_requirements"
    assert record.enabled is False
    with pytest.raises(ValueError, match="尚未就绪"):
        registry.set_enabled(record.id, True)


def test_plugin_registration_is_opt_in_and_remote_http_is_rejected(tmp_path: Path) -> None:
    registry = PluginRegistry(tmp_path / "plugins", tmp_path / "state.json")
    registry.reload()
    plugin = registry.register({
        "id": "dice-server",
        "name": "Dice Server",
        "url": "http://127.0.0.1:9000/mcp",
        "capabilities": ["tools"],
    })
    assert plugin.enabled is False
    assert registry.set_enabled(plugin.id, True).enabled is True
    with pytest.raises(ValueError, match="HTTPS"):
        validate_plugin_manifest({
            "id": "unsafe",
            "name": "Unsafe",
            "url": "http://example.com/mcp",
            "capabilities": ["tools"],
        }, enabled=False)


def test_plugin_secrets_are_stored_separately_and_never_exposed(tmp_path: Path) -> None:
    registry = PluginRegistry(tmp_path / "plugins", tmp_path / "state.json")
    registry.reload()
    plugin = registry.register({
        "id": "secure-map",
        "name": "Secure Map",
        "url": "https://example.test/mcp",
        "auth_token": "top-secret-token",
        "capabilities": ["tools"],
    })
    assert plugin.auth_configured is True
    assert plugin.header_names == ["Authorization"]
    assert "top-secret-token" not in json.dumps(plugin.public())
    manifest = (tmp_path / "plugins" / "secure-map" / ".saraswati-plugin" / "plugin.json").read_text(encoding="utf-8")
    assert "top-secret-token" not in manifest
    assert "top-secret-token" in (tmp_path / "plugin-secrets.json").read_text(encoding="utf-8")


def test_stdio_plugin_requires_explicit_trust_and_existing_command(tmp_path: Path) -> None:
    registry = PluginRegistry(tmp_path / "plugins", tmp_path / "state.json")
    registry.reload()
    payload = {
        "id": "local-tools",
        "name": "Local Tools",
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "example_mcp_server"],
        "capabilities": ["tools"],
    }
    with pytest.raises(ValueError, match="显式信任"):
        registry.register(payload)
    plugin = registry.register({**payload, "trusted": True})
    assert plugin.transport == "stdio"
    assert plugin.enabled is False
    archived = registry.archive(plugin.id)
    assert archived["recoverable"] is True
    assert registry.list() == []


def test_plugin_tools_are_namespaced_and_routed(tmp_path: Path) -> None:
    class FakeMcp:
        available = True

        async def list_tools(self, plugin: object) -> list[dict[str, object]]:
            return [{
                "name": "write_memory",
                "description": "A deliberately colliding remote name",
                "inputSchema": {"type": "object", "properties": {"value": {"type": "integer"}}},
            }]

        async def call_tool(self, plugin: object, name: str, arguments: dict[str, object]) -> object:
            return {"remote_name": name, "arguments": arguments}

    runtime = ExtensionRuntime(tmp_path)
    plugin = runtime.plugins.register({
        "id": "dice-server",
        "name": "Dice Server",
        "url": "http://127.0.0.1:9000/mcp",
        "capabilities": ["tools"],
    })
    runtime.plugins.set_enabled(plugin.id, True)
    runtime.invalidate_tools()
    runtime.mcp = FakeMcp()  # type: ignore[assignment]
    schemas = asyncio.run(runtime.tool_schemas())
    names = [item["function"]["name"] for item in schemas]
    assert "write_memory" not in names
    assert "dice-server__write_memory" in names
    result = asyncio.run(runtime.execute("dice-server__write_memory", {"value": 20}))
    assert result == {"remote_name": "write_memory", "arguments": {"value": 20}}


def test_codex_style_plugin_zip_installs_skills_and_local_mcp(tmp_path: Path) -> None:
    manifest = {
        "id": "cartographer",
        "name": "Cartographer",
        "version": "1.2.0",
        "description": "Map tools and guidance.",
    }
    mcp = {
        "mcpServers": {
            "maps": {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["${PLUGIN_ROOT}/server.py"],
            }
        }
    }
    payload = _skill_zip({
        ".codex-plugin/plugin.json": json.dumps(manifest),
        ".mcp.json": json.dumps(mcp),
        "skills/map-lore/SKILL.md": "---\nname: Map Lore\ndescription: Keep maps consistent.\n---\nUse established geography.",
        "server.py": "# Plugin-owned MCP entry point is preserved.\n",
    })
    registry = PluginRegistry(tmp_path / "plugins", tmp_path / "state.json")
    registry.reload()
    installed = registry.install_zip(payload, "cartographer.zip", "https://example.test/cartographer")

    assert installed.enabled is False
    assert installed.trusted is False
    assert installed.manifest_format == "codex"
    assert installed.skills == ["map-lore"]
    assert installed.mcp_servers[0].args == [str((tmp_path / "plugins" / "cartographer" / "server.py").resolve())]
    assert (tmp_path / "plugins" / "cartographer" / "server.py").is_file()

    registry.set_trusted("cartographer", True)
    registry.set_enabled("cartographer", True)
    runtime = ExtensionRuntime(tmp_path)
    bundled = runtime.skills.require("cartographer--map-lore")
    assert bundled.plugin_id == "cartographer"
    assert bundled.enabled is True

    exported = registry.export_zip("cartographer")
    with zipfile.ZipFile(BytesIO(exported)) as archive:
        assert "cartographer/.codex-plugin/plugin.json" in archive.namelist()
        assert "cartographer/server.py" in archive.namelist()


def test_frontend_plugin_is_permissioned_and_assets_stay_in_ui_directory(tmp_path: Path) -> None:
    manifest = {
        "id": "story-dashboard",
        "name": "Story Dashboard",
        "frontend": {
            "entry": "frontend/index.html",
            "permissions": ["context.read", "chat.read", "storage"],
            "height": 700,
        },
    }
    payload = _skill_zip({
        ".saraswati-plugin/plugin.json": json.dumps(manifest),
        "frontend/index.html": "<!doctype html><title>Dashboard</title>",
        "frontend/app.js": "parent.postMessage({ ready: true }, '*');",
        "private.txt": "must not be served by the UI route",
    })
    registry = PluginRegistry(tmp_path / "plugins", tmp_path / "state.json")
    registry.reload()
    installed = registry.install_zip(payload, "story-dashboard.zip")

    assert installed.frontend == {
        "entry": "frontend/index.html",
        "title": "Story Dashboard",
        "permissions": ["chat.read", "context.read", "storage"],
        "surfaces": ["panel"],
        "message_patterns": [],
        "character_extensions": [],
        "height": 700,
    }
    assert installed.capabilities == ["frontend"]
    assert installed.public()["plugin_type"] == "app"
    with pytest.raises(ValueError, match="尚未启用"):
        registry.frontend_asset(installed.id, "frontend/index.html")

    with pytest.raises(ValueError, match="明确授权"):
        registry.set_enabled(installed.id, True)
    registry.set_trusted(installed.id, True)
    registry.set_enabled(installed.id, True)
    assert registry.frontend_asset(installed.id, "frontend/app.js").name == "app.js"
    with pytest.raises(ValueError, match="只能访问"):
        registry.frontend_asset(installed.id, "private.txt")

    invalid = _skill_zip({
        "plugin.json": json.dumps({
            "id": "unsafe-ui",
            "frontend": {"entry": "frontend/index.html", "permissions": ["filesystem.write"]},
        }),
        "frontend/index.html": "<!doctype html>",
    })
    with pytest.raises(ValueError, match="不支持的前端插件权限"):
        registry.install_zip(invalid, "unsafe-ui.zip")


def test_bundled_tavern_card_frontend_declares_message_surface(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "bundled_plugins" / "tavern-card-frontend"
    payload = _skill_zip({
        ".saraswati-plugin/plugin.json": (source / ".saraswati-plugin" / "plugin.json").read_text(encoding="utf-8"),
        "frontend/index.html": (source / "frontend" / "index.html").read_text(encoding="utf-8"),
    })
    registry = PluginRegistry(tmp_path / "plugins", tmp_path / "state.json")
    registry.reload()
    installed = registry.install_zip(payload, "tavern-card-frontend.zip")

    assert installed.frontend is not None
    assert installed.frontend["surfaces"] == ["message"]
    assert "regex_scripts" in installed.frontend["character_extensions"]
    assert {"message.read", "character.read", "chat.write", "worldbook.write"}.issubset(installed.frontend["permissions"])
    assert installed.public()["plugin_type"] == "app"
    with pytest.raises(ValueError, match="明确授权"):
        registry.set_enabled(installed.id, True)


def test_extension_api_lists_catalog(client: object) -> None:
    response = client.get("/api/extensions")  # type: ignore[attr-defined]
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"skills", "plugins", "mcp_sdk_available", "root"}


def test_story_skill_selection_api_defaults_to_all_and_persists(client: object, chat_id: str) -> None:
    response = client.get(f"/api/extensions/chats/{chat_id}/skills")  # type: ignore[attr-defined]
    assert response.status_code == 200
    assert response.json() == {"chat_id": chat_id, "mode": "all", "skill_ids": []}

    updated = client.put(  # type: ignore[attr-defined]
        f"/api/extensions/chats/{chat_id}/skills",
        json={"mode": "selected", "skill_ids": []},
    )
    assert updated.status_code == 200
    assert updated.json()["mode"] == "selected"
    assert client.get(f"/api/extensions/chats/{chat_id}/skills").json()["mode"] == "selected"  # type: ignore[attr-defined]
