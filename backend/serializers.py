"""把数据库对象转换为稳定的公开 API 模型。"""

from uuid import UUID

from backend.models import (
    AgentTraceRecord,
    AuditIssueRecord,
    ChatRecord,
    CharacterTemplateRecord,
    CharacterProfileRecord,
    MemoryRecord,
    NpcRecord,
    PersonaTemplateRecord,
    SceneNodeRecord,
    MessageRecord,
    SettingChangeRecord,
    StateChangeRecord,
    StateEntryRecord,
    StoryCharacterRecord,
    StoryPersonaRecord,
    StoryWorldBookRecord,
    TimelineAnchorRecord,
    WorldBookTemplateRecord,
    WorldBookEntryRecord,
)
from backend.schemas import (
    AgentTraceRead,
    AuditIssueRead,
    AuditStatus,
    ChatRead,
    CharacterTemplateRead,
    CharacterProfileRead,
    MemoryKind,
    MemoryRead,
    NpcRead,
    NpcRelation,
    PersonaRead,
    SceneNodeRead,
    MessageRead,
    MessageRole,
    ProposalStatus,
    SettingChangeRead,
    StateChangeRead,
    StateEntryRead,
    StoryCharacterRead,
    StoryPersonaRead,
    StoryWorldBookRead,
    TimelineAnchorRead,
    WorldBookTemplateRead,
    WorldBookEntryRead,
)
from backend.utils import json_loads


def chat_read(record: ChatRecord) -> ChatRead:
    return ChatRead(
        id=UUID(record.id),
        title=record.title,
        system_prompt=record.system_prompt,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def persona_template_read(record: PersonaTemplateRecord) -> PersonaRead:
    return PersonaRead(
        id=UUID(record.id),
        name=record.name,
        avatar=record.avatar,
        identity=record.identity,
        personality=record.personality,
        appearance=record.appearance,
        speaking_style=record.speaking_style,
        world_book_ids=json_loads(record.world_book_ids_json) or [],
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def story_persona_read(record: StoryPersonaRecord) -> StoryPersonaRead:
    return StoryPersonaRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        source_template_id=(UUID(record.source_template_id) if record.source_template_id else None),
        name=record.name,
        avatar=record.avatar,
        identity=record.identity,
        personality=record.personality,
        appearance=record.appearance,
        speaking_style=record.speaking_style,
        world_book_ids=json_loads(record.world_book_ids_json) or [],
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def character_read(record: CharacterProfileRecord) -> CharacterProfileRead:
    return CharacterProfileRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        name=record.name,
        identity=record.identity,
        personality=record.personality,
        speaking_style=record.speaking_style,
        scenario=record.scenario,
        avatar=record.avatar,
        updated_at=record.updated_at,
    )


def character_template_read(record: CharacterTemplateRecord) -> CharacterTemplateRead:
    compatibility = json_loads(record.compatibility_data_json) or {}
    extra = compatibility.get("saraswati_fields") or {}
    return CharacterTemplateRead(
        id=UUID(record.id),
        name=record.name,
        identity=record.identity,
        personality=record.personality,
        speaking_style=record.speaking_style,
        scenario=record.scenario,
        avatar=record.avatar,
        appearance=record.appearance,
        first_message=record.first_message,
        alternate_greetings=json_loads(record.alternate_greetings_json) or [],
        example_dialogue=record.example_dialogue,
        tags=json_loads(record.tags_json) or [],
        creator_notes=record.creator_notes,
        system_prompt=record.system_prompt,
        post_history_instructions=extra.get("post_history_instructions", ""),
        creator=extra.get("creator", ""),
        character_version=extra.get("character_version", ""),
        favorite=record.favorite,
        world_book_ids=json_loads(record.world_book_ids_json) or [],
        compatibility_data=compatibility,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def story_character_read(record: StoryCharacterRecord) -> StoryCharacterRead:
    compatibility = json_loads(record.compatibility_data_json) or {}
    extra = compatibility.get("saraswati_fields") or {}
    return StoryCharacterRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        source_template_id=(UUID(record.source_template_id) if record.source_template_id else None),
        name=record.name,
        identity=record.identity,
        personality=record.personality,
        speaking_style=record.speaking_style,
        scenario=record.scenario,
        avatar=record.avatar,
        appearance=record.appearance,
        first_message=record.first_message,
        alternate_greetings=json_loads(record.alternate_greetings_json) or [],
        example_dialogue=record.example_dialogue,
        tags=json_loads(record.tags_json) or [],
        creator_notes=record.creator_notes,
        system_prompt=record.system_prompt,
        post_history_instructions=extra.get("post_history_instructions", ""),
        creator=extra.get("creator", ""),
        character_version=extra.get("character_version", ""),
        favorite=record.favorite,
        world_book_ids=json_loads(record.world_book_ids_json) or [],
        compatibility_data=compatibility,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def world_book_read(record: WorldBookEntryRecord) -> WorldBookEntryRead:
    return WorldBookEntryRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        title=record.title,
        keywords=json_loads(record.keywords_json) or [],
        secondary_keywords=json_loads(record.secondary_keywords_json) or [],
        content=record.content,
        priority=record.priority,
        enabled=record.enabled,
        constant=record.constant,
        case_sensitive=record.case_sensitive,
        scan_depth=record.scan_depth,
        insertion_position=record.insertion_position,
        group_name=record.group_name,
        recursive=record.recursive,
        token_budget=record.token_budget,
        scope=record.scope,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def world_book_template_read(record: WorldBookTemplateRecord) -> WorldBookTemplateRead:
    compatibility = json_loads(record.compatibility_data_json) or {}
    extra = compatibility.get("saraswati_fields") or {}
    return WorldBookTemplateRead(
        id=UUID(record.id),
        title=record.title,
        keywords=json_loads(record.keywords_json) or [],
        secondary_keywords=json_loads(record.secondary_keywords_json) or [],
        content=record.content,
        priority=record.priority,
        enabled=record.enabled,
        constant=record.constant,
        case_sensitive=record.case_sensitive,
        scan_depth=record.scan_depth,
        insertion_position=record.insertion_position,
        group_name=record.group_name,
        recursive=record.recursive,
        selective_logic=extra.get("selective_logic", "and_any"),
        probability=extra.get("probability", 100),
        match_whole_words=extra.get("match_whole_words", False),
        prevent_recursion=extra.get("prevent_recursion", False),
        depth=extra.get("depth", 4),
        sticky=extra.get("sticky", 0),
        cooldown=extra.get("cooldown", 0),
        delay=extra.get("delay", 0),
        token_budget=record.token_budget,
        scope=record.scope,
        compatibility_data=compatibility,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def story_world_book_read(record: StoryWorldBookRecord) -> StoryWorldBookRead:
    compatibility = json_loads(record.compatibility_data_json) or {}
    extra = compatibility.get("saraswati_fields") or {}
    return StoryWorldBookRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        source_template_id=(UUID(record.source_template_id) if record.source_template_id else None),
        title=record.title,
        keywords=json_loads(record.keywords_json) or [],
        secondary_keywords=json_loads(record.secondary_keywords_json) or [],
        content=record.content,
        priority=record.priority,
        enabled=record.enabled,
        constant=record.constant,
        case_sensitive=record.case_sensitive,
        scan_depth=record.scan_depth,
        insertion_position=record.insertion_position,
        group_name=record.group_name,
        recursive=record.recursive,
        selective_logic=extra.get("selective_logic", "and_any"),
        probability=extra.get("probability", 100),
        match_whole_words=extra.get("match_whole_words", False),
        prevent_recursion=extra.get("prevent_recursion", False),
        depth=extra.get("depth", 4),
        sticky=extra.get("sticky", 0),
        cooldown=extra.get("cooldown", 0),
        delay=extra.get("delay", 0),
        token_budget=record.token_budget,
        scope=record.scope,
        compatibility_data=compatibility,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def message_read(record: MessageRecord) -> MessageRead:
    return MessageRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        role=MessageRole(record.role),
        content=record.content,
        created_at=record.created_at,
    )


def memory_read(record: MemoryRecord) -> MemoryRead:
    return MemoryRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        kind=MemoryKind(record.kind),
        content=record.content,
        importance=record.importance,
        source_message_id=(
            UUID(record.source_message_id) if record.source_message_id else None
        ),
        access_count=record.access_count,
        last_accessed_at=record.last_accessed_at,
        created_at=record.created_at,
    )


def scene_read(record: SceneNodeRecord, path: list[str]) -> SceneNodeRead:
    return SceneNodeRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        parent_id=UUID(record.parent_id) if record.parent_id else None,
        name=record.name,
        description=record.description,
        aliases=json_loads(record.aliases_json) or [],
        is_current=record.is_current,
        path=path,
        source_message_id=UUID(record.source_message_id) if record.source_message_id else None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def npc_read(record: NpcRecord) -> NpcRead:
    relations = json_loads(record.relations_json) or []
    return NpcRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        name=record.name,
        description=record.description,
        relation_to_user=record.relation_to_user,
        relations=[NpcRelation.model_validate(item) for item in relations],
        importance=record.importance,
        presence=record.presence,
        location_scene_id=(UUID(record.location_scene_id) if record.location_scene_id else None),
        outfit=record.outfit,
        condition=record.condition,
        source_message_id=UUID(record.source_message_id) if record.source_message_id else None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def timeline_anchor_read(record: TimelineAnchorRecord) -> TimelineAnchorRead:
    return TimelineAnchorRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        story_time=record.story_time,
        description=record.description,
        is_conflict=record.is_conflict,
        conflict_reason=record.conflict_reason,
        source_message_id=(UUID(record.source_message_id) if record.source_message_id else None),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def state_entry_read(record: StateEntryRecord) -> StateEntryRead:
    return StateEntryRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        entity=record.entity,
        key=record.key,
        value=json_loads(record.value_json),
        source_message_id=(
            UUID(record.source_message_id) if record.source_message_id else None
        ),
        version=record.version,
        updated_at=record.updated_at,
    )


def state_change_read(record: StateChangeRecord) -> StateChangeRead:
    return StateChangeRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        entity=record.entity,
        key=record.key,
        old_value=json_loads(record.old_value_json),
        new_value=json_loads(record.new_value_json),
        reason=record.reason,
        source_message_id=(
            UUID(record.source_message_id) if record.source_message_id else None
        ),
        status=ProposalStatus(record.status),
        created_at=record.created_at,
        resolved_at=record.resolved_at,
    )


def setting_change_read(record: SettingChangeRecord) -> SettingChangeRead:
    return SettingChangeRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        target_type=record.target_type,  # type: ignore[arg-type]
        target_id=UUID(record.target_id),
        field=record.field,
        base_value=record.base_value,
        new_value=record.new_value,
        reason=record.reason,
        evidence=record.evidence,
        importance=record.importance,  # type: ignore[arg-type]
        confidence=record.confidence,
        source_message_id=(UUID(record.source_message_id) if record.source_message_id else None),
        status=ProposalStatus(record.status),
        created_at=record.created_at,
        resolved_at=record.resolved_at,
    )


def audit_read(record: AuditIssueRecord) -> AuditIssueRead:
    return AuditIssueRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        message_id=UUID(record.message_id),
        category=record.category,
        severity=record.severity,
        description=record.description,
        expected_value=json_loads(record.expected_value_json),
        actual_value=json_loads(record.actual_value_json),
        evidence=record.evidence,
        status=AuditStatus(record.status),
        created_at=record.created_at,
    )


def trace_read(record: AgentTraceRecord) -> AgentTraceRead:
    return AgentTraceRead(
        id=UUID(record.id),
        chat_id=UUID(record.chat_id),
        turn_id=UUID(record.turn_id),
        step=record.step,
        event_type=record.event_type,
        payload=json_loads(record.payload_json),
        created_at=record.created_at,
    )
