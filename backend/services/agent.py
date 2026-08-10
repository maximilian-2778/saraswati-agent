"""基于 LangGraph 的有状态 Agent Runtime。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import aiosqlite
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.extensions import ExtensionRuntime
from backend.llm import ModelClient, ModelProviderError
from backend.models import (
    AgentTraceRecord,
    AuditIssueRecord,
    ChatRecord,
    MemoryRecord,
    MessageRecord,
    StateChangeRecord,
)
from backend.services.agent_graph import (
    AgentGraphContext,
    AgentGraphState,
    build_agent_graph,
)
from backend.services.audit import AuditService
from backend.services.context import ContextBuilder
from backend.services.memory import MemoryService, RetrievedMemory
from backend.services.narrative_delta import NarrativeDeltaService
from backend.services.narrative_delta_apply import NarrativeDeltaApplier
from backend.services.narrative_memory import NarrativeMemoryService
from backend.services.roleplay_graph import RoleplayGraphService
from backend.services.state import StateService
from backend.services.world_engine import WorldEngineService
from backend.services.tools import ToolExecutor
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
    """通过 LangGraph 节点协调模型、工具、记忆和生成后审计。"""

    def __init__(self, settings: Settings, model: ModelClient) -> None:
        self.settings = settings
        self.model = model
        self.memory_service = MemoryService(settings)
        self.state_service = StateService()
        self.audit_service = AuditService()
        self.graph_service = RoleplayGraphService()
        self.narrative_memory_service = NarrativeMemoryService(
            settings,
            self.memory_service,
        )
        self.narrative_delta_service = NarrativeDeltaService()
        self.narrative_delta_applier = NarrativeDeltaApplier(
            self.state_service,
            self.graph_service,
        )
        self.world_engine_service = WorldEngineService()
        self.extensions = ExtensionRuntime()
        self.context_builder = ContextBuilder(
            settings,
            self.memory_service,
            self.state_service,
            self.narrative_memory_service,
            self.graph_service,
            self.world_engine_service,
        )
        self._checkpoint_connection: aiosqlite.Connection | None = None
        self._checkpointer: AsyncSqliteSaver | InMemorySaver = InMemorySaver(
            serde=_safe_serializer()
        )
        self.workflow = build_agent_graph(self._checkpointer)

    async def startup(self) -> None:
        """打开本地检查点数据库，并用持久化图替换内存图。"""
        if self._checkpoint_connection is not None:
            return
        checkpoint_path = self.settings.langgraph_checkpoint_path
        if not checkpoint_path:
            return
        path = Path(checkpoint_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(path.as_posix())
        checkpointer = AsyncSqliteSaver(connection, serde=_safe_serializer())
        await checkpointer.setup()
        self._checkpoint_connection = connection
        self._checkpointer = checkpointer
        self.workflow = build_agent_graph(checkpointer)

    async def shutdown(self) -> None:
        """关闭 LangGraph 检查点和模型客户端持有的连接。"""
        if self._checkpoint_connection is not None:
            await self._checkpoint_connection.close()
            self._checkpoint_connection = None
        close_model = getattr(self.model, "close", None)
        if close_model is not None:
            await close_model()

    async def run_turn(
        self,
        db: Session,
        chat: ChatRecord,
        user_message: MessageRecord,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        context_debug: bool = False,
    ) -> AgentTurnResult:
        """运行一轮已编译的 LangGraph 工作流，并恢复原有返回结构。"""
        turn_id = str(uuid4())
        assistant_message_id = str(uuid4())
        executor = ToolExecutor(
            db,
            self.model,
            chat.id,
            user_message.id,
            self.memory_service,
            self.state_service,
            self.graph_service,
            self.extensions,
        )
        dependencies = AgentGraphContext(
            db=db,
            chat=chat,
            user_message=user_message,
            settings=self.settings,
            model=self.model,
            context_builder=self.context_builder,
            memory_service=self.memory_service,
            state_service=self.state_service,
            audit_service=self.audit_service,
            graph_service=self.graph_service,
            narrative_memory_service=self.narrative_memory_service,
            narrative_delta_service=self.narrative_delta_service,
            narrative_delta_applier=self.narrative_delta_applier,
            world_engine_service=self.world_engine_service,
            tool_executor=executor,
            trace=self._trace,
            context_debug=context_debug,
            on_token=on_token,
            on_progress=on_progress,
        )
        initial_state: AgentGraphState = {
            "turn_id": turn_id,
            "chat_id": chat.id,
            "user_message_id": user_message.id,
            "assistant_message_id": assistant_message_id,
            "working_messages": [],
            "pending_tool_calls": [],
            "retrieved_memories": [],
            "state_proposal_ids": [],
            "audit_issue_ids": [],
            "step": 0,
            "final_content": "",
            "memory_status": "pending",
            "delta_id": "",
            "error": "",
            "turn_started_at": perf_counter(),
        }
        config = {
            "configurable": {"thread_id": f"turn:{turn_id}"},
            "recursion_limit": self.settings.max_agent_steps * 3 + 12,
        }
        state: AgentGraphState = await self.workflow.ainvoke(
            initial_state,
            config=config,
            context=dependencies,
        )
        assistant_message = db.get(MessageRecord, state["assistant_message_id"])
        if assistant_message is None:
            raise RuntimeError("LangGraph 已结束，但没有保存助手回复")

        retrieved_memories = _retrieved_memories(
            db,
            state.get("retrieved_memories", []),
        )
        state_proposals = _records_by_id(
            db,
            StateChangeRecord,
            state.get("state_proposal_ids", []),
        )
        audit_issues = _records_by_id(
            db,
            AuditIssueRecord,
            state.get("audit_issue_ids", []),
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
            retrieved_memories=retrieved_memories,
            state_proposals=state_proposals,
            audit_issues=audit_issues,
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


def _safe_serializer() -> JsonPlusSerializer:
    """只允许 LangGraph 内置安全类型进入检查点反序列化流程。"""
    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=None,
    )


def _retrieved_memories(
    db: Session,
    values: list[dict[str, Any]],
) -> list[RetrievedMemory]:
    records = _records_by_id(
        db,
        MemoryRecord,
        [str(item["id"]) for item in values],
    )
    by_id = {record.id: record for record in records}
    return [
        RetrievedMemory(
            record=by_id[str(item["id"])],
            score=float(item.get("score", 0.0)),
            reason=str(item.get("reason", "")),
        )
        for item in values
        if str(item["id"]) in by_id
    ]


def _records_by_id(
    db: Session,
    model_type: Any,
    record_ids: list[str],
) -> list[Any]:
    if not record_ids:
        return []
    records = list(
        db.scalars(select(model_type).where(model_type.id.in_(record_ids))).all()
    )
    by_id = {record.id: record for record in records}
    return [by_id[record_id] for record_id in record_ids if record_id in by_id]
