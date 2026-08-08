"""Saraswati Agent 的 HTTP API 路由。"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.config import Settings, save_local_settings
from backend.llm import ModelProviderError, build_model_client
from backend.models import (
    AgentTraceRecord,
    AuditIssueRecord,
    ChatRecord,
    CharacterProfileRecord,
    MemoryRecord,
    MessageRecord,
    StateChangeRecord,
    WorldBookEntryRecord,
)
from backend.schemas import (
    AgentTraceRead,
    AgentTurnRead,
    AuditIssueRead,
    AuditResolution,
    AuditStatus,
    ChatCreate,
    ChatRead,
    CharacterProfileRead,
    CharacterProfileUpdate,
    HealthRead,
    MemoryCreate,
    MemoryKind,
    MemoryRead,
    MemorySearchRequest,
    MemorySearchResult,
    MemorySummaryRequest,
    MessageRead,
    MessageRole,
    MessageSend,
    ProposalStatus,
    RuntimeInfo,
    SettingsRead,
    SettingsTestResult,
    SettingsUpdate,
    StateChangeRead,
    StateEntryRead,
    StateProposalCreate,
    StateResolution,
    WorldBookEntryCreate,
    WorldBookEntryRead,
    WorldBookEntryUpdate,
)
from backend.serializers import (
    audit_read,
    chat_read,
    character_read,
    memory_read,
    message_read,
    state_change_read,
    state_entry_read,
    trace_read,
    world_book_read,
)
from backend.services.agent import AgentRuntime
from backend.utils import json_dumps


router = APIRouter()

# 系统级路由负责健康检查、运行状态和本机设置管理。


@router.get("/health", response_model=HealthRead, tags=["system"])
def health_check() -> HealthRead:
    """确认后端进程已经启动。"""
    return HealthRead()


@router.get("/runtime", response_model=RuntimeInfo, tags=["system"])
def runtime_info(request: Request) -> RuntimeInfo:
    """返回当前模型模式和 Agent 运行参数，不暴露 API Key。"""
    settings = request.app.state.settings
    model = request.app.state.model
    return RuntimeInfo(
        provider_mode=model.mode,
        model=model.model_name,
        embedding_model=settings.embedding_model,
        max_agent_steps=settings.max_agent_steps,
    )


@router.get("/settings", response_model=SettingsRead, tags=["system"])
def read_settings(request: Request) -> SettingsRead:
    """读取设置中心需要的数据，同时隐藏 API Key 明文。"""
    return _settings_read(request.app.state.settings)


@router.put("/settings", response_model=SettingsRead, tags=["system"])
def update_settings(payload: SettingsUpdate, request: Request) -> SettingsRead:
    """保存设置并立即重建模型客户端和 Agent Runtime。"""
    current: Settings = request.app.state.settings
    api_key = current.llm_api_key
    if payload.clear_api_key:
        api_key = None
    elif payload.api_key and payload.api_key.strip():
        api_key = payload.api_key.strip()

    weights = (
        payload.vector_weight
        + payload.keyword_weight
        + payload.importance_weight
        + payload.recency_weight
    )
    if weights <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="RAG 权重之和必须大于 0。",
        )

    updated = replace(
        current,
        llm_base_url=_clean_optional(payload.llm_base_url),
        llm_api_key=api_key,
        llm_model=_clean_optional(payload.llm_model),
        embedding_model=_clean_optional(payload.embedding_model),
        temperature=payload.temperature,
        top_p=payload.top_p,
        max_output_tokens=payload.max_output_tokens,
        presence_penalty=payload.presence_penalty,
        frequency_penalty=payload.frequency_penalty,
        request_timeout=payload.request_timeout,
        max_agent_steps=payload.max_agent_steps,
        recent_message_limit=payload.recent_message_limit,
        rag_limit=payload.rag_limit,
        vector_weight=payload.vector_weight,
        keyword_weight=payload.keyword_weight,
        importance_weight=payload.importance_weight,
        recency_weight=payload.recency_weight,
    )
    model = build_model_client(updated)
    save_local_settings(updated)
    request.app.state.settings = updated
    request.app.state.model = model
    request.app.state.runtime = AgentRuntime(updated, model)
    return _settings_read(updated)


@router.post("/settings/test", response_model=SettingsTestResult, tags=["system"])
async def test_settings(request: Request) -> SettingsTestResult:
    """发送一条最小请求，确认当前模型配置能够正常响应。"""
    model = request.app.state.model
    if model.mode == "demo":
        return SettingsTestResult(
            ok=True,
            provider_mode=model.mode,
            model=model.model_name,
            message="当前为演示模式；填写完整的地址、密钥和模型名后可测试真实连接。",
        )
    try:
        reply = await model.complete(
            [
                {"role": "system", "content": "只回复 OK。"},
                {"role": "user", "content": "连接测试"},
            ],
            None,
        )
    except ModelProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"模型连接失败：{exc}",
        ) from exc
    return SettingsTestResult(
        ok=True,
        provider_mode=model.mode,
        model=model.model_name,
        message=f"连接成功，模型返回：{(reply.content or '空响应')[:100]}",
    )


@router.post(
    "/chats",
    response_model=ChatRead,
    status_code=status.HTTP_201_CREATED,
    tags=["chats"],
)
def create_chat(payload: ChatCreate, db: Session = Depends(get_db)) -> ChatRead:
    """创建一个新的角色扮演存档。"""
    now = datetime.now(UTC)
    record = ChatRecord(
        id=str(uuid4()),
        title=payload.title,
        system_prompt=payload.system_prompt,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return chat_read(record)


@router.get("/chats", response_model=list[ChatRead], tags=["chats"])
def list_chats(db: Session = Depends(get_db)) -> list[ChatRead]:
    records = db.scalars(
        select(ChatRecord).order_by(ChatRecord.updated_at.desc())
    ).all()
    return [chat_read(record) for record in records]


@router.get("/chats/{chat_id}", response_model=ChatRead, tags=["chats"])
def get_chat(chat_id: UUID, db: Session = Depends(get_db)) -> ChatRead:
    return chat_read(_chat_or_404(db, chat_id))


@router.get(
    "/chats/{chat_id}/character",
    response_model=CharacterProfileRead,
    tags=["character"],
)
def get_character(
    chat_id: UUID,
    db: Session = Depends(get_db),
) -> CharacterProfileRead:
    """读取角色档案；尚未创建时返回一个空档案。"""
    _chat_or_404(db, chat_id)
    record = db.scalar(
        select(CharacterProfileRecord).where(
            CharacterProfileRecord.chat_id == str(chat_id)
        )
    )
    if record:
        return character_read(record)
    return CharacterProfileRead(chat_id=chat_id)


@router.put(
    "/chats/{chat_id}/character",
    response_model=CharacterProfileRead,
    tags=["character"],
)
def update_character(
    chat_id: UUID,
    payload: CharacterProfileUpdate,
    db: Session = Depends(get_db),
) -> CharacterProfileRead:
    """创建或覆盖当前聊天存档的角色档案。"""
    chat = _chat_or_404(db, chat_id)
    record = db.scalar(
        select(CharacterProfileRecord).where(
            CharacterProfileRecord.chat_id == str(chat_id)
        )
    )
    now = datetime.now(UTC)
    if not record:
        record = CharacterProfileRecord(
            id=str(uuid4()),
            chat_id=str(chat_id),
            updated_at=now,
        )
        db.add(record)
    record.name = payload.name.strip()
    record.identity = payload.identity.strip()
    record.personality = payload.personality.strip()
    record.speaking_style = payload.speaking_style.strip()
    record.scenario = payload.scenario.strip()
    record.updated_at = now
    chat.updated_at = now
    db.commit()
    db.refresh(record)
    return character_read(record)


@router.get(
    "/chats/{chat_id}/world-book",
    response_model=list[WorldBookEntryRead],
    tags=["world-book"],
)
def list_world_book(
    chat_id: UUID,
    db: Session = Depends(get_db),
) -> list[WorldBookEntryRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(WorldBookEntryRecord)
        .where(WorldBookEntryRecord.chat_id == str(chat_id))
        .order_by(
            WorldBookEntryRecord.priority.desc(),
            WorldBookEntryRecord.updated_at.desc(),
        )
    ).all()
    return [world_book_read(record) for record in records]


@router.post(
    "/chats/{chat_id}/world-book",
    response_model=WorldBookEntryRead,
    status_code=status.HTTP_201_CREATED,
    tags=["world-book"],
)
def create_world_book_entry(
    chat_id: UUID,
    payload: WorldBookEntryCreate,
    db: Session = Depends(get_db),
) -> WorldBookEntryRead:
    chat = _chat_or_404(db, chat_id)
    now = datetime.now(UTC)
    record = WorldBookEntryRecord(
        id=str(uuid4()),
        chat_id=str(chat_id),
        title=payload.title.strip(),
        keywords_json=json_dumps(_clean_keywords(payload.keywords)),
        content=payload.content.strip(),
        priority=payload.priority,
        enabled=payload.enabled,
        created_at=now,
        updated_at=now,
    )
    chat.updated_at = now
    db.add(record)
    db.commit()
    db.refresh(record)
    return world_book_read(record)


@router.put(
    "/chats/{chat_id}/world-book/{entry_id}",
    response_model=WorldBookEntryRead,
    tags=["world-book"],
)
def update_world_book_entry(
    chat_id: UUID,
    entry_id: UUID,
    payload: WorldBookEntryUpdate,
    db: Session = Depends(get_db),
) -> WorldBookEntryRead:
    chat = _chat_or_404(db, chat_id)
    record = _world_entry_or_404(db, chat_id, entry_id)
    now = datetime.now(UTC)
    record.title = payload.title.strip()
    record.keywords_json = json_dumps(_clean_keywords(payload.keywords))
    record.content = payload.content.strip()
    record.priority = payload.priority
    record.enabled = payload.enabled
    record.updated_at = now
    chat.updated_at = now
    db.commit()
    db.refresh(record)
    return world_book_read(record)


@router.delete(
    "/chats/{chat_id}/world-book/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["world-book"],
)
def delete_world_book_entry(
    chat_id: UUID,
    entry_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    _chat_or_404(db, chat_id)
    record = _world_entry_or_404(db, chat_id, entry_id)
    db.delete(record)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/chats/{chat_id}/messages",
    response_model=list[MessageRead],
    tags=["messages"],
)
def list_messages(chat_id: UUID, db: Session = Depends(get_db)) -> list[MessageRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(MessageRecord)
        .where(MessageRecord.chat_id == str(chat_id))
        .order_by(MessageRecord.created_at)
    ).all()
    return [message_read(record) for record in records]


@router.post(
    "/chats/{chat_id}/messages",
    response_model=AgentTurnRead,
    tags=["messages"],
)
async def send_message(
    chat_id: UUID,
    payload: MessageSend,
    request: Request,
    db: Session = Depends(get_db),
) -> AgentTurnRead:
    """保存用户消息，并运行一次完整 Agent 对话。"""
    chat = _chat_or_404(db, chat_id)
    user_message = MessageRecord(
        id=str(uuid4()),
        chat_id=chat.id,
        role=MessageRole.USER.value,
        content=payload.content,
        created_at=datetime.now(UTC),
    )
    chat.updated_at = user_message.created_at
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    runtime: AgentRuntime = request.app.state.runtime
    result = await runtime.run_turn(db, chat, user_message)
    return AgentTurnRead(
        turn_id=UUID(result.turn_id),
        provider_mode=runtime.model.mode,
        user_message=message_read(user_message),
        assistant_message=message_read(result.assistant_message),
        retrieved_memories=[
            MemorySearchResult(
                memory=memory_read(item.record),
                score=item.score,
                retrieval_reason=item.reason,
            )
            for item in result.retrieved_memories
        ],
        state_proposals=[state_change_read(item) for item in result.state_proposals],
        audit_issues=[audit_read(item) for item in result.audit_issues],
        trace=[trace_read(item) for item in result.traces],
    )


@router.get(
    "/chats/{chat_id}/memories",
    response_model=list[MemoryRead],
    tags=["memory"],
)
def list_memories(chat_id: UUID, db: Session = Depends(get_db)) -> list[MemoryRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(MemoryRecord)
        .where(MemoryRecord.chat_id == str(chat_id))
        .order_by(MemoryRecord.created_at.desc())
    ).all()
    return [memory_read(record) for record in records]


@router.post(
    "/chats/{chat_id}/memories",
    response_model=MemoryRead,
    status_code=status.HTTP_201_CREATED,
    tags=["memory"],
)
async def create_memory(
    chat_id: UUID,
    payload: MemoryCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryRead:
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    record = await runtime.memory_service.create(
        db,
        runtime.model,
        str(chat_id),
        payload.kind,
        payload.content,
        payload.importance,
        str(payload.source_message_id) if payload.source_message_id else None,
    )
    return memory_read(record)


@router.post(
    "/chats/{chat_id}/memories/search",
    response_model=list[MemorySearchResult],
    tags=["memory"],
)
async def search_memories(
    chat_id: UUID,
    payload: MemorySearchRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> list[MemorySearchResult]:
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    results = await runtime.memory_service.search(
        db,
        runtime.model,
        str(chat_id),
        payload.query,
        payload.limit,
    )
    return [
        MemorySearchResult(
            memory=memory_read(item.record),
            score=item.score,
            retrieval_reason=item.reason,
        )
        for item in results
    ]


@router.post(
    "/chats/{chat_id}/memories/summarize",
    response_model=MemoryRead,
    tags=["memory"],
)
async def summarize_memories(
    chat_id: UUID,
    payload: MemorySummaryRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MemoryRead:
    """把最近一段对话压缩成可检索的摘要记忆。"""
    _chat_or_404(db, chat_id)
    records_desc = db.scalars(
        select(MessageRecord)
        .where(MessageRecord.chat_id == str(chat_id))
        .order_by(MessageRecord.created_at.desc())
        .limit(payload.max_messages)
    ).all()
    records = list(reversed(records_desc))
    if not records:
        raise HTTPException(status_code=400, detail="当前存档还没有可总结的消息")

    transcript = "\n".join(
        f"{record.role}: {record.content}" for record in records
    )
    runtime: AgentRuntime = request.app.state.runtime
    reply = await runtime.model.complete(
        [
            {
                "role": "system",
                "content": (
                    "生成剧情摘要。保留关键事件、人物关系、承诺、伏笔、"
                    "时间变化和重要状态，不补充原文没有的信息。"
                ),
            },
            {"role": "user", "content": transcript},
        ]
    )
    summary = reply.content or "未能生成摘要。"
    record = await runtime.memory_service.create(
        db,
        runtime.model,
        str(chat_id),
        MemoryKind.SUMMARY,
        summary,
        importance=0.8,
        source_message_id=records[-1].id,
    )
    return memory_read(record)


@router.get(
    "/chats/{chat_id}/state",
    response_model=list[StateEntryRead],
    tags=["state"],
)
def list_state(
    chat_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> list[StateEntryRead]:
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    return [
        state_entry_read(item)
        for item in runtime.state_service.list_entries(db, str(chat_id))
    ]


@router.post(
    "/chats/{chat_id}/state/proposals",
    response_model=StateChangeRead,
    status_code=status.HTTP_201_CREATED,
    tags=["state"],
)
def create_state_proposal(
    chat_id: UUID,
    payload: StateProposalCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> StateChangeRead:
    _chat_or_404(db, chat_id)
    runtime: AgentRuntime = request.app.state.runtime
    record = runtime.state_service.propose(
        db,
        str(chat_id),
        payload.entity,
        payload.key,
        payload.new_value,
        payload.reason,
        str(payload.source_message_id) if payload.source_message_id else None,
    )
    return state_change_read(record)


@router.get(
    "/chats/{chat_id}/state/proposals",
    response_model=list[StateChangeRead],
    tags=["state"],
)
def list_state_proposals(
    chat_id: UUID,
    proposal_status: ProposalStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[StateChangeRead]:
    _chat_or_404(db, chat_id)
    statement = select(StateChangeRecord).where(
        StateChangeRecord.chat_id == str(chat_id)
    )
    if proposal_status:
        statement = statement.where(StateChangeRecord.status == proposal_status.value)
    records = db.scalars(statement.order_by(StateChangeRecord.created_at.desc())).all()
    return [state_change_read(record) for record in records]


@router.post(
    "/chats/{chat_id}/state/proposals/{proposal_id}/resolve",
    response_model=StateChangeRead,
    tags=["state"],
)
def resolve_state_proposal(
    chat_id: UUID,
    proposal_id: UUID,
    payload: StateResolution,
    request: Request,
    db: Session = Depends(get_db),
) -> StateChangeRead:
    _chat_or_404(db, chat_id)
    proposal = db.scalar(
        select(StateChangeRecord).where(
            StateChangeRecord.id == str(proposal_id),
            StateChangeRecord.chat_id == str(chat_id),
        )
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="状态变更建议不存在")
    runtime: AgentRuntime = request.app.state.runtime
    try:
        resolved = runtime.state_service.resolve(
            db,
            proposal,
            approve=payload.action == "approve",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return state_change_read(resolved)


@router.get(
    "/chats/{chat_id}/audits",
    response_model=list[AuditIssueRead],
    tags=["audit"],
)
def list_audits(chat_id: UUID, db: Session = Depends(get_db)) -> list[AuditIssueRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(AuditIssueRecord)
        .where(AuditIssueRecord.chat_id == str(chat_id))
        .order_by(AuditIssueRecord.created_at.desc())
    ).all()
    return [audit_read(record) for record in records]


@router.post(
    "/chats/{chat_id}/audits/{audit_id}/resolve",
    response_model=AuditIssueRead,
    tags=["audit"],
)
def resolve_audit(
    chat_id: UUID,
    audit_id: UUID,
    payload: AuditResolution,
    db: Session = Depends(get_db),
) -> AuditIssueRead:
    _chat_or_404(db, chat_id)
    record = db.scalar(
        select(AuditIssueRecord).where(
            AuditIssueRecord.id == str(audit_id),
            AuditIssueRecord.chat_id == str(chat_id),
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="审计问题不存在")
    record.status = (
        AuditStatus.RESOLVED.value
        if payload.action == "resolve"
        else AuditStatus.DISMISSED.value
    )
    db.commit()
    db.refresh(record)
    return audit_read(record)


@router.get(
    "/chats/{chat_id}/traces",
    response_model=list[AgentTraceRead],
    tags=["trace"],
)
def list_traces(
    chat_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[AgentTraceRead]:
    _chat_or_404(db, chat_id)
    records = db.scalars(
        select(AgentTraceRecord)
        .where(AgentTraceRecord.chat_id == str(chat_id))
        .order_by(AgentTraceRecord.created_at.desc())
        .limit(limit)
    ).all()
    return [trace_read(record) for record in records]


def _chat_or_404(db: Session, chat_id: UUID) -> ChatRecord:
    record = db.get(ChatRecord, str(chat_id))
    if not record:
        raise HTTPException(status_code=404, detail="聊天存档不存在")
    return record


def _world_entry_or_404(
    db: Session,
    chat_id: UUID,
    entry_id: UUID,
) -> WorldBookEntryRecord:
    record = db.scalar(
        select(WorldBookEntryRecord).where(
            WorldBookEntryRecord.id == str(entry_id),
            WorldBookEntryRecord.chat_id == str(chat_id),
        )
    )
    if not record:
        raise HTTPException(status_code=404, detail="世界书词条不存在")
    return record


def _clean_keywords(keywords: list[str]) -> list[str]:
    """清理空关键词并去重，避免同一触发词重复进入上下文。"""
    result: list[str] = []
    seen: set[str] = set()
    for raw_keyword in keywords:
        keyword = raw_keyword.strip()[:100]
        normalized = keyword.casefold()
        if keyword and normalized not in seen:
            seen.add(normalized)
            result.append(keyword)
    return result


def _settings_read(settings: Settings) -> SettingsRead:
    key = settings.llm_api_key or ""
    hint = f"••••{key[-4:]}" if key else None
    return SettingsRead(
        provider_mode=settings.provider_mode,
        llm_base_url=settings.llm_base_url,
        api_key_configured=bool(key),
        api_key_hint=hint,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        temperature=settings.temperature,
        top_p=settings.top_p,
        max_output_tokens=settings.max_output_tokens,
        presence_penalty=settings.presence_penalty,
        frequency_penalty=settings.frequency_penalty,
        request_timeout=settings.request_timeout,
        max_agent_steps=settings.max_agent_steps,
        recent_message_limit=settings.recent_message_limit,
        rag_limit=settings.rag_limit,
        vector_weight=settings.vector_weight,
        keyword_weight=settings.keyword_weight,
        importance_weight=settings.importance_weight,
        recency_weight=settings.recency_weight,
    )


def _clean_optional(value: str | None) -> str | None:
    text = value.strip() if value else ""
    return text or None
