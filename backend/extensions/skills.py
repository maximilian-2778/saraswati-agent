"""Agent Skills 发现、分级读取和本地安装安全检查。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
import zipfile
from datetime import UTC, datetime
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Any
from uuid import uuid4

import yaml


MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_SKILL_FILES = 64
MAX_SKILL_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024
SUPPORT_DIRS = frozenset({"references", "templates", "assets", "scripts"})
EXCLUDED_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__"})
INVISIBLE_CHARS = frozenset({"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"})
IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


@dataclass(slots=True)
class SkillRecord:
    id: str
    name: str
    description: str
    version: str
    author: str
    path: str
    enabled: bool
    plugin_id: str = ""
    source: str = "local"
    read_only: bool = True
    tags: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    digest: str = ""
    warnings: list[str] = field(default_factory=list)
    license: str = ""
    compatibility: str = ""
    platforms: list[str] = field(default_factory=list)
    required_environment_variables: list[str] = field(default_factory=list)
    required_commands: list[str] = field(default_factory=list)
    missing_requirements: list[str] = field(default_factory=list)
    readiness: str = "ready"
    installed_at: str = ""
    source_url: str = ""
    view_count: int = 0
    use_count: int = 0
    last_used_at: str = ""

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("path", None)
        data["location"] = (
            f"data/extensions/plugins/{self.plugin_id}/skills"
            if self.plugin_id else f"data/extensions/skills/{self.id}"
        )
        return data


class SkillRegistry:
    """只扫描受控目录；第三方 Skill 仅作为只读说明和资源。"""

    def __init__(self, root: Path, state_file: Path) -> None:
        self.root = root
        self.state_file = state_file
        self._skills: dict[str, SkillRecord] = {}
        self._disabled: set[str] = set()
        self._plugin_roots: dict[str, list[Path]] = {}
        self._usage = SkillUsageStore(root.parent / "skill-usage.json")

    def set_plugin_roots(self, roots: dict[str, list[Path]]) -> None:
        self._plugin_roots = roots

    def reload(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._disabled = set(_read_json(self.state_file).get("disabled_skills", []))
        discovered: dict[str, SkillRecord] = {}
        for skill_md in sorted(self.root.rglob("SKILL.md")):
            if any(part in EXCLUDED_DIRS for part in skill_md.parts):
                continue
            if _is_nested_support_skill(skill_md, self.root):
                continue
            try:
                record = self._read_record(skill_md)
            except (OSError, ValueError):
                continue
            if record.id not in discovered:
                discovered[record.id] = record
        for plugin_id, roots in sorted(self._plugin_roots.items()):
            for plugin_root in roots:
                for skill_md in sorted(plugin_root.rglob("SKILL.md")):
                    if any(part in EXCLUDED_DIRS for part in skill_md.parts):
                        continue
                    if _is_nested_support_skill(skill_md, plugin_root):
                        continue
                    try:
                        record = self._read_record(skill_md, plugin_root, plugin_id)
                    except (OSError, ValueError):
                        continue
                    discovered.setdefault(record.id, record)
        self._skills = discovered

    def list(self) -> list[SkillRecord]:
        return sorted(self._skills.values(), key=lambda item: item.name.lower())

    def enabled(self) -> list[SkillRecord]:
        return [item for item in self.list() if item.enabled]

    def set_enabled(self, skill_id: str, enabled: bool) -> SkillRecord:
        record = self.require(skill_id)
        if enabled and record.readiness != "ready":
            raise ValueError(f"Skill 尚未就绪：{', '.join(record.missing_requirements) or record.readiness}")
        if enabled:
            self._disabled.discard(skill_id)
        else:
            self._disabled.add(skill_id)
        state = _read_json(self.state_file)
        state["disabled_skills"] = sorted(self._disabled)
        _write_json(self.state_file, state)
        record.enabled = enabled and record.readiness == "ready"
        return record

    def require(self, skill_id: str) -> SkillRecord:
        record = self._skills.get(skill_id)
        if record is None:
            raise ValueError(f"Skill 不存在：{skill_id}")
        return record

    def view(self, skill_id: str, resource: str | None = None) -> dict[str, Any]:
        record = self.require(skill_id)
        if not record.enabled:
            raise ValueError(f"Skill 已停用：{skill_id}")
        skill_root = Path(record.path)
        target = skill_root / "SKILL.md" if not resource else _safe_child(skill_root, resource)
        if resource and resource not in record.resources:
            raise ValueError(f"Skill 资源不存在或不可读取：{resource}")
        content = target.read_text(encoding="utf-8-sig", errors="replace")
        frontmatter, body = parse_frontmatter(content)
        self._usage.bump(skill_id, "view")
        self._apply_usage(record)
        return {
            "skill": record.id,
            "resource": resource or "SKILL.md",
            "content": body.strip() if not resource else content,
            "metadata": frontmatter if not resource else {},
            "resources": record.resources if not resource else [],
            "read_only": True,
        }

    def record_use(self, skill_id: str) -> None:
        record = self.require(skill_id)
        self._usage.bump(skill_id, "use")
        self._apply_usage(record)

    def install_zip(
        self,
        payload: bytes,
        filename: str,
        source_url: str = "",
    ) -> SkillRecord:
        """在隔离目录解包并扫描 Skill；校验通过后才原子移入活动目录。"""
        if len(payload) > MAX_ARCHIVE_BYTES:
            raise ValueError("Skill 压缩包超过 4 MiB")
        quarantine_root = self.root.parent / ".quarantine" / uuid4().hex
        quarantine_root.mkdir(parents=True, exist_ok=False)
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                files = [item for item in archive.infolist() if not item.is_dir()]
                if len(files) > MAX_SKILL_FILES:
                    raise ValueError(f"Skill 文件数超过上限 {MAX_SKILL_FILES}")
                if sum(item.file_size for item in files) > MAX_SKILL_BYTES:
                    raise ValueError("Skill 解压后超过 2 MiB")
                for item in archive.infolist():
                    relative = _safe_archive_path(item.filename)
                    mode = (item.external_attr >> 16) & 0xFFFF
                    if stat.S_ISLNK(mode):
                        raise ValueError("Skill 压缩包不允许包含符号链接")
                    if item.flag_bits & 0x1:
                        raise ValueError("不支持加密的 Skill 压缩包")
                    target = quarantine_root / Path(*relative.parts)
                    target.resolve().relative_to(quarantine_root.resolve())
                    if item.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
            candidates = [
                path for path in quarantine_root.rglob("SKILL.md")
                if not _is_nested_support_skill(path, quarantine_root)
            ]
            if len(candidates) != 1:
                raise ValueError("压缩包必须且只能包含一个主 SKILL.md")
            record = self._read_record(candidates[0], quarantine_root)
            severe = [warning for warning in record.warnings if "可执行文件" in warning or "不可见 Unicode" in warning]
            if severe:
                raise ValueError(f"Skill 安全扫描未通过：{severe[0]}")
            destination = self.root / record.id
            if destination.exists():
                raise ValueError(f"Skill 已存在：{record.id}")
            self.root.mkdir(parents=True, exist_ok=True)
            shutil.move(str(candidates[0].parent), str(destination))
            installed_at = datetime.now(UTC).isoformat()
            _write_json(destination / ".saraswati-provenance.json", {
                "source": "archive",
                "source_name": Path(filename).name,
                "source_url": source_url.strip(),
                "installed_at": installed_at,
                "digest": record.digest,
            })
            self._usage.record_install(record.id, installed_at)
            self.reload()
            return self.require(record.id)
        except zipfile.BadZipFile as exc:
            raise ValueError("文件不是有效的 ZIP 压缩包") from exc
        finally:
            if quarantine_root.exists():
                shutil.rmtree(quarantine_root)

    def archive(self, skill_id: str) -> dict[str, str | bool]:
        record = self.require(skill_id)
        if record.plugin_id:
            raise ValueError("插件内置技能请通过归档插件移除")
        source = Path(record.path).resolve()
        source.relative_to(self.root.resolve())
        archive_root = self.root.parent / ".archive"
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_id = f"{skill_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        destination = archive_root / archive_id
        shutil.move(str(source), str(destination))
        self._usage.mark_archived(skill_id)
        self.reload()
        return {"skill_id": skill_id, "archive_id": archive_id, "recoverable": True}

    def export_zip(self, skill_id: str) -> bytes:
        record = self.require(skill_id)
        root = Path(record.path)
        output = BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.is_symlink() and path.name != ".saraswati-provenance.json":
                    archive.write(path, f"{skill_id}/{path.relative_to(root).as_posix()}")
        return output.getvalue()

    def match_explicit(self, text: str) -> SkillRecord | None:
        match = re.match(r"^/([a-zA-Z0-9_-]{1,64})(?:\s|$)", text.strip())
        if not match:
            return None
        return next(
            (item for item in self.enabled() if item.id == match.group(1) or item.name == match.group(1)),
            None,
        )

    def _read_record(
        self,
        skill_md: Path,
        allowed_root: Path | None = None,
        plugin_id: str = "",
    ) -> SkillRecord:
        root = skill_md.parent.resolve()
        root.relative_to((allowed_root or self.root).resolve())
        content = skill_md.read_text(encoding="utf-8-sig", errors="replace")
        frontmatter, body = parse_frontmatter(content)
        native_id = str(frontmatter.get("id") or root.name).strip().lower()
        if not IDENTIFIER_RE.fullmatch(native_id):
            raise ValueError("Skill id 必须是安全的短标识符")
        skill_id = _plugin_skill_id(plugin_id, native_id) if plugin_id else native_id
        name = str(frontmatter.get("name") or native_id).strip()[:MAX_NAME_LENGTH]
        description = str(frontmatter.get("description") or _first_paragraph(body)).strip()
        description = description[:MAX_DESCRIPTION_LENGTH]
        if not name or not description:
            raise ValueError("SKILL.md 必须提供 name 和 description")
        warnings, digest = scan_skill_bundle(root)
        resources = _list_resources(root)
        platforms = _string_list(frontmatter.get("platforms"))
        required_env, required_commands = _requirements(frontmatter)
        missing = [f"env:{name}" for name in required_env if not os.getenv(name)]
        missing.extend(f"command:{name}" for name in required_commands if shutil.which(name) is None)
        platform_ready = _matches_platform(platforms)
        readiness = "incompatible" if not platform_ready else "missing_requirements" if missing else "ready"
        provenance = _read_json(root / ".saraswati-provenance.json")
        record = SkillRecord(
            id=skill_id,
            name=name,
            description=description,
            version=str(frontmatter.get("version") or "").strip(),
            author=str(frontmatter.get("author") or "").strip(),
            path=str(root),
            enabled=skill_id not in self._disabled and readiness == "ready",
            plugin_id=plugin_id,
            tags=_string_list(frontmatter.get("tags")),
            resources=resources,
            digest=digest,
            warnings=warnings,
            license=str(frontmatter.get("license") or "").strip(),
            compatibility=str(frontmatter.get("compatibility") or "").strip(),
            platforms=platforms,
            required_environment_variables=required_env,
            required_commands=required_commands,
            missing_requirements=missing,
            readiness=readiness,
            source=f"plugin:{plugin_id}" if plugin_id else str(provenance.get("source") or "local"),
            source_url=str(provenance.get("source_url") or ""),
            installed_at=str(provenance.get("installed_at") or ""),
        )
        self._apply_usage(record)
        return record

    def _apply_usage(self, record: SkillRecord) -> None:
        usage = self._usage.get(record.id)
        record.view_count = int(usage.get("view_count", 0))
        record.use_count = int(usage.get("use_count", 0))
        record.last_used_at = str(usage.get("last_used_at") or "")


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """使用 SafeLoader 解析 Agent Skills YAML；拒绝自定义对象标签。"""
    content = content.lstrip("\ufeff")
    if not content.startswith("---"):
        return {}, content
    match = re.search(r"\n---\s*(?:\n|$)", content[3:])
    if not match:
        return {}, content
    raw = content[3 : match.start() + 3]
    body = content[match.end() + 3 :]
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"SKILL.md YAML frontmatter 无效：{exc}") from exc
    return (parsed if isinstance(parsed, dict) else {}), body


def scan_skill_bundle(root: Path) -> tuple[list[str], str]:
    files = [
        path for path in root.rglob("*")
        if path.is_file() and path.name != ".saraswati-provenance.json"
    ]
    if len(files) > MAX_SKILL_FILES:
        raise ValueError(f"Skill 文件数超过上限 {MAX_SKILL_FILES}")
    total = sum(path.stat().st_size for path in files)
    if total > MAX_SKILL_BYTES:
        raise ValueError("Skill 总大小超过 2 MiB")
    digest = hashlib.sha256()
    warnings: list[str] = []
    for path in sorted(files):
        if path.is_symlink():
            raise ValueError("Skill 不允许包含符号链接")
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        digest.update(relative.encode("utf-8") + b"\0" + data)
        if path.suffix.lower() in {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".js", ".ts"}:
            text = data.decode("utf-8", errors="replace").lstrip("\ufeff")
            if any(char in text for char in INVISIBLE_CHARS):
                warnings.append(f"{relative} 含不可见 Unicode 字符")
        if path.suffix.lower() in {".exe", ".dll", ".bat", ".cmd", ".ps1"}:
            warnings.append(f"{relative} 是可执行文件；Saraswati 不会执行它")
    return warnings, f"sha256:{digest.hexdigest()}"


def _list_resources(root: Path) -> list[str]:
    resources: list[str] = []
    for directory in SUPPORT_DIRS:
        support = root / directory
        if not support.exists():
            continue
        for path in support.rglob("*"):
            if path.is_file() and not path.is_symlink():
                resources.append(path.relative_to(root).as_posix())
    return sorted(resources)


def _safe_child(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError("资源路径不得越出 Skill 目录")
    target = (root / Path(*pure.parts)).resolve()
    target.relative_to(root.resolve())
    if target.is_symlink() or not target.is_file():
        raise ValueError("资源路径无效")
    return target


def _safe_archive_path(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if not normalized or pure.is_absolute() or ".." in pure.parts or re.match(r"^[A-Za-z]:", normalized):
        raise ValueError("Skill 压缩包包含不安全路径")
    return pure


def _is_nested_support_skill(path: Path, scan_root: Path) -> bool:
    relative = path.relative_to(scan_root)
    return any(part in SUPPORT_DIRS for part in relative.parts[:-1])


def _first_paragraph(body: str) -> str:
    return next((line.strip() for line in body.splitlines() if line.strip() and not line.startswith("#")), "")


def _plugin_skill_id(plugin_id: str, native_id: str) -> str:
    value = f"{plugin_id}--{native_id}"
    if len(value) <= 64:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{value[:55]}-{digest}"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _requirements(frontmatter: dict[str, Any]) -> tuple[list[str], list[str]]:
    environment = _string_list(frontmatter.get("required_environment_variables"))
    commands: list[str] = []
    prerequisites = frontmatter.get("prerequisites")
    if isinstance(prerequisites, dict):
        environment.extend(_string_list(prerequisites.get("env_vars")))
        commands.extend(_string_list(prerequisites.get("commands")))
    setup = frontmatter.get("setup")
    if isinstance(setup, dict):
        environment.extend(_string_list(setup.get("required_environment_variables")))
    safe_env = sorted({item for item in environment if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item)})
    safe_commands = sorted({item for item in commands if re.fullmatch(r"[A-Za-z0-9_.+-]+", item)})
    return safe_env, safe_commands


def _matches_platform(platforms: list[str]) -> bool:
    if not platforms:
        return True
    current = "windows" if sys.platform.startswith("win") else "macos" if sys.platform == "darwin" else "linux"
    return current in {item.lower().strip() for item in platforms}


class SkillUsageStore:
    """轻量、原子写入的 Skill 使用与来源侧车。"""

    _lock = Lock()

    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, skill_id: str) -> dict[str, Any]:
        return dict(_read_json(self.path).get(skill_id) or {})

    def bump(self, skill_id: str, kind: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            data = _read_json(self.path)
            record = dict(data.get(skill_id) or {})
            key = "view_count" if kind == "view" else "use_count"
            record[key] = max(0, int(record.get(key, 0))) + 1
            record["last_viewed_at" if kind == "view" else "last_used_at"] = now
            data[skill_id] = record
            _write_json_atomic(self.path, data)

    def record_install(self, skill_id: str, installed_at: str) -> None:
        with self._lock:
            data = _read_json(self.path)
            record = dict(data.get(skill_id) or {})
            record.update({"installed_at": installed_at, "archived": False})
            data[skill_id] = record
            _write_json_atomic(self.path, data)

    def mark_archived(self, skill_id: str) -> None:
        with self._lock:
            data = _read_json(self.path)
            record = dict(data.get(skill_id) or {})
            record.update({"archived": True, "archived_at": datetime.now(UTC).isoformat()})
            data[skill_id] = record
            _write_json_atomic(self.path, data)


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
