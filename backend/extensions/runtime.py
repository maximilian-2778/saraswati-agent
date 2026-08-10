"""把 Skill 分级加载和 MCP Plugin 工具统一接入 Agent。"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from backend.config import PROJECT_ROOT
from backend.extensions.plugins import McpClient, PluginRegistry
from backend.extensions.skills import SkillRegistry


class ExtensionRuntime:
    """扩展运行时；发现失败时保持主聊天可用。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or PROJECT_ROOT / "data" / "extensions"
        state_file = self.root / "state.json"
        self.skills = SkillRegistry(self.root / "skills", state_file)
        self.plugins = PluginRegistry(self.root / "plugins", state_file)
        self.mcp = McpClient()
        self._tool_routes: dict[str, tuple[str, str, str]] = {}
        self._schema_cache: dict[tuple[str, ...] | None, list[dict[str, Any]]] = {}
        self.reload()

    def reload(self) -> None:
        self.plugins.reload()
        self.skills.set_plugin_roots({
            plugin.id: plugin.skill_roots()
            for plugin in self.plugins.enabled()
            if plugin.skill_roots()
        })
        self.skills.reload()
        self._tool_routes.clear()
        self._schema_cache.clear()

    def invalidate_tools(self) -> None:
        self._tool_routes.clear()
        self._schema_cache.clear()

    def catalog(self) -> dict[str, Any]:
        return {
            "skills": [item.public() for item in self.skills.list()],
            "plugins": [item.public() for item in self.plugins.list()],
            "mcp_sdk_available": self.mcp.available,
            "root": "data/extensions",
        }

    def prompt_messages(
        self,
        user_text: str,
        allowed_skill_ids: set[str] | None = None,
    ) -> list[dict[str, str]]:
        enabled = self._allowed_skills(allowed_skill_ids)
        if not enabled:
            return []
        lines = [
            "可用 Skill（这里只提供元数据；需要时调用 activate_skill 按需读取，不要臆测其内容）：",
            *[f"- {item.id}: {item.description}" for item in enabled],
        ]
        explicit = self.skills.match_explicit(user_text)
        if explicit and allowed_skill_ids is not None and explicit.id not in allowed_skill_ids:
            explicit = None
        if explicit:
            self.skills.record_use(explicit.id)
            payload = self.skills.view(explicit.id)
            lines.extend(["", f"用户显式启用了 Skill `{explicit.id}`：", str(payload["content"])])
        return [{"role": "system", "content": "\n".join(lines)}]

    async def tool_schemas(self, allowed_skill_ids: set[str] | None = None) -> list[dict[str, Any]]:
        cache_key = None if allowed_skill_ids is None else tuple(sorted(allowed_skill_ids))
        if cache_key in self._schema_cache:
            return list(self._schema_cache[cache_key])
        schemas: list[dict[str, Any]] = []
        enabled_skills = self._allowed_skills(allowed_skill_ids)
        if enabled_skills:
            schemas.append({
                "type": "function",
                "function": {
                    "name": "activate_skill",
                    "description": "按需加载一个 Skill 的完整说明或其附属资源。先根据系统提供的 Skill 元数据选择，再调用本工具。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "enum": [item.id for item in enabled_skills]},
                            "resource": {"type": "string", "description": "可选；主说明返回的 resources 中的相对路径"},
                        },
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                },
            })
        self._tool_routes.clear()
        for plugin in self.plugins.enabled():
            plugin.tools = []
            errors: list[str] = []
            for server in plugin.mcp_servers:
                try:
                    tools = await self.mcp.list_tools(server)
                except Exception as exc:
                    errors.append(f"{server.id}: {exc}")
                    continue
                for tool in tools:
                    remote_name = str(tool["name"])
                    if plugin.allowed_tools and remote_name not in plugin.allowed_tools:
                        continue
                    if server.allowed_tools and remote_name not in server.allowed_tools:
                        continue
                    if remote_name in server.excluded_tools:
                        continue
                    plugin.tools.append(remote_name)
                    public_name = _public_tool_name(
                        plugin.id,
                        remote_name,
                        server.id if len(plugin.mcp_servers) > 1 else "",
                    )
                    if public_name in self._tool_routes:
                        continue
                    self._tool_routes[public_name] = (plugin.id, server.id, remote_name)
                    schemas.append({
                        "type": "function",
                        "function": {
                            "name": public_name,
                            "description": f"[{plugin.name}] {tool.get('description', '')}".strip(),
                            "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
                        },
                    })
            plugin.tools = sorted(set(plugin.tools))
            plugin.status = "error" if errors else "connected" if plugin.mcp_servers else "idle"
            plugin.error = "；".join(errors) or None
        self._schema_cache[cache_key] = schemas
        return list(schemas)

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        allowed_skill_ids: set[str] | None = None,
    ) -> Any:
        if name == "activate_skill":
            skill_id = str(arguments.get("name", ""))
            if allowed_skill_ids is not None and skill_id not in allowed_skill_ids:
                raise ValueError(f"当前故事未授权 Skill：{skill_id}")
            self.skills.record_use(skill_id)
            return self.skills.view(skill_id, _optional(arguments.get("resource")))
        route = self._tool_routes.get(name)
        if route is None:
            raise ValueError(f"未知扩展工具：{name}")
        plugin_id, server_id, remote_name = route
        plugin = self.plugins.require(plugin_id)
        if not plugin.enabled:
            raise ValueError(f"Plugin 已停用：{plugin_id}")
        return await self.mcp.call_tool(plugin.server(server_id), remote_name, arguments)

    async def test_plugin(self, plugin_id: str) -> dict[str, Any]:
        plugin = self.plugins.require(plugin_id)
        if any(server.transport == "stdio" for server in plugin.mcp_servers) and not plugin.trusted:
            raise ValueError("测试本机程序前需要先信任该插件")
        tools: list[str] = []
        errors: list[str] = []
        for server in plugin.mcp_servers:
            try:
                tools.extend(str(item["name"]) for item in await self.mcp.list_tools(server))
            except Exception as exc:
                errors.append(f"{server.id}: {exc}")
        plugin.tools = sorted(set(tools))
        plugin.status = "error" if errors else "connected" if plugin.mcp_servers else "idle"
        plugin.error = "；".join(errors) or None
        if errors:
            raise RuntimeError(plugin.error)
        return {"ok": True, "plugin": plugin.public(), "tool_count": len(plugin.tools)}

    def _allowed_skills(self, allowed_skill_ids: set[str] | None) -> list[Any]:
        enabled = self.skills.enabled()
        if allowed_skill_ids is None:
            return enabled
        return [item for item in enabled if item.id in allowed_skill_ids]


def _public_tool_name(plugin_id: str, remote_name: str, server_id: str = "") -> str:
    parts = [plugin_id, server_id, remote_name] if server_id else [plugin_id, remote_name]
    value = "__".join(re.sub(r"[^A-Za-z0-9_-]", "_", part) for part in parts)
    if len(value) <= 64:
        return value
    return f"{value[:55]}_{hashlib.sha256(value.encode()).hexdigest()[:8]}"


def _optional(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
