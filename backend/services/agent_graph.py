"""Saraswati Agent 的 LangGraph 编排图。"""

from __future__ import annotations

import json
from time import perf_counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.llm import ModelClient, ModelProviderError
from backend.models import (
    AuditIssueRecord,
    ChatRecord,
    MessageRecord,
    NarrativeDeltaRecord,
    NarrativeLeafRecord,
)
from backend.schemas import MessageRole
from backend.services.audit import AuditService
from backend.services.context import ContextBuilder
from backend.services.memory import MemoryService
from backend.services.narrative_delta import NarrativeDeltaService
from backend.services.narrative_delta_apply import NarrativeDeltaApplier
from backend.services.narrative_memory import NarrativeMemoryService
from backend.services.roleplay_graph import RoleplayGraphService
from backend.services.state import StateService
from backend.services.tools import TOOL_SCHEMAS, ToolExecutor
from backend.services.token_budget import estimate_tokens
from backend.utils import json_dumps


TraceWriter = Callable[[Session, str, str, int, str, dict[str, Any]], None]
TokenWriter = Callable[[str], Awaitable[None]]
ProgressWriter = Callable[[str], Awaitable[None]]


class AgentGraphState(TypedDict, total=False):
    """节点之间传递并写入检查点的纯数据状态。"""

    turn_id: str
    chat_id: str
    user_message_id: str
    assistant_message_id: str
    working_messages: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    retrieved_memories: list[dict[str, Any]]
    state_proposal_ids: list[str]
    audit_issue_ids: list[str]
    step: int
    final_content: str
    memory_status: str
    delta_id: str
    error: str
    turn_started_at: float


@dataclass(slots=True)
class AgentGraphContext:
    """单次运行使用的依赖；这些对象不会写入 LangGraph 检查点。"""

    db: Session
    chat: ChatRecord
    user_message: MessageRecord
    settings: Settings
    model: ModelClient
    context_builder: ContextBuilder
    memory_service: MemoryService
    state_service: StateService
    audit_service: AuditService
    graph_service: RoleplayGraphService
    narrative_memory_service: NarrativeMemoryService
    narrative_delta_service: NarrativeDeltaService
    narrative_delta_applier: NarrativeDeltaApplier
    tool_executor: ToolExecutor
    trace: TraceWriter
    on_token: TokenWriter | None = None
    on_progress: ProgressWriter | None = None


def build_agent_graph(checkpointer: Any) -> Any:
    """构建并编译角色扮演 Agent 状态图。"""

    graph = StateGraph(AgentGraphState, context_schema=AgentGraphContext)
    graph.add_node("build_context", _build_context)
    graph.add_node("call_model", _call_model)
    graph.add_node("execute_tools", _execute_tools)
    graph.add_node("force_final_response", _force_final_response)
    graph.add_node("persist_response", _persist_response)
    graph.add_node("update_memory", _update_memory)
    graph.add_node("extract_delta", _extract_delta)
    graph.add_node("apply_narrative_delta", _apply_narrative_delta)
    graph.add_node("audit_response", _audit_response)

    graph.add_edge(START, "build_context")
    graph.add_edge("build_context", "call_model")
    graph.add_conditional_edges(
        "call_model",
        _route_after_model,
        {"tools": "execute_tools", "persist": "persist_response"},
    )
    graph.add_conditional_edges(
        "execute_tools",
        _route_after_tools,
        {"continue": "call_model", "force": "force_final_response"},
    )
    graph.add_edge("force_final_response", "persist_response")
    graph.add_edge("persist_response", "update_memory")
    graph.add_edge("update_memory", "extract_delta")
    graph.add_edge("extract_delta", "apply_narrative_delta")
    graph.add_edge("apply_narrative_delta", "audit_response")
    graph.add_edge("audit_response", END)
    return graph.compile(checkpointer=checkpointer, name="saraswati_roleplay_agent")


async def _build_context(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> dict[str, Any]:
    dependencies = runtime.context
    context = await dependencies.context_builder.build(
        dependencies.db,
        dependencies.model,
        dependencies.chat,
        dependencies.user_message.content,
    )
    dependencies.trace(
        dependencies.db,
        state["chat_id"],
        state["turn_id"],
        0,
        "context_built",
        {
            "message_count": len(context.messages),
            "memory_ids": [item.record.id for item in context.retrieved_memories],
            "state_count": context.state_count,
            "character_configured": context.character_configured,
            "world_entry_ids": context.world_entry_ids,
            "token_budget": context.diagnostics,
        },
    )
    return {
        "working_messages": list(context.messages),
        "retrieved_memories": [
            {
                "id": item.record.id,
                "score": item.score,
                "reason": item.reason,
            }
            for item in context.retrieved_memories
        ],
        "pending_tool_calls": [],
        "state_proposal_ids": [],
        "audit_issue_ids": [],
        "step": 0,
    }


async def _call_model(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> dict[str, Any]:
    dependencies = runtime.context
    step = state.get("step", 0) + 1
    messages = list(state.get("working_messages", []))
    started_at = perf_counter()
    input_tokens = _message_tokens(messages, dependencies.model.model_name)
    streamed_parts: list[str] = []

    async def forward_token(token: str) -> None:
        streamed_parts.append(token)

    try:
        reply = (
            await dependencies.model.stream_complete(
                messages,
                TOOL_SCHEMAS,
                forward_token,
            )
            if dependencies.on_token
            else await dependencies.model.complete(messages, TOOL_SCHEMAS)
        )
    except ModelProviderError as exc:
        # 请求尾部失败时，已经收到的正文仍然可以作为本轮结果使用。
        if streamed_parts and dependencies.on_token is not None:
            await dependencies.on_token("".join(streamed_parts))
        dependencies.trace(
            dependencies.db,
            state["chat_id"],
            state["turn_id"],
            step,
            "model_error",
            {
                "error": str(exc),
                "streamed_content_preserved": bool(streamed_parts),
                **_call_metrics(
                    dependencies.settings,
                    input_tokens,
                    estimate_tokens("".join(streamed_parts), dependencies.model.model_name),
                    perf_counter() - started_at,
                ),
            },
        )
        return {
            "step": step,
            "pending_tool_calls": [],
            "final_content": "".join(streamed_parts) or f"模型服务暂时不可用：{exc}",
            "error": str(exc),
        }

    dependencies.trace(
        dependencies.db,
        state["chat_id"],
        state["turn_id"],
        step,
        "model_response",
        {
            "has_content": bool(reply.content),
            "tool_names": [call.name for call in reply.tool_calls],
            **_call_metrics(
                dependencies.settings,
                input_tokens,
                _reply_tokens(reply.content, reply.tool_calls, dependencies.model.model_name),
                perf_counter() - started_at,
            ),
        },
    )
    if not reply.tool_calls:
        # 工具调用信息可能直到流的末尾才出现，因此每次模型调用先在后端
        # 暂存正文。只有确认这是最终回复后才交给前端，避免用户先看到一份
        # 完整草稿，工具执行后又看到模型从头生成一次。
        if streamed_parts and dependencies.on_token is not None:
            await dependencies.on_token("".join(streamed_parts))
        return {
            "step": step,
            "pending_tool_calls": [],
            "final_content": reply.content or "模型没有返回可显示的内容。",
        }

    calls = [
        {"id": call.id, "name": call.name, "arguments": call.arguments}
        for call in reply.tool_calls
    ]
    messages.append(
        {
            "role": "assistant",
            "content": reply.content,
            "tool_calls": [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(
                            call["arguments"],
                            ensure_ascii=False,
                        ),
                    },
                }
                for call in calls
            ],
        }
    )
    return {
        "step": step,
        "working_messages": messages,
        "pending_tool_calls": calls,
        "final_content": "",
    }


async def _execute_tools(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> dict[str, Any]:
    dependencies = runtime.context
    messages = list(state.get("working_messages", []))
    for call in state.get("pending_tool_calls", []):
        try:
            result = await dependencies.tool_executor.execute(
                str(call["name"]),
                dict(call.get("arguments") or {}),
            )
            event_type = "tool_result"
        except (KeyError, TypeError, ValueError) as exc:
            result = {"error": str(exc)}
            event_type = "tool_error"
        dependencies.trace(
            dependencies.db,
            state["chat_id"],
            state["turn_id"],
            state["step"],
            event_type,
            {
                "tool": call["name"],
                "arguments": call.get("arguments") or {},
                "result": result,
            },
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": json_dumps(result),
            }
        )
    return {
        "working_messages": messages,
        "pending_tool_calls": [],
        "state_proposal_ids": [
            record.id for record in dependencies.tool_executor.created_proposals
        ],
    }


async def _force_final_response(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> dict[str, Any]:
    dependencies = runtime.context
    messages = list(state.get("working_messages", []))
    messages.append(
        {
            "role": "system",
            "content": "工具调用已达到步数上限，请直接给出最终角色回复。",
        }
    )
    started_at = perf_counter()
    input_tokens = _message_tokens(messages, dependencies.model.model_name)
    streamed_parts: list[str] = []

    async def forward_token(token: str) -> None:
        streamed_parts.append(token)
        if dependencies.on_token is not None:
            await dependencies.on_token(token)

    try:
        reply = (
            await dependencies.model.stream_complete(
                messages,
                None,
                forward_token,
            )
            if dependencies.on_token
            else await dependencies.model.complete(messages, None)
        )
        final_content = reply.content or "本轮未生成最终回复。"
        dependencies.trace(
            dependencies.db,
            state["chat_id"],
            state["turn_id"],
            state["step"] + 1,
            "forced_model_response",
            {
                "has_content": bool(reply.content),
                **_call_metrics(
                    dependencies.settings,
                    input_tokens,
                    estimate_tokens(reply.content or "", dependencies.model.model_name),
                    perf_counter() - started_at,
                ),
            },
        )
        return {
            "working_messages": messages,
            "final_content": final_content,
        }
    except ModelProviderError as exc:
        dependencies.trace(
            dependencies.db,
            state["chat_id"],
            state["turn_id"],
            state["step"] + 1,
            "model_error",
            {
                "error": str(exc),
                "forced": True,
                "streamed_content_preserved": bool(streamed_parts),
                **_call_metrics(
                    dependencies.settings,
                    input_tokens,
                    estimate_tokens("".join(streamed_parts), dependencies.model.model_name),
                    perf_counter() - started_at,
                ),
            },
        )
        return {
            "working_messages": messages,
            "final_content": "".join(streamed_parts) or f"模型服务暂时不可用：{exc}",
            "error": str(exc),
        }


def _message_tokens(messages: list[dict[str, Any]], model_name: str | None) -> int:
    return sum(
        estimate_tokens(str(message.get("content") or ""), model_name)
        for message in messages
    )


def _reply_tokens(content: str | None, tool_calls: list[Any], model_name: str | None) -> int:
    text = content or ""
    if tool_calls:
        text += json.dumps(
            [{"name": call.name, "arguments": call.arguments} for call in tool_calls],
            ensure_ascii=False,
        )
    return estimate_tokens(text, model_name)


def _call_metrics(
    settings: Settings,
    input_tokens: int,
    output_tokens: int,
    duration_seconds: float,
) -> dict[str, Any]:
    estimated_cost = (
        input_tokens * settings.input_price_per_million
        + output_tokens * settings.output_price_per_million
    ) / 1_000_000
    return {
        "duration_ms": round(duration_seconds * 1000, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": round(estimated_cost, 8),
        "pricing_configured": bool(
            settings.input_price_per_million or settings.output_price_per_million
        ),
    }


async def _persist_response(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> dict[str, Any]:
    dependencies = runtime.context
    message = dependencies.db.get(MessageRecord, state["assistant_message_id"])
    if message is None:
        message = MessageRecord(
            id=state["assistant_message_id"],
            chat_id=state["chat_id"],
            role=MessageRole.ASSISTANT.value,
            content=state.get("final_content") or "本轮未生成最终回复。",
            created_at=datetime.now(UTC),
        )
        dependencies.db.add(message)
        dependencies.chat.updated_at = message.created_at
        dependencies.db.commit()
        dependencies.db.refresh(message)
    dependencies.trace(
        dependencies.db,
        state["chat_id"],
        state["turn_id"],
        state["step"],
        "response_persisted",
        {"assistant_message_id": message.id},
    )
    if dependencies.on_progress is not None:
        await dependencies.on_progress("postprocessing")
    return {"assistant_message_id": message.id}


async def _update_memory(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> dict[str, Any]:
    dependencies = runtime.context
    assistant_message = _message(dependencies.db, state["assistant_message_id"])
    existing_leaf = dependencies.db.scalar(
        select(NarrativeLeafRecord).where(
            NarrativeLeafRecord.assistant_message_id == assistant_message.id
        )
    )
    if existing_leaf is not None:
        return {"memory_status": "existing"}
    try:
        memory = await dependencies.narrative_memory_service.process_turn(
            dependencies.db,
            dependencies.model,
            state["chat_id"],
            dependencies.user_message,
            assistant_message,
        )
        return {"memory_status": "created" if memory else "disabled"}
    except ModelProviderError as exc:
        dependencies.trace(
            dependencies.db,
            state["chat_id"],
            state["turn_id"],
            dependencies.settings.max_agent_steps + 1,
            "memory_pipeline_error",
            {"error": str(exc)},
        )
        return {"memory_status": "failed", "error": str(exc)}


async def _extract_delta(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> dict[str, Any]:
    dependencies = runtime.context
    assistant_message = _message(dependencies.db, state["assistant_message_id"])
    delta = dependencies.db.scalar(
        select(NarrativeDeltaRecord).where(
            NarrativeDeltaRecord.assistant_message_id == assistant_message.id
        )
    )
    if delta is None:
        delta = await dependencies.narrative_delta_service.process_turn(
            dependencies.db,
            dependencies.model,
            state["chat_id"],
            dependencies.user_message,
            assistant_message,
        )
    dependencies.trace(
        dependencies.db,
        state["chat_id"],
        state["turn_id"],
        dependencies.settings.max_agent_steps + 1,
        "narrative_delta_created",
        {"delta_id": delta.id, "payload": json.loads(delta.payload_json)},
    )
    return {"delta_id": delta.id}


async def _apply_narrative_delta(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> dict[str, Any]:
    dependencies = runtime.context
    delta = dependencies.db.get(NarrativeDeltaRecord, state["delta_id"])
    if delta is None:
        return {}
    result = dependencies.narrative_delta_applier.apply(dependencies.db, delta)
    existing_ids = list(state.get("state_proposal_ids", []))
    applied_ids = [item.id for item in result.state_changes]
    proposal_ids = list(dict.fromkeys([*existing_ids, *applied_ids]))
    dependencies.trace(
        dependencies.db,
        state["chat_id"],
        state["turn_id"],
        dependencies.settings.max_agent_steps + 1,
        "narrative_delta_applied",
        {
            "delta_id": delta.id,
            "timeline_count": result.timeline_count,
            "scene_count": result.scene_count,
            "npc_count": result.npc_count,
            "state_change_ids": applied_ids,
            "deduplicated_count": result.skipped_count,
        },
    )
    return {"state_proposal_ids": proposal_ids}


async def _audit_response(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> dict[str, Any]:
    dependencies = runtime.context
    assistant_message = _message(dependencies.db, state["assistant_message_id"])
    issues = list(
        dependencies.db.scalars(
            select(AuditIssueRecord).where(
                AuditIssueRecord.message_id == assistant_message.id
            )
        ).all()
    )
    if not issues:
        entries = dependencies.state_service.list_entries(
            dependencies.db,
            state["chat_id"],
        )
        issues = dependencies.audit_service.audit_message(
            dependencies.db,
            state["chat_id"],
            assistant_message.id,
            assistant_message.content,
            entries,
        )
    proposal_ids = list(dict.fromkeys([
        *state.get("state_proposal_ids", []),
        *(record.id for record in dependencies.tool_executor.created_proposals),
    ]))
    dependencies.trace(
        dependencies.db,
        state["chat_id"],
        state["turn_id"],
        dependencies.settings.max_agent_steps + 1,
        "turn_completed",
        {
            "assistant_message_id": assistant_message.id,
            "proposal_count": len(proposal_ids),
            "audit_count": len(issues),
            "duration_ms": round(
                (perf_counter() - state.get("turn_started_at", perf_counter())) * 1000,
                2,
            ),
        },
    )
    return {
        "state_proposal_ids": proposal_ids,
        "audit_issue_ids": [issue.id for issue in issues],
    }


def _route_after_model(state: AgentGraphState) -> Literal["tools", "persist"]:
    return "tools" if state.get("pending_tool_calls") else "persist"


def _route_after_tools(
    state: AgentGraphState,
    runtime: Runtime[AgentGraphContext],
) -> Literal["continue", "force"]:
    return (
        "force"
        if state.get("step", 0) >= runtime.context.settings.max_agent_steps
        else "continue"
    )


def _message(db: Session, message_id: str) -> MessageRecord:
    message = db.get(MessageRecord, message_id)
    if message is None:
        raise RuntimeError(f"找不到工作流消息：{message_id}")
    return message
