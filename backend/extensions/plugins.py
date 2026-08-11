"""可分发插件包发现、安装和 MCP 客户端适配。"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import stat
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from backend.extensions.skills import IDENTIFIER_RE


PLUGIN_MANIFESTS = (
    ".saraswati-plugin/plugin.json",
    ".codex-plugin/plugin.json",
    "plugin.json",
)
MAX_PLUGIN_ARCHIVE_BYTES = 32 * 1024 * 1024
MAX_PLUGIN_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_PLUGIN_FILES = 512
FRONTEND_PERMISSIONS = {
    "context.read",
    "chat.read",
    "chat.write",
    "message.read",
    "character.read",
    "worldbook.read",
    "worldbook.write",
    "storage",
}
FRONTEND_SURFACES = {"panel", "message"}


@dataclass(slots=True)
class McpServerRecord:
    id: str
    transport: str = "streamable_http"
    url: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    cwd: str = ""
    environment_variables: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict, repr=False)
    allowed_tools: list[str] = field(default_factory=list)
    excluded_tools: list[str] = field(default_factory=list)
    timeout_seconds: float = 30.0
    headers: dict[str, str] = field(default_factory=dict, repr=False)

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("headers", None)
        data.pop("env", None)
        data["header_names"] = sorted(self.headers)
        return data


@dataclass(slots=True)
class PluginRecord:
    id: str
    name: str
    description: str
    version: str
    enabled: bool
    path: str
    manifest_format: str = "saraswati"
    source: str = "local"
    author: str = ""
    license: str = ""
    homepage: str = ""
    repository: str = ""
    keywords: list[str] = field(default_factory=list)
    trusted: bool = False
    status: str = "idle"
    error: str | None = None
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    interface: dict[str, Any] = field(default_factory=dict)
    frontend: dict[str, Any] | None = None
    mcp_servers: list[McpServerRecord] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    installed_at: str = ""
    source_url: str = ""
    # Legacy presentation fields retained for API compatibility.
    url: str = ""
    transport: str = "streamable_http"
    command: str = ""
    args: list[str] = field(default_factory=list)
    environment_variables: list[str] = field(default_factory=list)
    timeout_seconds: float = 30.0
    auth_configured: bool = False
    header_names: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("path", None)
        data["mcp_servers"] = [item.public() for item in self.mcp_servers]
        data["location"] = f"data/extensions/plugins/{self.id}"
        data["plugin_type"] = _plugin_type(self)
        return data

    def server(self, server_id: str) -> McpServerRecord:
        server = next((item for item in self.mcp_servers if item.id == server_id), None)
        if server is None:
            raise ValueError(f"插件 {self.id} 不包含 MCP 服务：{server_id}")
        return server

    def skill_roots(self) -> list[Path]:
        root = Path(self.path)
        candidates = [root / "skills"]
        return [item for item in candidates if item.is_dir()]


class PluginRegistry:
    """发现 Codex 风格和 Saraswati 风格插件包；新插件默认停用。"""

    def __init__(self, root: Path, state_file: Path) -> None:
        self.root = root
        self.state_file = state_file
        self.secret_file = root.parent / "plugin-secrets.json"
        self._plugins: dict[str, PluginRecord] = {}

    def reload(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        state = _read_json(self.state_file)
        secrets = _read_json(self.secret_file)
        manifest_paths = _discover_manifests(self.root)

        # Upgrade the old deny-list once. Fresh/manual discoveries remain opt-in.
        if "enabled_plugins" not in state:
            disabled = set(state.get("disabled_plugins", []))
            enabled = (
                {_manifest_directory(path).name for path in manifest_paths} - disabled
                if "disabled_plugins" in state else set()
            )
            state["enabled_plugins"] = sorted(enabled)
        enabled_ids = set(state.get("enabled_plugins", []))
        trusted_ids = set(state.get("trusted_plugins", []))
        known_ids = set(state.get("known_plugins", []))

        plugins: dict[str, PluginRecord] = {}
        for manifest_path in manifest_paths:
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                root = _manifest_directory(manifest_path)
                provisional_id = str(raw.get("id") or raw.get("name") or root.name).strip().lower()
                secret_headers = secrets.get(provisional_id, {})
                record = _read_plugin_package(
                    root,
                    manifest_path,
                    raw,
                    enabled=provisional_id in enabled_ids,
                    # Trust is a local decision.  A downloaded manifest may ask
                    # for trust, but it must never be able to grant it to itself.
                    trusted=provisional_id in trusted_ids,
                    secret_headers=secret_headers if isinstance(secret_headers, dict) else {},
                )
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            plugins.setdefault(record.id, record)
            known_ids.add(record.id)

        state["known_plugins"] = sorted(known_ids & set(plugins))
        state["enabled_plugins"] = sorted(enabled_ids & set(plugins))
        state["trusted_plugins"] = sorted(trusted_ids & set(plugins))
        state.pop("disabled_plugins", None)
        _write_json_atomic(self.state_file, state)
        self._plugins = plugins

    def list(self) -> list[PluginRecord]:
        return sorted(self._plugins.values(), key=lambda item: item.name.lower())

    def enabled(self) -> list[PluginRecord]:
        return [item for item in self.list() if item.enabled]

    def require(self, plugin_id: str) -> PluginRecord:
        record = self._plugins.get(plugin_id)
        if record is None:
            raise ValueError(f"插件不存在：{plugin_id}")
        return record

    def frontend_asset(self, plugin_id: str, relative_path: str) -> Path:
        """Resolve an enabled UI plugin asset without exposing the rest of its package."""
        record = self.require(plugin_id)
        if not record.enabled:
            raise ValueError("插件尚未启用")
        if not record.frontend:
            raise ValueError("插件没有前端界面")
        root = Path(record.path).resolve()
        entry = _safe_component(root, str(record.frontend["entry"]))
        frontend_root = entry.parent.resolve()
        target = _safe_component(root, relative_path)
        try:
            target.resolve().relative_to(frontend_root)
        except ValueError as exc:
            raise ValueError("只能访问插件前端目录中的资源") from exc
        if not target.is_file() or target.is_symlink():
            raise ValueError("插件前端资源不存在")
        return target

    def register(self, raw: dict[str, Any]) -> PluginRecord:
        """把表单中的单一 MCP 连接写成标准本地插件包。"""
        plugin_id = str(raw.get("id") or "").strip().lower()
        if not IDENTIFIER_RE.fullmatch(plugin_id):
            raise ValueError("插件标识必须是安全的短标识符")
        directory = self.root / plugin_id
        if directory.exists():
            raise ValueError(f"插件已存在：{plugin_id}")
        if str(raw.get("transport") or "streamable_http") == "stdio" and not raw.get("trusted"):
            raise ValueError("本机程序插件需要显式信任")
        secret_headers = _secret_headers(raw)
        manifest = {
            "id": plugin_id,
            "name": str(raw.get("name") or plugin_id),
            "version": str(raw.get("version") or ""),
            "description": str(raw.get("description") or ""),
            "trusted": bool(raw.get("trusted", False)),
            "mcp": {key: value for key, value in raw.items() if key in {
                "url", "transport", "command", "args", "environment_variables",
                "allowed_tools", "timeout_seconds",
            }},
        }
        directory.joinpath(".saraswati-plugin").mkdir(parents=True)
        _write_json(directory / ".saraswati-plugin" / "plugin.json", manifest)
        if secret_headers:
            secrets = _read_json(self.secret_file)
            secrets[plugin_id] = secret_headers
            _write_json_atomic(self.secret_file, secrets)
        self._mark_known(plugin_id, trusted=bool(raw.get("trusted", False)))
        self.reload()
        return self.require(plugin_id)

    def set_enabled(self, plugin_id: str, enabled: bool) -> PluginRecord:
        record = self.require(plugin_id)
        if enabled and record.missing_requirements:
            raise ValueError(f"插件尚未就绪：{', '.join(record.missing_requirements)}")
        needs_trust = any(item.transport == "stdio" for item in record.mcp_servers) or bool(
            record.frontend and record.frontend.get("permissions")
        )
        if enabled and needs_trust and not record.trusted:
            raise ValueError("该插件会访问本机能力或故事数据，启用前需要明确授权")
        state = _read_json(self.state_file)
        enabled_ids = set(state.get("enabled_plugins", []))
        if enabled:
            enabled_ids.add(plugin_id)
        else:
            enabled_ids.discard(plugin_id)
        state["enabled_plugins"] = sorted(enabled_ids)
        _write_json_atomic(self.state_file, state)
        record.enabled = enabled
        record.status, record.error = "idle", None
        return record

    def set_trusted(self, plugin_id: str, trusted: bool) -> PluginRecord:
        record = self.require(plugin_id)
        state = _read_json(self.state_file)
        trusted_ids = set(state.get("trusted_plugins", []))
        if trusted:
            trusted_ids.add(plugin_id)
        else:
            trusted_ids.discard(plugin_id)
            set_enabled = set(state.get("enabled_plugins", []))
            set_enabled.discard(plugin_id)
            state["enabled_plugins"] = sorted(set_enabled)
        state["trusted_plugins"] = sorted(trusted_ids)
        _write_json_atomic(self.state_file, state)
        record.trusted = trusted
        if not trusted:
            record.enabled = False
        return record

    def install_zip(self, payload: bytes, filename: str, source_url: str = "") -> PluginRecord:
        if len(payload) > MAX_PLUGIN_ARCHIVE_BYTES:
            raise ValueError("插件安装包超过 32 MiB")
        quarantine = self.root.parent / ".plugin-quarantine" / uuid4().hex
        quarantine.mkdir(parents=True, exist_ok=False)
        try:
            _extract_plugin_archive(payload, quarantine)
            manifests = _discover_archive_manifests(quarantine)
            if len(manifests) != 1:
                raise ValueError("插件包必须且只能包含一个插件清单")
            manifest_path = manifests[0]
            package_root = _manifest_directory(manifest_path)
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            record = _read_plugin_package(package_root, manifest_path, raw, False, False, {})
            destination = self.root / record.id
            if destination.exists():
                raise ValueError(f"插件已存在：{record.id}")
            shutil.move(str(package_root), str(destination))
            installed_at = datetime.now(UTC).isoformat()
            _write_json(destination / ".saraswati-provenance.json", {
                "source": "archive",
                "source_name": Path(filename).name,
                "source_url": source_url.strip(),
                "installed_at": installed_at,
            })
            self._mark_known(record.id, trusted=False)
            self.reload()
            return self.require(record.id)
        except zipfile.BadZipFile as exc:
            raise ValueError("文件不是有效的 ZIP 插件包") from exc
        finally:
            if quarantine.exists():
                shutil.rmtree(quarantine)

    def export_zip(self, plugin_id: str) -> bytes:
        record = self.require(plugin_id)
        root = Path(record.path)
        output = BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.is_symlink() and path.name != ".saraswati-provenance.json":
                    archive.write(path, f"{plugin_id}/{path.relative_to(root).as_posix()}")
        return output.getvalue()

    def archive(self, plugin_id: str) -> dict[str, str | bool]:
        record = self.require(plugin_id)
        source = Path(record.path).resolve()
        source.relative_to(self.root.resolve())
        archive_root = self.root.parent / ".plugin-archive"
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_id = f"{record.id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:6]}"
        shutil.move(str(source), str(archive_root / archive_id))
        secrets = _read_json(self.secret_file)
        secrets.pop(record.id, None)
        _write_json_atomic(self.secret_file, secrets)
        state = _read_json(self.state_file)
        for key in ("enabled_plugins", "trusted_plugins", "known_plugins"):
            values = set(state.get(key, []))
            values.discard(record.id)
            state[key] = sorted(values)
        _write_json_atomic(self.state_file, state)
        self.reload()
        return {"plugin_id": record.id, "archive_id": archive_id, "recoverable": True}

    def _mark_known(self, plugin_id: str, trusted: bool) -> None:
        state = _read_json(self.state_file)
        known = set(state.get("known_plugins", []))
        known.add(plugin_id)
        state["known_plugins"] = sorted(known)
        enabled = set(state.get("enabled_plugins", []))
        enabled.discard(plugin_id)
        state["enabled_plugins"] = sorted(enabled)
        if trusted:
            trusted_ids = set(state.get("trusted_plugins", []))
            trusted_ids.add(plugin_id)
            state["trusted_plugins"] = sorted(trusted_ids)
        _write_json_atomic(self.state_file, state)


class McpClient:
    """MCP SDK 适配层；每次调用建立隔离连接。"""

    @property
    def available(self) -> bool:
        return importlib.util.find_spec("mcp") is not None

    async def list_tools(self, server: McpServerRecord) -> list[dict[str, Any]]:
        async with self._session(server) as session:
            result = await session.list_tools()
            return [{
                "name": str(item.name),
                "description": str(item.description or ""),
                "inputSchema": dict(item.inputSchema or {"type": "object", "properties": {}}),
            } for item in getattr(result, "tools", []) or []]

    async def call_tool(self, server: McpServerRecord, name: str, arguments: dict[str, Any]) -> Any:
        async with self._session(server) as session:
            result = await session.call_tool(name, arguments=arguments)
            if getattr(result, "isError", False):
                raise ValueError(_mcp_result_text(result) or f"MCP 工具执行失败：{name}")
            structured = getattr(result, "structuredContent", None)
            return structured if structured is not None else {"content": _mcp_content(result)}

    def _session(self, server: McpServerRecord) -> Any:
        if not self.available:
            raise RuntimeError("尚未安装 MCP Python SDK；请重新安装 requirements.txt")
        return _McpSessionContext(server)


class _McpSessionContext:
    def __init__(self, server: McpServerRecord) -> None:
        self.server = server
        self._transport: Any = None
        self._session_context: Any = None
        self._http_client: Any = None

    async def __aenter__(self) -> Any:
        from mcp import ClientSession
        if self.server.transport == "stdio":
            from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client
            environment = get_default_environment()
            environment.update(self.server.env)
            environment.update({name: os.environ[name] for name in self.server.environment_variables if name in os.environ})
            parameters = StdioServerParameters(
                command=self.server.command,
                args=self.server.args,
                cwd=self.server.cwd or None,
                env=environment,
            )
            self._transport = stdio_client(parameters)
        elif self.server.transport == "sse":
            from mcp.client.sse import sse_client
            self._transport = sse_client(
                self.server.url,
                headers=self.server.headers or None,
                timeout=self.server.timeout_seconds,
                sse_read_timeout=max(60, self.server.timeout_seconds),
            )
        else:
            try:
                from mcp.client.streamable_http import streamable_http_client
            except ImportError:
                from mcp.client.streamable_http import streamablehttp_client as streamable_http_client
            if self.server.headers:
                from mcp.shared._httpx_utils import create_mcp_http_client
                self._http_client = create_mcp_http_client(headers=self.server.headers)
                await self._http_client.__aenter__()
            self._transport = streamable_http_client(self.server.url, http_client=self._http_client)
        streams = await self._transport.__aenter__()
        self._session_context = ClientSession(streams[0], streams[1])
        session = await self._session_context.__aenter__()
        await session.initialize()
        return session

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._session_context is not None:
            await self._session_context.__aexit__(exc_type, exc, traceback)
        if self._transport is not None:
            await self._transport.__aexit__(exc_type, exc, traceback)
        if self._http_client is not None:
            await self._http_client.__aexit__(exc_type, exc, traceback)


def validate_plugin_manifest(raw: dict[str, Any], enabled: bool, secret_headers: dict[str, str] | None = None) -> PluginRecord:
    """兼容旧测试和表单登记的单服务清单。"""
    plugin_id = str(raw.get("id") or raw.get("name") or "").strip().lower()
    root = Path.cwd()
    manifest = root / "plugin.json"
    return _read_plugin_package(root, manifest, raw, enabled, bool(raw.get("trusted", False)), secret_headers or {})


def _read_plugin_package(
    root: Path,
    manifest_path: Path,
    raw: dict[str, Any],
    enabled: bool,
    trusted: bool,
    secret_headers: dict[str, str],
) -> PluginRecord:
    plugin_id = str(raw.get("id") or raw.get("name") or root.name).strip().lower()
    if not IDENTIFIER_RE.fullmatch(plugin_id):
        raise ValueError("插件标识必须是安全的短标识符")
    interface = raw.get("interface") if isinstance(raw.get("interface"), dict) else {}
    author = raw.get("author")
    if isinstance(author, dict):
        author = str(author.get("name") or "")
    display_name = str(interface.get("displayName") or raw.get("display_name") or raw.get("name") or plugin_id)
    description = str(interface.get("shortDescription") or raw.get("description") or "")
    provenance = _read_json(root / ".saraswati-provenance.json")
    servers = _read_mcp_servers(root, raw, plugin_id, secret_headers)
    frontend = _read_frontend(root, raw.get("frontend"), display_name)
    skills_root = _resolve_component_path(root, raw.get("skills"), "skills")
    skills = []
    if skills_root and skills_root.is_dir():
        skills = sorted(path.parent.name for path in skills_root.rglob("SKILL.md"))
    resources = sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.name != ".saraswati-provenance.json"
    )
    missing: list[str] = []
    for server in servers:
        if server.transport == "stdio" and not (shutil.which(server.command) or Path(server.command).is_file()):
            missing.append(f"command:{server.command}")
        missing.extend(f"env:{name}" for name in server.environment_variables if name not in os.environ)
    primary = servers[0] if servers else McpServerRecord(id=plugin_id)
    capabilities = []
    if skills:
        capabilities.append("skills")
    if servers:
        capabilities.append("tools")
    if frontend:
        capabilities.append("frontend")
    manifest_format = "codex" if ".codex-plugin" in manifest_path.parts else "saraswati" if ".saraswati-plugin" in manifest_path.parts else "legacy"
    return PluginRecord(
        id=plugin_id,
        name=display_name[:96],
        description=description[:2048],
        version=str(raw.get("version") or "")[:64],
        enabled=enabled,
        path=str(root.resolve()),
        manifest_format=manifest_format,
        source=str(provenance.get("source") or "local"),
        author=str(author or "")[:256],
        license=str(raw.get("license") or "")[:64],
        homepage=str(raw.get("homepage") or "")[:2048],
        repository=str(raw.get("repository") or "")[:2048],
        keywords=_string_list(raw.get("keywords")),
        trusted=trusted,
        skills=skills,
        resources=resources,
        interface=dict(interface),
        frontend=frontend,
        mcp_servers=servers,
        capabilities=capabilities,
        allowed_tools=primary.allowed_tools,
        missing_requirements=sorted(set(missing)),
        installed_at=str(provenance.get("installed_at") or ""),
        source_url=str(provenance.get("source_url") or ""),
        url=primary.url,
        transport=primary.transport,
        command=primary.command,
        args=primary.args,
        environment_variables=primary.environment_variables,
        timeout_seconds=primary.timeout_seconds,
        auth_configured=any(bool(item.headers) for item in servers),
        header_names=sorted({name for item in servers for name in item.headers}),
    )


def _read_frontend(root: Path, value: Any, display_name: str) -> dict[str, Any] | None:
    if value in (None, False):
        return None
    config = {"entry": value} if isinstance(value, str) else dict(value) if isinstance(value, dict) else None
    if config is None:
        raise ValueError("frontend 必须是入口路径或配置对象")
    entry_value = str(config.get("entry") or "").strip()
    if not entry_value:
        raise ValueError("前端插件必须声明 frontend.entry")
    entry = _safe_component(root, entry_value)
    if entry.suffix.lower() not in {".html", ".htm"} or not entry.is_file() or entry.is_symlink():
        raise ValueError("frontend.entry 必须指向插件内存在的 HTML 文件")
    permissions = sorted(set(_string_list(config.get("permissions"))))
    unknown = [item for item in permissions if item not in FRONTEND_PERMISSIONS]
    if unknown:
        raise ValueError(f"不支持的前端插件权限：{unknown[0]}")
    surfaces = sorted(set(_string_list(config.get("surfaces")) or ["panel"]))
    unknown_surfaces = [item for item in surfaces if item not in FRONTEND_SURFACES]
    if unknown_surfaces:
        raise ValueError(f"不支持的前端插件表面：{unknown_surfaces[0]}")
    message_patterns = _string_list(config.get("message_patterns"))[:32]
    if any(len(item) > 256 for item in message_patterns):
        raise ValueError("前端插件消息匹配文本不能超过 256 个字符")
    character_extensions = [
        item for item in _string_list(config.get("character_extensions"))[:32]
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", item)
    ]
    if "message" in surfaces and not message_patterns and not character_extensions:
        raise ValueError("消息表面插件必须声明 message_patterns 或 character_extensions")
    return {
        "entry": entry.relative_to(root.resolve()).as_posix(),
        "title": str(config.get("title") or display_name)[:96],
        "permissions": permissions,
        "surfaces": surfaces,
        "message_patterns": message_patterns,
        "character_extensions": character_extensions,
        "height": max(320, min(int(config.get("height") or 620), 900)),
    }


def _read_mcp_servers(root: Path, raw: dict[str, Any], plugin_id: str, secret_headers: dict[str, str]) -> list[McpServerRecord]:
    configurations: dict[str, Any] = {}
    reference = raw.get("mcpServers")
    if isinstance(reference, str):
        path = _safe_component(root, reference)
        configurations = _read_json(path)
    elif isinstance(reference, dict):
        configurations = dict(reference)
    elif isinstance(raw.get("mcp"), dict):
        configurations = {plugin_id: raw["mcp"]}
    elif any(raw.get(key) for key in ("url", "command")):
        configurations = {plugin_id: raw}
    else:
        default = root / ".mcp.json"
        if default.is_file():
            configurations = _read_json(default)
    wrapped = configurations.get("mcp_servers") or configurations.get("mcpServers")
    if isinstance(wrapped, dict):
        configurations = wrapped
    servers: list[McpServerRecord] = []
    for server_id, value in configurations.items():
        if not isinstance(value, dict):
            continue
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "-", str(server_id)).strip("-")[:64] or "default"
        headers = {str(key): str(val) for key, val in dict(value.get("headers") or {}).items() if str(key) and str(val)}
        if len(configurations) == 1:
            headers.update({str(key): str(val) for key, val in secret_headers.items()})
        transport = str(value.get("transport") or value.get("type") or ("stdio" if value.get("command") else "streamable_http"))
        transport = "streamable_http" if transport in {"http", "streamable-http"} else transport.lower()
        if transport not in {"streamable_http", "sse", "stdio"}:
            raise ValueError(f"不支持的 MCP 连接方式：{transport}")
        url = str(value.get("url") or "").strip()
        command = _expand_plugin_path(root, str(value.get("command") or ""))
        if transport == "stdio":
            if not command or any(char in command for char in "\r\n\0"):
                raise ValueError("本机 MCP 服务必须提供有效的 command")
            url = ""
        else:
            _validate_url(url)
        tools = value.get("tools") if isinstance(value.get("tools"), dict) else {}
        allowed = value.get("allowed_tools", tools.get("include", []))
        excluded = value.get("excluded_tools", tools.get("exclude", []))
        env = {str(key): _expand_env(str(val)) for key, val in dict(value.get("env") or {}).items()}
        env_names = _string_list(value.get("environment_variables"))
        cwd = _expand_plugin_path(root, str(value.get("cwd") or str(root)))
        servers.append(McpServerRecord(
            id=safe_id,
            transport=transport,
            url=url,
            command=command,
            args=[_expand_plugin_path(root, str(item), only_explicit=True) for item in value.get("args", [])][:128],
            cwd=cwd,
            environment_variables=[item for item in env_names if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item)],
            env=env,
            allowed_tools=[item for item in _string_list(allowed) if re.fullmatch(r"[A-Za-z0-9_.-]+", item)],
            excluded_tools=[item for item in _string_list(excluded) if re.fullmatch(r"[A-Za-z0-9_.-]+", item)],
            timeout_seconds=max(1.0, min(float(value.get("timeout_seconds", 30)), 300.0)),
            headers=headers,
        ))
    return servers


def _discover_manifests(root: Path) -> list[Path]:
    discovered: list[Path] = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        manifest = next((directory / relative for relative in PLUGIN_MANIFESTS if (directory / relative).is_file()), None)
        if manifest:
            discovered.append(manifest)
    return discovered


def _discover_archive_manifests(root: Path) -> list[Path]:
    """Find one package in either a flat ZIP or a single wrapper directory."""
    discovered = [root / relative for relative in PLUGIN_MANIFESTS if (root / relative).is_file()]
    discovered.extend(_discover_manifests(root))
    return list(dict.fromkeys(path.resolve() for path in discovered))


def _manifest_directory(path: Path) -> Path:
    return path.parent.parent if path.parent.name in {".saraswati-plugin", ".codex-plugin"} else path.parent


def _resolve_component_path(root: Path, value: Any, default: str) -> Path | None:
    if value is False or value is None and not (root / default).exists():
        return None
    return _safe_component(root, str(value or f"./{default}"))


def _safe_component(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError("插件组件路径不得越出插件目录")
    target = (root / Path(*pure.parts)).resolve()
    target.relative_to(root.resolve())
    return target


def _expand_plugin_path(root: Path, value: str, only_explicit: bool = False) -> str:
    had_plugin_root = "${PLUGIN_ROOT}" in value
    expanded = value.replace("${PLUGIN_ROOT}", str(root.resolve()))
    if had_plugin_root:
        return str(Path(expanded).resolve())
    if expanded.startswith(("./", ".\\")):
        return str((root / expanded[2:]).resolve())
    if not only_explicit and expanded and (root / expanded).is_file():
        return str((root / expanded).resolve())
    return expanded


def _expand_env(value: str) -> str:
    pattern = re.compile(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)\}")
    return pattern.sub(lambda match: os.getenv(match.group(1), ""), value)


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("远程 MCP 必须使用 HTTPS；HTTP 只允许本机回环地址")
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("HTTP/SSE MCP 服务必须提供有效地址")


def _extract_plugin_archive(payload: bytes, destination: Path) -> None:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        files = [item for item in archive.infolist() if not item.is_dir()]
        if len(files) > MAX_PLUGIN_FILES:
            raise ValueError(f"插件文件数超过上限 {MAX_PLUGIN_FILES}")
        if sum(item.file_size for item in files) > MAX_PLUGIN_EXPANDED_BYTES:
            raise ValueError("插件解压后超过 64 MiB")
        for item in archive.infolist():
            relative = PurePosixPath(item.filename.replace("\\", "/"))
            if relative.is_absolute() or ".." in relative.parts or re.match(r"^[A-Za-z]:", item.filename):
                raise ValueError("插件安装包包含不安全路径")
            if stat.S_ISLNK((item.external_attr >> 16) & 0xFFFF):
                raise ValueError("插件安装包不允许包含符号链接")
            if item.flag_bits & 0x1:
                raise ValueError("不支持加密的插件安装包")
            target = destination / Path(*relative.parts)
            target.resolve().relative_to(destination.resolve())
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)


def _secret_headers(raw: dict[str, Any]) -> dict[str, str]:
    headers = {str(key): str(value) for key, value in dict(raw.get("headers") or {}).items() if str(key) and str(value)}
    token = str(raw.get("auth_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _plugin_type(record: PluginRecord) -> str:
    kinds = sum((bool(record.skills), bool(record.mcp_servers), bool(record.frontend)))
    if kinds > 1:
        return "hybrid"
    if record.skills:
        return "skill"
    if record.mcp_servers:
        return "tool"
    if record.frontend:
        return "app"
    return "resource"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _mcp_content(result: Any) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") if hasattr(item, "model_dump") else {"type": "text", "text": str(item)} for item in getattr(result, "content", []) or []]


def _mcp_result_text(result: Any) -> str:
    return "\n".join(str(item.get("text", "")) for item in _mcp_content(result) if item.get("type") == "text")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
