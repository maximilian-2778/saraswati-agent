"""对外 API 使用的请求与响应数据契约。"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MemoryKind(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    SUMMARY = "summary"
    IMPLICIT = "implicit"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AuditStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ChatCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    system_prompt: str = Field(default="", max_length=20_000)
    character_template_ids: list[UUID] = Field(default_factory=list, max_length=50)
    world_book_template_ids: list[UUID] = Field(default_factory=list, max_length=100)


class ChatRead(BaseModel):
    id: UUID
    title: str
    system_prompt: str
    created_at: datetime
    updated_at: datetime


class CharacterProfileUpdate(BaseModel):
    name: str = Field(default="", max_length=100)
    identity: str = Field(default="", max_length=10_000)
    personality: str = Field(default="", max_length=10_000)
    speaking_style: str = Field(default="", max_length=10_000)
    scenario: str = Field(default="", max_length=10_000)


class CharacterTemplateCreate(CharacterProfileUpdate):
    name: str = Field(min_length=1, max_length=100)


class CharacterTemplateRead(CharacterTemplateCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime


class StoryCharacterRead(CharacterTemplateCreate):
    id: UUID
    chat_id: UUID
    source_template_id: UUID | None
    created_at: datetime
    updated_at: datetime


class CharacterProfileRead(CharacterProfileUpdate):
    id: UUID | None = None
    chat_id: UUID
    updated_at: datetime | None = None


class WorldBookEntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    content: str = Field(min_length=1, max_length=20_000)
    priority: int = Field(default=50, ge=0, le=100)
    enabled: bool = True


class WorldBookEntryUpdate(WorldBookEntryCreate):
    pass


class WorldBookTemplateRead(WorldBookEntryCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime


class StoryWorldBookRead(WorldBookEntryCreate):
    id: UUID
    chat_id: UUID
    source_template_id: UUID | None
    created_at: datetime
    updated_at: datetime


class WorldBookEntryRead(WorldBookEntryCreate):
    id: UUID
    chat_id: UUID
    created_at: datetime
    updated_at: datetime


class MessageSend(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


class MessageUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)


class MessageRead(BaseModel):
    id: UUID
    chat_id: UUID
    role: MessageRole
    content: str
    created_at: datetime


class MemoryCreate(BaseModel):
    kind: MemoryKind = MemoryKind.SEMANTIC
    content: str = Field(min_length=1, max_length=20_000)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    source_message_id: UUID | None = None


class MemoryRead(BaseModel):
    id: UUID
    chat_id: UUID
    kind: MemoryKind
    content: str
    importance: float
    source_message_id: UUID | None
    access_count: int
    last_accessed_at: datetime | None
    created_at: datetime


class MemorySearchResult(BaseModel):
    memory: MemoryRead
    score: float
    retrieval_reason: str


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=5_000)
    limit: int = Field(default=5, ge=1, le=20)


class MemorySummaryRequest(BaseModel):
    max_messages: int = Field(default=30, ge=4, le=100)
    detail_mode: Literal["brief", "detailed"] = "brief"


class MemoryUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)


class MemoryMergeRequest(BaseModel):
    memory_ids: list[UUID] = Field(min_length=2, max_length=50)
    detail_mode: Literal["brief", "detailed"] = "brief"


class NarrativeNodeRead(BaseModel):
    id: UUID
    node_type: Literal["leaf", "summary"]
    level: int
    content: str
    child_ids: list[UUID] = Field(default_factory=list)
    source_message_id: UUID | None = None
    time_start: str | None = None
    time_end: str | None = None
    valid: bool = True
    active: bool = False
    created_at: datetime


class MemoryCoverageRead(BaseModel):
    total_ai_floors: int
    summarized_floors: int
    valid_floors: int
    coverage_ratio: float
    missing_message_ids: list[UUID] = Field(default_factory=list)
    invalid_message_ids: list[UUID] = Field(default_factory=list)
    selected_node_ids: list[UUID] = Field(default_factory=list)


class SceneNodeUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    parent_id: UUID | None = None
    description: str = Field(default="", max_length=10_000)
    is_current: bool = False


class SceneNodeRead(SceneNodeUpsert):
    id: UUID
    chat_id: UUID
    path: list[str] = Field(default_factory=list)
    source_message_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class NpcRelation(BaseModel):
    target: str = Field(min_length=1, max_length=120)
    relation: str = Field(min_length=1, max_length=1_000)


class NpcUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=10_000)
    relation_to_user: str = Field(default="", max_length=5_000)
    relations: list[NpcRelation] = Field(default_factory=list, max_length=100)
    importance: Literal["core", "supporting", "minor"] = "supporting"
    presence: Literal["present", "nearby", "away", "unknown"] = "away"
    location_scene_id: UUID | None = None
    outfit: str = Field(default="", max_length=5_000)
    condition: str = Field(default="", max_length=5_000)


class NpcRead(NpcUpsert):
    id: UUID
    chat_id: UUID
    source_message_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class TimelineAnchorCreate(BaseModel):
    story_time: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5_000)
    source_message_id: UUID | None = None


class TimelineAnchorRead(TimelineAnchorCreate):
    id: UUID
    chat_id: UUID
    created_at: datetime
    updated_at: datetime


class StateEntryRead(BaseModel):
    id: UUID
    chat_id: UUID
    entity: str
    key: str
    value: Any
    source_message_id: UUID | None
    version: int
    updated_at: datetime


class StateProposalCreate(BaseModel):
    entity: str = Field(min_length=1, max_length=100)
    key: str = Field(min_length=1, max_length=100)
    new_value: Any
    reason: str = Field(min_length=1, max_length=2_000)
    source_message_id: UUID | None = None


class StateChangeRead(BaseModel):
    id: UUID
    chat_id: UUID
    entity: str
    key: str
    old_value: Any | None
    new_value: Any
    reason: str
    source_message_id: UUID | None
    status: ProposalStatus
    created_at: datetime
    resolved_at: datetime | None


class StateResolution(BaseModel):
    action: Literal["approve", "reject"]


class AuditIssueRead(BaseModel):
    id: UUID
    chat_id: UUID
    message_id: UUID
    category: str
    severity: str
    description: str
    expected_value: Any | None
    actual_value: Any | None
    evidence: str
    status: AuditStatus
    created_at: datetime


class AuditResolution(BaseModel):
    action: Literal["resolve", "dismiss"]


class AgentTraceRead(BaseModel):
    id: UUID
    chat_id: UUID
    turn_id: UUID
    step: int
    event_type: str
    payload: Any
    created_at: datetime


class AgentTurnRead(BaseModel):
    turn_id: UUID = Field(default_factory=uuid4)
    provider_mode: str
    user_message: MessageRead
    assistant_message: MessageRead
    retrieved_memories: list[MemorySearchResult] = Field(default_factory=list)
    state_proposals: list[StateChangeRead] = Field(default_factory=list)
    audit_issues: list[AuditIssueRead] = Field(default_factory=list)
    trace: list[AgentTraceRead] = Field(default_factory=list)


class RuntimeInfo(BaseModel):
    provider_mode: str
    model: str | None
    embedding_model: str | None
    max_agent_steps: int


class SettingsRead(BaseModel):
    """返回给前端的安全配置视图，不包含 API Key 明文。"""

    provider_mode: str
    llm_base_url: str | None
    api_key_configured: bool
    api_key_hint: str | None
    llm_model: str | None
    embedding_model: str | None
    temperature: float
    top_p: float
    max_output_tokens: int
    presence_penalty: float
    frequency_penalty: float
    request_timeout: float
    max_agent_steps: int
    recent_message_limit: int
    rag_limit: int
    vector_weight: float
    keyword_weight: float
    importance_weight: float
    recency_weight: float
    auto_summary_enabled: bool
    summary_detail_mode: Literal["brief", "detailed"]
    chapter_summary_size: int
    arc_summary_size: int
    rerank_base_url: str | None
    rerank_api_key_configured: bool
    rerank_api_key_hint: str | None
    rerank_model: str | None
    rerank_candidates: int


class SettingsUpdate(BaseModel):
    """设置中心允许修改的模型与 Agent 参数。"""

    llm_base_url: str | None = Field(default=None, max_length=2_000)
    api_key: str | None = Field(default=None, max_length=10_000)
    clear_api_key: bool = False
    llm_model: str | None = Field(default=None, max_length=200)
    embedding_model: str | None = Field(default=None, max_length=200)
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, gt=0.0, le=1.0)
    max_output_tokens: int = Field(default=2048, ge=64, le=32_768)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    request_timeout: float = Field(default=90.0, ge=5.0, le=600.0)
    max_agent_steps: int = Field(default=4, ge=1, le=12)
    recent_message_limit: int = Field(default=16, ge=2, le=100)
    rag_limit: int = Field(default=5, ge=1, le=30)
    vector_weight: float = Field(default=0.55, ge=0.0, le=1.0)
    keyword_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    importance_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    recency_weight: float = Field(default=0.05, ge=0.0, le=1.0)
    auto_summary_enabled: bool = True
    summary_detail_mode: Literal["brief", "detailed"] = "brief"
    chapter_summary_size: int = Field(default=8, ge=2, le=50)
    arc_summary_size: int = Field(default=4, ge=2, le=20)
    rerank_base_url: str | None = Field(default=None, max_length=2_000)
    rerank_api_key: str | None = Field(default=None, max_length=10_000)
    clear_rerank_api_key: bool = False
    rerank_model: str | None = Field(default=None, max_length=200)
    rerank_candidates: int = Field(default=20, ge=2, le=100)


class SettingsTestResult(BaseModel):
    ok: bool
    provider_mode: str
    model: str | None
    message: str


class HealthRead(BaseModel):
    status: str = "ok"
    service: str = "saraswati-agent-api"
    version: str = "0.4.0"
