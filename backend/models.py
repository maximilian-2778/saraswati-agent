"""聊天、记忆、状态和运行轨迹对应的 SQLAlchemy 持久化模型。"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ChatRecord(Base):
    __tablename__ = "chats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatSkillModeRecord(Base):
    """故事级 Skill 策略；缺少记录时默认跟随全部全局启用项。"""

    __tablename__ = "chat_skill_modes"

    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="all")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChatSkillBindingRecord(Base):
    """故事在 selected 模式下允许使用的 Skill。"""

    __tablename__ = "chat_skill_bindings"
    __table_args__ = (UniqueConstraint("chat_id", "skill_id", name="uq_chat_skill_binding"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PromptPresetRecord(Base):
    """可复用的写作提示词；采样字段仅用于酒馆 JSON 兼容。"""

    __tablename__ = "prompt_presets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    top_p: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    presence_penalty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    frequency_penalty: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    context_window_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=32768)
    prompts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    extra_settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PersonaTemplateRecord(Base):
    """可跨故事复用的玩家身份。"""

    __tablename__ = "persona_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar: Mapped[str] = mapped_column(Text, nullable=False, default="")
    identity: Mapped[str] = mapped_column(Text, nullable=False, default="")
    personality: Mapped[str] = mapped_column(Text, nullable=False, default="")
    appearance: Mapped[str] = mapped_column(Text, nullable=False, default="")
    speaking_style: Mapped[str] = mapped_column(Text, nullable=False, default="")
    world_book_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoryPersonaRecord(Base):
    """创建故事时复制出的 Persona 私有快照。"""

    __tablename__ = "story_personas"
    __table_args__ = (UniqueConstraint("chat_id", name="uq_story_persona_chat"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_template_id: Mapped[str | None] = mapped_column(
        ForeignKey("persona_templates.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar: Mapped[str] = mapped_column(Text, nullable=False, default="")
    identity: Mapped[str] = mapped_column(Text, nullable=False, default="")
    personality: Mapped[str] = mapped_column(Text, nullable=False, default="")
    appearance: Mapped[str] = mapped_column(Text, nullable=False, default="")
    speaking_style: Mapped[str] = mapped_column(Text, nullable=False, default="")
    world_book_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CharacterTemplateRecord(Base):
    """可跨故事复用的角色原始设定。"""

    __tablename__ = "character_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    identity: Mapped[str] = mapped_column(Text, nullable=False, default="")
    personality: Mapped[str] = mapped_column(Text, nullable=False, default="")
    speaking_style: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scenario: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar: Mapped[str] = mapped_column(Text, nullable=False, default="")
    appearance: Mapped[str] = mapped_column(Text, nullable=False, default="")
    first_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    alternate_greetings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    example_dialogue: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    creator_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    world_book_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorldBookTemplateRecord(Base):
    """可跨故事复用的世界书词条原始设定。"""

    __tablename__ = "world_book_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    secondary_keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    constant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scan_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    insertion_position: Mapped[str] = mapped_column(String(30), nullable=False, default="before_history")
    group_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    recursive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    scope: Mapped[str] = mapped_column(String(30), nullable=False, default="global")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoryCharacterRecord(Base):
    """创建故事时从角色模板复制出的私有快照。"""

    __tablename__ = "story_characters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_template_id: Mapped[str | None] = mapped_column(
        ForeignKey("character_templates.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    identity: Mapped[str] = mapped_column(Text, nullable=False, default="")
    personality: Mapped[str] = mapped_column(Text, nullable=False, default="")
    speaking_style: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scenario: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar: Mapped[str] = mapped_column(Text, nullable=False, default="")
    appearance: Mapped[str] = mapped_column(Text, nullable=False, default="")
    first_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    alternate_greetings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    example_dialogue: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    creator_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    world_book_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoryWorldBookRecord(Base):
    """创建故事时从世界书模板复制出的私有快照。"""

    __tablename__ = "story_world_books"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_template_id: Mapped[str | None] = mapped_column(
        ForeignKey("world_book_templates.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    secondary_keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    constant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scan_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    insertion_position: Mapped[str] = mapped_column(String(30), nullable=False, default="before_history")
    group_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    recursive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    scope: Mapped[str] = mapped_column(String(30), nullable=False, default="story")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CharacterProfileRecord(Base):
    __tablename__ = "character_profiles"
    __table_args__ = (UniqueConstraint("chat_id", name="uq_character_chat"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    identity: Mapped[str] = mapped_column(Text, nullable=False, default="")
    personality: Mapped[str] = mapped_column(Text, nullable=False, default="")
    speaking_style: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scenario: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorldBookEntryRecord(Base):
    __tablename__ = "world_book_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    secondary_keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    constant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scan_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    insertion_position: Mapped[str] = mapped_column(String(30), nullable=False, default="before_history")
    group_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    recursive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    scope: Mapped[str] = mapped_column(String(30), nullable=False, default="story")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageRecord(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageVariantRecord(Base):
    """同一条助手消息的候选正文，切换候选不会改变消息在剧情中的位置。"""

    __tablename__ = "message_variants"
    __table_args__ = (
        UniqueConstraint("message_id", "position", name="uq_message_variant_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    state_changes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    graph_events_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageBookmarkRecord(Base):
    """用户收藏的剧情消息。"""

    __tablename__ = "message_bookmarks"

    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True
    )
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoryCheckpointRecord(Base):
    """指向某条消息的轻量检查点；恢复时创建一条安全的故事分支。"""

    __tablename__ = "story_checkpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryRecord(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NarrativeLeafRecord(Base):
    """一轮角色回复对应的可信摘要叶子；原文变化后可由指纹判定失效。"""

    __tablename__ = "narrative_leaves"
    __table_args__ = (
        UniqueConstraint("assistant_message_id", name="uq_narrative_leaf_message"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    assistant_message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    detail_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    time_start: Mapped[str | None] = mapped_column(String(200), nullable=True)
    time_end: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NarrativeSummaryNodeRecord(Base):
    """摘要森林中的压缩节点；child_refs_json 引用叶子或更低层节点。"""

    __tablename__ = "narrative_summary_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    level: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    child_refs_json: Mapped[str] = mapped_column(Text, nullable=False)
    memory_id: Mapped[str | None] = mapped_column(
        ForeignKey("memories.id", ondelete="SET NULL"), nullable=True
    )
    time_start: Mapped[str | None] = mapped_column(String(200), nullable=True)
    time_end: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SceneNodeRecord(Base):
    """故事内地点树节点。"""

    __tablename__ = "scene_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("scene_nodes.id", ondelete="CASCADE"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NpcRecord(Base):
    """NPC 当前档案与关系图节点。"""

    __tablename__ = "npcs"
    __table_args__ = (UniqueConstraint("chat_id", "name", name="uq_npc_chat_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    relation_to_user: Mapped[str] = mapped_column(Text, nullable=False, default="")
    relations_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    importance: Mapped[str] = mapped_column(String(20), nullable=False, default="supporting")
    presence: Mapped[str] = mapped_column(String(20), nullable=False, default="away")
    location_scene_id: Mapped[str | None] = mapped_column(
        ForeignKey("scene_nodes.id", ondelete="SET NULL"), nullable=True
    )
    outfit: Mapped[str] = mapped_column(Text, nullable=False, default="")
    condition: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RoleplayGraphEventRecord(Base):
    """场景/NPC 图的不可变事件；投影可由有效事件完整重建。"""

    __tablename__ = "roleplay_graph_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True, nullable=True
    )
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NarrativeDeltaRecord(Base):
    """一轮剧情造成的结构化变化，绑定用户与助手原文指纹。"""

    __tablename__ = "narrative_deltas"
    __table_args__ = (
        UniqueConstraint("assistant_message_id", name="uq_delta_assistant_message"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    assistant_message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorldEngineConfigRecord(Base):
    """故事级世界推演开关；默认手动，避免无意增加模型调用。"""

    __tablename__ = "world_engine_configs"

    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    auto_evolve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorldEvolutionRecord(Base):
    """一次世界推进的不可变快照；before_hash 将记录串成可校验状态链。"""

    __tablename__ = "world_evolutions"
    __table_args__ = (
        UniqueConstraint("chat_id", "sequence", name="uq_world_evolution_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    user_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True, nullable=True
    )
    assistant_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True, nullable=True
    )
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    after_state_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TimelineAnchorRecord(Base):
    """从剧情中提取或由用户补充的故事内时间锚点。"""

    __tablename__ = "timeline_anchors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False
    )
    story_time: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StateEntryRecord(Base):
    __tablename__ = "state_entries"
    __table_args__ = (
        UniqueConstraint("chat_id", "entity", "key", name="uq_state_identity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    entity: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StateChangeRecord(Base):
    __tablename__ = "state_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    entity: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    old_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class AuditIssueRecord(Base):
    __tablename__ = "audit_issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    expected_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentTraceRecord(Base):
    __tablename__ = "agent_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chat_id: Mapped[str] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    turn_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
