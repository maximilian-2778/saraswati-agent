"""有状态、可追踪、带最大步数限制的 Agent Runtime。"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.llm import ModelClient, ModelProviderError
from backend.models import (
    AgentTraceRecord,
    AuditIssueRecord,
    ChatRecord,
    MessageRecord,
    StateChangeRecord,
)
from backend.schemas import MessageRole
from backend.services.audit import AuditService
from backend.services.context import ContextBuilder
from backend.services.memory import MemoryService, RetrievedMemory
from backend.services.narrative_memory import NarrativeMemoryService
from backend.services.narrative_delta import NarrativeDeltaService
from backend.services.roleplay_graph import RoleplayGraphService
from backend.services.state import StateService
from backend.services.tools import TOOL_SCHEMAS, ToolExecutor
from backend.utils import json_dumps


@dataclass(slots=True)
class AgentTurnResult:
    turn_id: str
    assistant_message: MessageRecord
    retrieved_memories: list[RetrievedMemory]
    state_proposals: list[StateChangeRecord]
    audit_issues: list[AuditIssueRecord]
    traces: list[AgentTraceRecord]


class AgentRuntime:
    """负责上下文、模型调用、工具执行、记忆写入和一致性审计。"""

    def __init__(self, settings: Settings, model: ModelClient) -> None:
        self.settings = settings
        self.model = model
        self.memory_service = MemoryService(settings)
        self.state_service = StateService()
        self.audit_service = AuditService()
        self.graph_service = RoleplayGraphService()
        self.narrative_memory_service = NarrativeMemoryService(
            settings, self.memory_service
        )
        self.narrative_delta_service = NarrativeDeltaService()
        self.context_builder = ContextBuilder(
            settings,
            self.memory_service,
            self.state_service,
            self.narrative_memory_service,
            self.graph_service,
        )

    async def run_turn(
        self,
        db: Session,
        chat: ChatRecord,
        user_message: MessageRecord,
        on_token: Callable[[str], Awaitable[None]] | None = None,
    ) -> AgentTurnResult:
        turn_id = str(uuid4())
        context = await self.context_builder.build(
            db,
            self.model,
            chat,
            user_message.content,
        )
        self._trace(
            db,
            chat.id,
            turn_id,
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

        executor = ToolExecutor(
            db,
            self.model,
            chat.id,
            user_message.id,
            self.memory_service,
            self.state_service,
            self.graph_service,
        )
        working_messages = list(context.messages)
        final_content: str | None = None

        for step in range(1, self.settings.max_agent_steps + 1):
            try:
                reply = (
                    await self.model.stream_complete(
                        working_messages, TOOL_SCHEMAS, on_token
                    )
                    if on_token
                    else await self.model.complete(working_messages, TOOL_SCHEMAS)
                )
            except ModelProviderError as exc:
                self._trace(
                    db,
                    chat.id,
                    turn_id,
                    step,
                    "model_error",
                    {"error": str(exc)},
                )
                final_content = f"模型服务暂时不可用：{exc}"
                break

            self._trace(
                db,
                chat.id,
                turn_id,
                step,
                "model_response",
                {
                    "has_content": bool(reply.content),
                    "tool_names": [call.name for call in reply.tool_calls],
                },
            )
            if not reply.tool_calls:
                final_content = reply.content or "模型没有返回可显示的内容。"
                break

            working_messages.append(
                {
                    "role": "assistant",
                    "content": reply.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(
                                    call.arguments,
                                    ensure_ascii=False,
                                ),
                            },
                        }
                        for call in reply.tool_calls
                    ],
                }
            )
            for call in reply.tool_calls:
                try:
                    result = await executor.execute(call.name, call.arguments)
                    event_type = "tool_result"
                except (KeyError, TypeError, ValueError) as exc:
                    result = {"error": str(exc)}
                    event_type = "tool_error"
                self._trace(
                    db,
                    chat.id,
                    turn_id,
                    step,
                    event_type,
                    {"tool": call.name, "arguments": call.arguments, "result": result},
                )
                working_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json_dumps(result),
                    }
                )

        if final_content is None:
            working_messages.append(
                {
                    "role": "system",
                    "content": "工具调用已达到步数上限，请直接给出最终角色回复。",
                }
            )
            try:
                forced_reply = (
                    await self.model.stream_complete(working_messages, None, on_token)
                    if on_token
                    else await self.model.complete(working_messages, None)
                )
                final_content = forced_reply.content or "本轮未生成最终回复。"
            except ModelProviderError as exc:
                final_content = f"模型服务暂时不可用：{exc}"

        assistant_message = MessageRecord(
            id=str(uuid4()),
            chat_id=chat.id,
            role=MessageRole.ASSISTANT.value,
            content=final_content,
            created_at=datetime.now(UTC),
        )
        db.add(assistant_message)
        chat.updated_at = assistant_message.created_at
        db.commit()
        db.refresh(assistant_message)

        try:
            await self.narrative_memory_service.process_turn(
                db,
                self.model,
                chat.id,
                user_message,
                assistant_message,
            )
        except ModelProviderError as exc:
            # 自动整理属于辅助流程；失败时保留正文，不能让已经完成的对话报错。
            self._trace(
                db,
                chat.id,
                turn_id,
                self.settings.max_agent_steps + 1,
                "memory_pipeline_error",
                {"error": str(exc)},
            )

        delta = await self.narrative_delta_service.process_turn(
            db, self.model, chat.id, user_message, assistant_message
        )
        self._trace(
            db,
            chat.id,
            turn_id,
            self.settings.max_agent_steps + 1,
            "narrative_delta_created",
            {"delta_id": delta.id, "payload": json.loads(delta.payload_json)},
        )

        state_entries = self.state_service.list_entries(db, chat.id)
        issues = self.audit_service.audit_message(
            db,
            chat.id,
            assistant_message.id,
            assistant_message.content,
            state_entries,
        )
        self._trace(
            db,
            chat.id,
            turn_id,
            self.settings.max_agent_steps + 1,
            "turn_completed",
            {
                "assistant_message_id": assistant_message.id,
                "proposal_count": len(executor.created_proposals),
                "audit_count": len(issues),
            },
        )
        traces = list(
            db.scalars(
                select(AgentTraceRecord)
                .where(AgentTraceRecord.turn_id == turn_id)
                .order_by(AgentTraceRecord.created_at)
            ).all()
        )
        return AgentTurnResult(
            turn_id=turn_id,
            assistant_message=assistant_message,
            retrieved_memories=context.retrieved_memories,
            state_proposals=executor.created_proposals,
            audit_issues=issues,
            traces=traces,
        )

    async def generate_candidate(
        self,
        db: Session,
        chat: ChatRecord,
        user_message: MessageRecord,
    ) -> str:
        """基于原用户消息生成一个无副作用的候选回复。"""
        context = await self.context_builder.build(
            db,
            self.model,
            chat,
            user_message.content,
            through=user_message.created_at,
        )
        try:
            reply = await self.model.complete(context.messages, None)
        except ModelProviderError as exc:
            raise ModelProviderError(f"候选回复生成失败：{exc}") from exc
        return reply.content or "模型没有返回可显示的内容。"

    @staticmethod
    def _trace(
        db: Session,
        chat_id: str,
        turn_id: str,
        step: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        db.add(
            AgentTraceRecord(
                id=str(uuid4()),
                chat_id=chat_id,
                turn_id=turn_id,
                step=step,
                event_type=event_type,
                payload_json=json_dumps(payload),
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
