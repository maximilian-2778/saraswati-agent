# Changelog

All notable changes to Saraswati Agent are documented in this file.

## [Unreleased]

### Planned

- Streaming model responses.

## [0.5.0] - 2026-08-08

### Added

- 每轮自动提取结构化剧情 Delta，记录摘要、时间变化、事实、悬念、数值和图谱事件。
- 场景/NPC 不可变事件日志与投影重放，消息改写后自动剔除来源失效事件。
- Token 预算器和 `context_built` 分区占用诊断，始终为模型输出预留空间。
- 记忆中枢“变化”页签，显示 Delta 内容与原文指纹有效性。
- 固定角色扮演 RAG 数据集、Recall@K/MRR 脚本和 300 轮长上下文压力评测。

### Changed

- 手动删除场景/NPC 也写入事件日志，避免投影重建时错误复活。
- 模型 Delta 提取失败时降级为本地数值提取，不影响正文保存。

## [0.4.0] - 2026-08-08

### Added

- 父子地点、当前位置和层级路径组成的故事场景树。
- 带重要度、在场状态、位置、与玩家关系和 NPC 间关系的角色图谱。
- Agent 可调用的场景与 NPC 更新工具，以及按相关性控制的图谱上下文注入。
- 独立 `/rerank` 服务配置，兼容 Cohere/Jina 风格响应并保护单独的 API Key。

### Changed

- 独立 reranker 对本地混合检索候选进行精排；未配置或服务失败时自动降级。
- 记忆中枢增加“世界”页签，场景树和 NPC 图谱可自动维护也可手动管理。

## [0.3.0] - 2026-08-08

### Added

- 每轮回复后自动生成可检索的楼层摘要。
- 楼层摘要自动压缩为章节总结，章节继续压缩为篇章概览。
- 显式故事时间识别、自动时间锚点与手动补充时间线。
- 摘要编辑、删除、多选合并以及精简/详细两种生成模式。
- 将结构化状态按物品、人物、场景、悬念和其他事实分类为剧情台账。
- 可解释的主动记忆检索页面和独立高级诊断区。
- 带原文指纹、子节点引用和覆盖率诊断的摘要森林。
- 楼层改写后的失效传播、旧向量索引排除与一键分支重建。
- 旧故事漏摘检测和自动补齐入口。

### Changed

- “运行观察台”重构为玩家导向的“记忆中枢”。
- 上下文从摘要森林选择最高完整节点；损坏分支自动下钻，近期原文不重复注入摘要。
- RAG 改为多视角检索，并按置信度选择原文档或摘要档。
- 已批准状态改为事件真源，当前台账由事件顺序重放得到。
- 高重要度事实成为少量常驻深层记忆，其余记忆仅在相关时浮现。
- 自动摘要阈值和默认详细程度可在设置中心调整。

## [0.2.0] - 2026-08-08

### Added

- 独立于故事的可复用角色模板库与世界书模板库。
- 新建故事时可多选角色和世界书，并自动创建故事私有副本。
- 已有故事可以继续绑定模板副本，也可以独立编辑或移除副本。
- 多角色上下文组装，以及旧版故事内角色/世界书的自动兼容迁移。

### Changed

- 角色与世界书从运行观察台移到顶部一级导航。
- 模板修改、删除与故事内演化彻底隔离，避免覆盖原始设定。

## [0.1.0] - 2026-08-08

### Added

- Stateful roleplay Agent runtime with bounded tool execution.
- Layered long-term memory and explainable hybrid RAG retrieval.
- Structured state ledger with human approval and numeric consistency audits.
- Story-local character profiles and keyword-triggered world-book entries.
- React client with trace inspection, runtime settings and local demo mode.
- FastAPI test suite and production frontend build.
