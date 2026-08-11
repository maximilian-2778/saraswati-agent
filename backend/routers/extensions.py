"""Skill 与 MCP Plugin 的本机扩展管理 API。"""

from __future__ import annotations

import mimetypes
import html as html_module
import ipaddress
from urllib.parse import urlparse, urljoin
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
import httpx
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.extensions import ExtensionRuntime
from backend.models import ChatRecord, ChatSkillBindingRecord, ChatSkillModeRecord


router = APIRouter(prefix="/extensions", tags=["extensions"])


class ExtensionToggle(BaseModel):
    enabled: bool


class PluginTrust(BaseModel):
    trusted: bool


class ChatSkillUpdate(BaseModel):
    mode: Literal["all", "selected"] = "all"
    skill_ids: list[str] = Field(default_factory=list, max_length=128)


class PluginCreate(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=1024)
    version: str = Field(default="", max_length=64)
    url: str = Field(default="", max_length=2048)
    transport: Literal["streamable_http", "sse", "stdio"] = "streamable_http"
    capabilities: list[Literal["tools"]] = Field(default_factory=lambda: ["tools"])
    allowed_tools: list[str] = Field(default_factory=list)
    command: str = Field(default="", max_length=2048)
    args: list[str] = Field(default_factory=list, max_length=64)
    environment_variables: list[str] = Field(default_factory=list, max_length=64)
    trusted: bool = False
    timeout_seconds: float = Field(default=30, ge=1, le=300)
    auth_token: str = Field(default="", max_length=8192)
    headers: dict[str, str] = Field(default_factory=dict)


@router.get("")
def list_extensions(request: Request) -> dict[str, Any]:
    return _runtime(request).catalog()


@router.post("/reload")
def reload_extensions(request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    runtime.reload()
    return runtime.catalog()


@router.patch("/skills/{skill_id}")
def toggle_skill(skill_id: str, payload: ExtensionToggle, request: Request) -> dict[str, Any]:
    try:
        runtime = _runtime(request)
        record = runtime.skills.set_enabled(skill_id, payload.enabled)
        runtime.invalidate_tools()
        return record.public()
    except ValueError as exc:
        code = status.HTTP_409_CONFLICT if "尚未就绪" in str(exc) else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post("/skills/install", status_code=status.HTTP_201_CREATED)
async def install_skill(
    request: Request,
    file: UploadFile = File(...),
    source_url: str = Form(default=""),
) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="请选择 ZIP 格式的 Skill 包")
    try:
        runtime = _runtime(request)
        record = runtime.skills.install_zip(await file.read(), file.filename or "skill.zip", source_url)
        runtime.invalidate_tools()
        return record.public()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.delete("/skills/{skill_id}")
def archive_skill(
    skill_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, str | bool]:
    try:
        runtime = _runtime(request)
        result = runtime.skills.archive(skill_id)
        runtime.invalidate_tools()
        db.execute(delete(ChatSkillBindingRecord).where(ChatSkillBindingRecord.skill_id == skill_id))
        db.commit()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/skills/{skill_id}/export")
def export_skill(skill_id: str, request: Request) -> Response:
    try:
        payload = _runtime(request).skills.export_zip(skill_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{skill_id}.zip"'},
    )


@router.get("/chats/{chat_id}/skills")
def get_chat_skills(chat_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    _chat_or_404(db, chat_id)
    mode = db.get(ChatSkillModeRecord, chat_id)
    skill_ids = db.scalars(
        select(ChatSkillBindingRecord.skill_id)
        .where(ChatSkillBindingRecord.chat_id == chat_id)
        .order_by(ChatSkillBindingRecord.skill_id)
    ).all()
    return {"chat_id": chat_id, "mode": mode.mode if mode else "all", "skill_ids": list(skill_ids)}


@router.put("/chats/{chat_id}/skills")
def update_chat_skills(
    chat_id: str,
    payload: ChatSkillUpdate,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _chat_or_404(db, chat_id)
    available = {item.id for item in _runtime(request).skills.list()}
    selected = sorted(set(payload.skill_ids))
    unknown = [item for item in selected if item not in available]
    if unknown:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Skill 不存在：{unknown[0]}")
    now = datetime.now(UTC)
    mode = db.get(ChatSkillModeRecord, chat_id)
    if mode is None:
        mode = ChatSkillModeRecord(chat_id=chat_id, mode=payload.mode, updated_at=now)
        db.add(mode)
    else:
        mode.mode = payload.mode
        mode.updated_at = now
    db.execute(delete(ChatSkillBindingRecord).where(ChatSkillBindingRecord.chat_id == chat_id))
    for skill_id in selected:
        db.add(ChatSkillBindingRecord(
            id=str(uuid4()), chat_id=chat_id, skill_id=skill_id, created_at=now
        ))
    db.commit()
    return {"chat_id": chat_id, "mode": payload.mode, "skill_ids": selected}


@router.post("/plugins", status_code=status.HTTP_201_CREATED)
def register_plugin(payload: PluginCreate, request: Request) -> dict[str, Any]:
    try:
        return _runtime(request).plugins.register(payload.model_dump()).public()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.patch("/plugins/{plugin_id}")
def toggle_plugin(plugin_id: str, payload: ExtensionToggle, request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        record = runtime.plugins.set_enabled(plugin_id, payload.enabled)
        runtime.reload()
        return runtime.plugins.require(record.id).public()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/plugins/{plugin_id}")
def archive_plugin(plugin_id: str, request: Request) -> dict[str, str | bool]:
    try:
        runtime = _runtime(request)
        result = runtime.plugins.archive(plugin_id)
        runtime.reload()
        return result
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/plugins/{plugin_id}/test")
async def test_plugin(plugin_id: str, request: Request) -> dict[str, Any]:
    runtime = _runtime(request)
    try:
        return await runtime.test_plugin(plugin_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"MCP 连接失败：{exc}") from exc


@router.post("/plugins/install", status_code=status.HTTP_201_CREATED)
async def install_plugin(
    request: Request,
    file: UploadFile = File(...),
    source_url: str = Form(default=""),
) -> dict[str, Any]:
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="请选择 ZIP 格式的插件包")
    try:
        runtime = _runtime(request)
        record = runtime.plugins.install_zip(await file.read(), file.filename or "plugin.zip", source_url)
        runtime.reload()
        return runtime.plugins.require(record.id).public()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/plugins/{plugin_id}/export")
def export_plugin(plugin_id: str, request: Request) -> Response:
    try:
        payload = _runtime(request).plugins.export_zip(plugin_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{plugin_id}.zip"'},
    )


@router.get("/plugins/{plugin_id}/ui/{asset_path:path}")
def plugin_frontend_asset(plugin_id: str, asset_path: str, request: Request) -> Response:
    """Serve only enabled plugin UI assets under a restrictive browser policy."""
    try:
        path = _runtime(request).plugins.frontend_asset(plugin_id, asset_path)
    except ValueError as exc:
        code = status.HTTP_409_CONFLICT if "尚未启用" in str(exc) else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {
        "Cache-Control": "no-store",
        "Access-Control-Allow-Origin": "*",
        "Cross-Origin-Resource-Policy": "cross-origin",
    }
    return Response(content=path.read_bytes(), media_type=media_type, headers=headers)


@router.get("/plugins/{plugin_id}/external")
async def plugin_external_frontend(plugin_id: str, url: str) -> Response:
    """Load an HTTPS card frontend through the compatibility wrapper.

    Tavern cards commonly use jQuery's ``load`` to pull a complete external page.
    The wrapper injects the local compatibility dependency before returning the
    page, while keeping ordinary plugins on the no-network policy.
    """
    if plugin_id != "tavern-card-frontend":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="外部前端代理仅供酒馆角色卡兼容器使用")
    parsed = _public_https_url(url)
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(15.0),
            headers={"User-Agent": "Saraswati-Agent-Tavern-Frontend/1.0"},
        ) as client:
            response = None
            for _ in range(4):
                response = await client.get(parsed)
                if response.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = response.headers.get("location")
                if not location:
                    break
                parsed = _public_https_url(urljoin(parsed, location))
            if response is None:
                raise ValueError("外部页面没有返回响应")
            response.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"外部角色卡前端加载失败：{exc}") from exc
    # Some Tavern cards bundle a complete game UI and exceed the size of a
    # small document. Keep a finite cap while allowing normal bundled pages.
    if len(response.content) > 16 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="外部角色卡前端超过 16 MiB 限制")
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower() and not response.text.lstrip().lower().startswith(("<!doctype html", "<html")):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="外部地址没有返回 HTML 页面")
    base_url = urljoin(str(response.url), ".")
    base_tag = f'<base href="{html_module.escape(base_url, quote=True)}">'
    jquery_tag = '<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>'
    page = response.text
    head_start = page.lower().find("<head")
    head_end = page.find(">", head_start) if head_start >= 0 else -1
    if head_end >= 0:
        page = page[: head_end + 1] + base_tag + jquery_tag + page[head_end + 1 :]
    else:
        page = f"<!doctype html><html><head>{base_tag}{jquery_tag}</head><body>{page}</body></html>"
    return Response(
        content=page.encode("utf-8"),
        media_type="text/html",
        headers={
            "Cache-Control": "no-store",
        },
    )


@router.post("/plugins/{plugin_id}/trust")
def trust_plugin(plugin_id: str, payload: PluginTrust, request: Request) -> dict[str, Any]:
    try:
        runtime = _runtime(request)
        runtime.plugins.set_trusted(plugin_id, payload.trusted)
        runtime.reload()
        return runtime.plugins.require(plugin_id).public()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _runtime(request: Request) -> ExtensionRuntime:
    return request.app.state.runtime.extensions


def _public_https_url(value: str) -> str:
    parsed = urlparse(str(value).strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() != "https" or not hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="外部角色卡前端只允许公开 HTTPS 地址")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不允许访问本机地址")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不允许访问内网地址")
    return parsed.geturl()


def _chat_or_404(db: Session, chat_id: str) -> ChatRecord:
    chat = db.get(ChatRecord, chat_id)
    if chat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="故事不存在")
    return chat
