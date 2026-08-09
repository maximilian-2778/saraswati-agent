# 系统架构

## 整体结构

```mermaid
flowchart LR
    UI[React 客户端] -->|HTTP JSON| API[FastAPI 接口层]
    API --> RT[Agent Runtime]
    RT --> LG[LangGraph StateGraph]
    LG --> LLM[OpenAI 兼容模型]
    LG --> CTX[上下文组装器]
    LG --> TOOLS[工具注册表]
    LG --> CP[(节点检查点)]
    CTX --> FOREST[摘要森林选择器]
    CTX --> MEM[分档 RAG 服务]
    CTX --> STATE[状态服务]
    CTX --> GRAPH[场景树 / NPC 图谱]
    TOOLS --> MEM
    TOOLS --> STATE
    LG --> AUDIT[一致性审计器]
    LG --> DELTA[剧情 Delta 提取器]
    CTX --> BUDGET[Token 预算器]
    API --> DB[(SQLite)]
    MIG[Alembic revisions] --> DB
    MEM --> DB
    STATE --> EVENTS[已批准状态事件]
    EVENTS --> DB
    AUDIT --> DB
    GRAPH --> DB
    DELTA --> DB
    CP --> DB2[(langgraph_checkpoints.db)]
    GRAPH --> GEVENTS[场景 / NPC 事件日志]
    GEVENTS --> DB
```

## 后端分层

- `api`：很薄的公开入口，只汇总各领域路由。
- `routers`：按系统、模板、故事、记忆和状态分组，公开 URL 保持稳定。
- `controllers`：处理 HTTP 请求、依赖注入和响应转换；后续新增接口应先放入对应领域模块。
- `services`：记忆检索、状态变更、审计、上下文组装和 Agent 执行等业务逻辑。
- `services/agent_graph`：LangGraph 状态、节点和条件边；图状态只保存可序列化数据。
- `services/agent`：工作流生命周期和原有 `run_turn` 接口；数据库会话、模型和工具执行器通过运行时上下文注入。
- `llm`：与厂商无关的模型接口，以及 OpenAI 兼容实现和演示实现。
- `models`：SQLAlchemy 持久化模型，是数据库内部的数据表示。
- `schemas`：Pydantic 请求和响应模型，是 API 对外的数据契约。
- `database`：数据库引擎、单次请求的 Session 生命周期和旧库兼容补齐逻辑。
- `migrations`：启动时执行 Alembic upgrade，并接管没有 revision 的旧数据库。
- `config`：带安全默认值的环境配置。

## 一轮对话的数据流

```mermaid
sequenceDiagram
    participant U as 用户
    participant A as FastAPI
    participant D as SQLite
    participant R as LangGraph Runtime
    participant C as Checkpointer
    participant M as 记忆/状态工具
    participant L as LLM

    U->>A: POST /chats/{id}/messages
    A->>D: 保存用户消息
    A->>R: 执行一轮 Agent
    R->>C: 保存初始状态
    R->>M: 组装角色、触发的世界书、近期消息、记忆和状态
    R->>C: 保存上下文节点状态
    R->>L: 携带工具定义请求模型
    loop 最多执行配置的步数
        L-->>R: 返回工具调用
        R->>M: 执行工具并记录轨迹
        M-->>R: 返回工具结果
        R->>C: 保存工具节点状态
        R->>L: 携带结果继续推理
    end
    L-->>R: 返回最终角色回复
    R->>D: 保存回复、记忆、剧情 Delta、轨迹和审计问题
    R->>C: 保存完成状态
    A-->>U: 返回正文和调试面板数据
```

## 数据权威规则

- LangGraph 检查点只保存消息、记录 ID、执行步数和路由结果；数据库会话、模型客户端、回调和 API Key 不进入图状态。
- 每轮使用独立 `thread_id`，节点状态写入单独的本地 SQLite 文件；剧情长期记忆仍由业务数据库管理。

- 原始消息允许用户显式改写；摘要叶子的原文指纹用于检测改写，而不是静默同步旧摘要。
- 角色和世界书模板是跨故事复用的母版；故事只绑定创建时复制出的私有快照。
- 一个故事可以拥有多个角色和多个世界书副本；角色全部注入，世界书按关键词和优先级选择性注入。
- 故事副本可以随剧情演化，模板的修改或删除不会覆盖已有故事内容。
- 每轮回复生成 L0 摘要叶子；压缩节点保存子节点 ID，形成可验证的摘要森林。
- 窗口外历史优先由最高完整节点表示；若子叶失效，祖先不再注入并自动下钻到可信旁支。
- 修复操作删除失效分支及对应向量索引，再依据新原文重建，避免 RAG 偷渡旧剧情。
- 时间锚点从显式故事时间中提取，物品、NPC、场景和悬念复用带审批的结构化状态账本。
- 场景树和 NPC 图谱是叙事知识结构；Agent 可自动维护，但上下文只选择当前场景、在场人物、核心人物和查询命中的节点。
- 场景和 NPC 当前表是事件投影；更新与删除先写入带来源哈希的事件，消息改写后清空投影并重放有效事件。
- 每轮 Delta 绑定用户/助手消息共同指纹；前端可以明确区分有效变化和已被改写淘汰的旧变化。
- 已批准的状态变更事件是精确数值的真源；`state_entries` 是按事件顺序重放生成的当前投影。
- 待审核建议在用户批准前不会改变当前状态。
- 记忆是可检索的叙事证据，不作为精确数值的最终依据。
- 审计、记忆和状态建议在可能时保留来源消息 ID。

## RAG 策略

MVP 将向量以 JSON 保存到 SQLite，不要求额外安装向量数据库。一次查询会扩展为事件、人物关系、物品状态和计划悬念等视角，再综合 Embedding 余弦相似度、关键词重合、重要度和时间因素。近期原文及失效分支会被排除；本地初排候选可发送给独立 `/rerank` 服务，高分结果注入清洗后的来源原文，普通结果只注入摘要。精排失败会自动保留本地顺序。

## 数据库演进

应用使用 Alembic 管理业务数据库结构。空数据库从 `0001` 依次升级到 head；已有业务表但没有 `alembic_version` 的旧库会先由兼容逻辑补齐 0.9 基线字段和数据，再 stamp 到 `0001`。后续模型变化必须增加 revision，不能继续在启动函数中追加临时 `ALTER TABLE`。

SQLite 迁移启用 batch mode。自动生成脚本提交前需要检查字段改名、约束变化、数据搬迁和 downgrade 顺序；CI 通过 `alembic check` 发现 ORM Metadata 与迁移 head 的差异。
