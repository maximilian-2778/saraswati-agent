"""Agent 可调用的工具定义与执行器。"""

from typing import Any

from sqlalchemy.orm import Session

from backend.llm import ModelClient
from backend.models import MemoryRecord, StateChangeRecord
from backend.schemas import MemoryKind
from backend.services.memory import MemoryService
from backend.services.roleplay_graph import RoleplayGraphService
from backend.services.state import StateService
from backend.utils import json_loads


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "upsert_scene",
            "description": "发现新地点、进入新地点或场景描述发生变化时维护层级场景树。同一地点的简称、别称或店铺类型应复用已有节点，不要重复创建。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "description": {"type": "string"},
                    "is_current": {"type": "boolean"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upsert_npc",
            "description": "NPC 登场、离场、换装、受伤、位置或人物关系变化时更新关系图。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "relation_to_user": {"type": "string"},
                    "relations": {"type": "array", "items": {"type": "object", "properties": {"target": {"type": "string"}, "relation": {"type": "string"}}, "required": ["target", "relation"]}},
                    "importance": {"type": "string", "enum": ["core", "supporting", "minor"]},
                    "presence": {"type": "string", "enum": ["present", "nearby", "away", "unknown"]},
                    "location_path": {"type": "array", "items": {"type": "string"}},
                    "outfit": {"type": "string"},
                    "condition": {"type": "string"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_state",
            "description": "查询人物、物品、金钱、地点或任务等已批准的精确状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string", "description": "实体名称，可选"},
                    "key": {"type": "string", "description": "状态字段，可选"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memories",
            "description": "检索与当前剧情相关的历史事件、事实、摘要或隐性记忆。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_state_change",
            "description": "剧情造成明确状态变化时写入状态事件。系统会自动采用，并保留来源和撤销记录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "key": {"type": "string"},
                    "new_value": {},
                    "reason": {"type": "string"},
                },
                "required": ["entity", "key", "new_value", "reason"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_memory",
            "description": "保存值得跨多轮保留的剧情信息。不要保存临时或重复细节。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["episodic", "semantic", "summary", "implicit"],
                    },
                    "content": {"type": "string"},
                    "importance": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },
                "required": ["kind", "content"],
                "additionalProperties": False,
            },
        },
    },
]


class ToolExecutor:
    """执行模型工具调用，并收集本轮产生的新记录。"""

    def __init__(
        self,
        db: Session,
        model: ModelClient,
        chat_id: str,
        source_message_id: str,
        memory_service: MemoryService,
        state_service: StateService,
        graph_service: RoleplayGraphService,
    ) -> None:
        self.db = db
        self.model = model
        self.chat_id = chat_id
        self.source_message_id = source_message_id
        self.memory_service = memory_service
        self.state_service = state_service
        self.graph_service = graph_service
        self.created_proposals: list[StateChangeRecord] = []
        self.created_memories: list[MemoryRecord] = []

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "upsert_scene":
            path = [str(item) for item in arguments.get("path", [])]
            scene = self.graph_service.upsert_scene_path(
                self.db,
                self.chat_id,
                path,
                str(arguments.get("description", "")),
                bool(arguments.get("is_current", False)),
                self.source_message_id,
            )
            return {"scene_id": scene.id, "path": path, "is_current": scene.is_current}

        if name == "upsert_npc":
            location_id = None
            location_path = [str(item) for item in arguments.get("location_path", [])]
            if location_path:
                location = self.graph_service.upsert_scene_path(
                    self.db, self.chat_id, location_path, source_message_id=self.source_message_id
                )
                location_id = location.id
            npc = self.graph_service.upsert_npc(
                self.db,
                self.chat_id,
                str(arguments["name"]),
                str(arguments.get("description", "")),
                str(arguments.get("relation_to_user", "")),
                list(arguments.get("relations", [])),
                str(arguments.get("importance", "supporting")),
                str(arguments.get("presence", "away")),
                location_id,
                str(arguments.get("outfit", "")),
                str(arguments.get("condition", "")),
                self.source_message_id,
            )
            return {"npc_id": npc.id, "name": npc.name, "presence": npc.presence}

        if name == "query_state":
            entries = self.state_service.list_entries(
                self.db,
                self.chat_id,
                entity=_clean_optional(arguments.get("entity")),
                key=_clean_optional(arguments.get("key")),
            )
            return [
                {
                    "entity": entry.entity,
                    "key": entry.key,
                    "value": json_loads(entry.value_json),
                    "version": entry.version,
                }
                for entry in entries
            ]

        if name == "search_memories":
            results = await self.memory_service.search(
                self.db,
                self.model,
                self.chat_id,
                str(arguments.get("query", "")),
                max(1, min(int(arguments.get("limit", 5)), 10)),
            )
            return [
                {
                    "kind": item.record.kind,
                    "content": item.record.content,
                    "score": item.score,
                    "source_message_id": item.record.source_message_id,
                }
                for item in results
            ]

        if name == "propose_state_change":
            proposal = self.state_service.apply(
                self.db,
                self.chat_id,
                str(arguments["entity"]),
                str(arguments["key"]),
                arguments.get("new_value"),
                str(arguments["reason"]),
                self.source_message_id,
            )
            self.created_proposals.append(proposal)
            return {"proposal_id": proposal.id, "status": proposal.status}

        if name == "write_memory":
            try:
                kind = MemoryKind(str(arguments.get("kind", "semantic")))
            except ValueError:
                kind = MemoryKind.SEMANTIC
            memory = await self.memory_service.create(
                self.db,
                self.model,
                self.chat_id,
                kind,
                str(arguments["content"]),
                float(arguments.get("importance", 0.5)),
                self.source_message_id,
            )
            self.created_memories.append(memory)
            return {"memory_id": memory.id, "kind": memory.kind}

        raise ValueError(f"未知工具：{name}")


def _clean_optional(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
