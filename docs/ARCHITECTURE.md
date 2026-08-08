# 系统架构

## 整体结构

```mermaid
flowchart LR
    UI[React 客户端] -->|HTTP JSON| API[FastAPI 接口层]
    API --> RT[Agent Runtime]
    RT --> LLM[OpenAI 兼容模型]
    RT --> CTX[上下文组装器]
    RT --> TOOLS[工具注册表]
    CTX --> MEM[记忆与 RAG 服务]
    CTX --> STATE[状态服务]
    TOOLS --> MEM
    TOOLS --> STATE
    RT --> AUDIT[一致性审计器]
    API --> DB[(SQLite)]
    MEM --> DB
    STATE --> DB
    AUDIT --> DB
```

## 后端分层

- `api`：HTTP 路由和依赖注入，负责验证请求，并把服务结果转换成公开数据模型。
- `services`：记忆检索、状态变更、审计、上下文组装和 Agent 执行等业务逻辑。
- `llm`：与厂商无关的模型接口，以及 OpenAI 兼容实现和演示实现。
- `models`：SQLAlchemy 持久化模型，是数据库内部的数据表示。
- `schemas`：Pydantic 请求和响应模型，是 API 对外的数据契约。
- `database`：数据库引擎和单次请求的 Session 生命周期。
- `config`：带安全默认值的环境配置。

## 一轮对话的数据流

```mermaid
sequenceDiagram
    participant U as 用户
    participant A as FastAPI
    participant D as SQLite
    participant R as Agent Runtime
    participant M as 记忆/状态工具
    participant L as LLM

    U->>A: POST /chats/{id}/messages
    A->>D: 保存用户消息
    A->>R: 执行一轮 Agent
    R->>M: 组装角色、触发的世界书、近期消息、记忆和状态
    R->>L: 携带工具定义请求模型
    loop 最多执行配置的步数
        L-->>R: 返回工具调用
        R->>M: 执行工具并记录轨迹
        M-->>R: 返回工具结果
        R->>L: 携带结果继续推理
    end
    L-->>R: 返回最终角色回复
    R->>D: 保存回复、记忆、轨迹和审计问题
    A-->>U: 返回正文和调试面板数据
```

## 数据权威规则

- 原始消息是历史记录，除未来明确的编辑流程外不会被修改。
- 角色档案是每轮固定注入的人物约束；世界书按关键词和优先级选择性注入。
- 已批准的结构化状态是精确数值的唯一事实来源。
- 待审核建议在用户批准前不会改变当前状态。
- 记忆是可检索的叙事证据，不作为精确数值的最终依据。
- 审计、记忆和状态建议在可能时保留来源消息 ID。

## RAG 策略

MVP 将向量以 JSON 保存到 SQLite，不要求额外安装向量数据库。检索同时考虑 Embedding 余弦相似度、关键词重合、重要度和时间因素。它适合本地简历项目的数据量；后续扩展可以替换为 Qdrant 或 PostgreSQL + pgvector。

## 数据库演进

完整 1.0 使用新的 `saraswati_v1.db`，保留教程阶段的旧数据库。第一版干净结构由 SQLAlchemy 创建；1.0 表结构稳定后，再用 Alembic 管理后续数据库迁移。
