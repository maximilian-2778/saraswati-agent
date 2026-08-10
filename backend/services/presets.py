"""Prompt 预设默认值、SillyTavern 导入和导出。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.models import PromptPresetRecord
from backend.schemas import PresetPrompt, PromptPresetCreate, PromptPresetRead
from backend.utils import json_dumps, json_loads


def default_prompts() -> list[PresetPrompt]:
    blocks = [
        ("main", "主提示词", "根据当前角色与故事继续进行沉浸式角色扮演。"),
        ("style", "文风指导", ""),
        ("negative", "禁止内容", ""),
        ("jailbreak", "历史后指令 / 破甲", ""),
    ]
    return [PresetPrompt(
        identifier=key,
        name=name,
        marker=False,
        content=content,
        position="in_chat" if key == "jailbreak" else "relative",
        depth=0,
    ) for key, name, content in blocks]


def preset_read(record: PromptPresetRecord, active_id: str | None) -> PromptPresetRead:
    return PromptPresetRead(
        id=record.id,
        name=record.name,
        description=record.description,
        temperature=record.temperature,
        top_p=record.top_p,
        max_output_tokens=record.max_output_tokens,
        presence_penalty=record.presence_penalty,
        frequency_penalty=record.frequency_penalty,
        context_window_tokens=record.context_window_tokens,
        prompts=_writing_prompts(json_loads(record.prompts_json) or []),
        extra_settings=json_loads(record.extra_settings_json) or {},
        active=record.id == active_id,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def create_record(payload: PromptPresetCreate, *, record_id: str | None = None) -> PromptPresetRecord:
    now = datetime.now(UTC)
    prompts = payload.prompts or default_prompts()
    return PromptPresetRecord(
        id=record_id or str(uuid4()), name=payload.name.strip(),
        description=payload.description.strip(), temperature=payload.temperature,
        top_p=payload.top_p, max_output_tokens=payload.max_output_tokens,
        presence_penalty=payload.presence_penalty,
        frequency_penalty=payload.frequency_penalty,
        context_window_tokens=payload.context_window_tokens,
        prompts_json=json_dumps([item.model_dump(mode="json") for item in prompts]),
        extra_settings_json=json_dumps(payload.extra_settings),
        created_at=now, updated_at=now,
    )


def import_payload(data: dict[str, Any], requested_name: str | None = None) -> PromptPresetCreate:
    prompts_raw = data.get("prompts") if isinstance(data.get("prompts"), list) else []
    enabled_by_id: dict[str, bool] = {}
    order_ids: list[str] = []
    orders = data.get("prompt_order")
    if isinstance(orders, list) and orders:
        selected = next((item for item in orders if item.get("character_id") == 100001), orders[0])
        for item in selected.get("order", []):
            identifier = str(item.get("identifier") or "")
            if identifier:
                order_ids.append(identifier)
                enabled_by_id[identifier] = bool(item.get("enabled", True))
    parsed: dict[str, PresetPrompt] = {}
    for index, item in enumerate(prompts_raw):
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("identifier") or f"custom-{index}")
        parsed[identifier] = PresetPrompt(
            identifier=identifier,
            name=str(item.get("name") or identifier),
            role=str(item.get("role") or "system"),
            content=str(item.get("content") or ""),
            enabled=bool(item.get("enabled", enabled_by_id.get(identifier, True))),
            marker=bool(item.get("marker", False)),
            position="in_chat" if item.get("injection_position") == 1 or item.get("position") == "in_chat" else "relative",
            depth=max(0, int(item.get("injection_depth", item.get("depth", 0)) or 0)),
        )
    ordered = [parsed.pop(identifier) for identifier in order_ids if identifier in parsed]
    ordered.extend(parsed.values())
    ordered = [item for item in ordered if not item.marker and item.identifier not in _DYNAMIC_SLOT_IDS]
    if not ordered:
        ordered = default_prompts()
    known = {
        "name", "temperature", "top_p", "openai_max_tokens", "max_output_tokens",
        "frequency_penalty", "presence_penalty", "openai_max_context",
        "context_window_tokens", "prompts", "prompt_order",
    }
    return PromptPresetCreate(
        name=(requested_name or str(data.get("name") or "导入预设")).strip(),
        description="从 SillyTavern JSON 导入" if "prompt_order" in data else str(data.get("description") or ""),
        temperature=float(data.get("temperature", 0.8)),
        top_p=float(data.get("top_p", 1.0)),
        max_output_tokens=int(data.get("openai_max_tokens", data.get("max_output_tokens", 2048))),
        presence_penalty=float(data.get("presence_penalty", 0.0)),
        frequency_penalty=float(data.get("frequency_penalty", 0.0)),
        context_window_tokens=int(data.get("openai_max_context", data.get("context_window_tokens", 32768))),
        prompts=ordered,
        extra_settings={
            **{key: value for key, value in data.items() if key not in known},
            "_sillytavern_original": data,
        },
    )


def export_sillytavern(record: PromptPresetRecord) -> dict[str, Any]:
    prompts = [item.model_dump(mode="json") for item in _writing_prompts(json_loads(record.prompts_json) or [])]
    extra = json_loads(record.extra_settings_json) or {}
    original = extra.pop("_sillytavern_original", None)
    result = dict(original) if isinstance(original, dict) else {}
    original_prompts = result.get("prompts") if isinstance(result.get("prompts"), list) else []
    current_by_id = {item["identifier"]: item for item in prompts}
    merged_prompts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in original_prompts:
        if not isinstance(raw, dict):
            continue
        identifier = str(raw.get("identifier") or "")
        current = current_by_id.get(identifier)
        if current:
            raw = {**raw, "name": current["name"], "role": current["role"], "content": current["content"]}
            seen.add(identifier)
        merged_prompts.append(raw)
    merged_prompts.extend(
        {key: value for key, value in item.items() if key not in {"enabled", "position", "depth"}}
        for item in prompts if item["identifier"] not in seen
    )
    original_orders = result.get("prompt_order") if isinstance(result.get("prompt_order"), list) else []
    prompt_order = [item for item in original_orders if isinstance(item, dict) and item.get("character_id") != 100001]
    prompt_order.insert(0, {
        "character_id": 100001,
        "order": [{"identifier": item["identifier"], "enabled": item.get("enabled", True)} for item in prompts],
    })
    result.update({
        **extra,
        "temperature": record.temperature,
        "top_p": record.top_p,
        "openai_max_tokens": record.max_output_tokens,
        "presence_penalty": record.presence_penalty,
        "frequency_penalty": record.frequency_penalty,
        "openai_max_context": record.context_window_tokens,
        "prompts": merged_prompts,
        "prompt_order": prompt_order,
    })
    return result


_DYNAMIC_SLOT_IDS = {
    "worldInfoBefore", "worldInfoAfter", "personaDescription", "charDescription",
    "charPersonality", "scenario", "dialogueExamples", "longTermMemory",
    "ragMemory", "roleplayState", "chatHistory",
}


def _writing_prompts(items: list[Any]) -> list[PresetPrompt]:
    result: list[PresetPrompt] = []
    for item in items:
        try:
            prompt = PresetPrompt.model_validate(item)
        except (TypeError, ValueError):
            continue
        if prompt.marker or prompt.identifier in _DYNAMIC_SLOT_IDS:
            continue
        result.append(prompt)
    return result or default_prompts()
