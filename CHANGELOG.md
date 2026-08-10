# Changelog

All notable changes to Saraswati Agent are documented in this file.

## [1.1.0] - 2026-08-10

### Added

- Added centered RPG-style scene and character detail dialogs with separate navigation for profiles, attributes, relationships, and inventories.
- Added reusable engraved ornaments and bookplate details for the story archive and writing composer.

### Changed

- Refined the light and dark themes with consistent literary typography, stronger text contrast, paper depth, and restrained printmaking details.
- Reworked the console, settings center, and writing preset interfaces so their typography and controls follow the same classical archive system.
- Improved the empty-story composition, responsive spacing, navigation icons, selected-story treatment, and composer presentation.
- Removed redundant console decoration and the duplicate sidebar console entry.

### Fixed

- Fixed dark-theme text and illustration contrast regressions.
- Fixed modal placement, nested panel scrolling, unintended horizontal scrollbars, and several title, badge, and close-button alignment issues.
- Fixed stretched, blurred, and misaligned composer ornaments by preserving their source proportions and extending only the connecting rules.

## [1.0.0] - 2026-08-09

Saraswati Agent 的首个正式版本。该版本整合了独立角色扮演客户端、可复用资料库、分层长期记忆、RAG、结构化剧情状态和 LangGraph 生成后整理流程。

### Added

- 独立的多故事角色扮演聊天客户端，支持头像、消息编辑、重新生成、收藏、检查点和故事快照。
- 可复用的角色、主控人物、世界书和写作预设资料库。
- 分层摘要、时间锚点、向量记忆、RAG 召回、场景树、NPC 图谱、物品与精确状态管理。
- LangGraph 对话编排、工具调用、结构化 Narrative Delta、自动采用、修改历史、一键撤销和回复审计。
- OpenAI-compatible 对话、Embedding、结构化输出和独立 Reranker 配置。
- 上下文预算、模型 tokenizer、世界书触发记录、Prompt 预览、耗时与费用估算。
- Alembic 数据库迁移、模块化 FastAPI 路由、供应商适配器和完整回归测试。
- React、TypeScript、TanStack Query 构建的古典档案风格界面，包含亮色与暗色主题。

### Known issues

- 控制台导航角标当前显示数据总量，尚未区分“新增未读”和“已经查看”。
- 控制台标题装饰线、数字角标和关闭符号仍需进一步校正视觉对齐。

## [0.14.0] - 2026-08-09

### Added

- 增加可复用的写作预设库，用于管理主提示词、文风、禁写项和历史后指令。
- 写作提示词支持启停、System/User/Assistant 角色、顺序调整、自定义内容与 In-Chat Depth。
- 预设可以复制、启用、删除，并支持 SillyTavern Chat Completion JSON 导入导出。
- 支持 `{{char}}`、`{{user}}` 宏；角色、主控人物、世界书、长期总结、RAG 和聊天记录继续由故事上下文独立装配。
- 增加 Alembic `0002` 迁移和预设启用、顺序、导入导出回归测试。

### Changed

- 预设移动到角色、主控人物和世界书同级的顶部导航，不再混入模型设置。
- 启用预设不会修改 Temperature、Top-P、输出 Token、Penalty 或上下文窗口。
- 上下文调试页分别显示写作预设和故事资料，便于发现重复注入。

## [0.13.0] - 2026-08-09

### Added

- 生成后 Delta 增加场景、NPC、物品和通用状态变化。
- LangGraph 增加 `apply_narrative_delta` 节点，在回复保存后补齐时间、场景、人物和精确状态。
- Agent 产生的物品与数值变化默认自动采用，同时保留来源、旧值和完整修改记录。
- 修改记录支持一键撤销；撤销后按剩余事件重建当前状态。
- 增加生成后整理和状态撤销的端到端测试。

### Changed

- 主模型工具调用继续负责实时更新，生成后整理按当前投影和来源消息去重，避免重复写入。
- 消息改写后，相关自动修改会标记为已撤销，不再重新堆进待确认列表。

## [0.12.0] - 2026-08-09

### Added

- 设置中心增加可选的上下文调试模式，默认保持关闭。
- 故事资料增加“上下文”页，按发送顺序展示系统规则、主控人物、角色、世界书、长期总结、RAG、场景、状态、近期对话和用户消息。
- 每个上下文块显示启用状态、Token、加入原因和实际内容。
- 增加总预算、剩余额度、裁剪记录、世界书触发记录、RAG 分数和最终 Prompt 预览。
- 记录整轮耗时、每次模型调用耗时、输入输出 Token 和可配置的费用估算。
- 模型设置增加每百万输入与输出 Token 单价；未配置时不显示虚假费用。

### Changed

- Token 预算诊断现在保留被裁剪消息的角色、Token 数和短预览。
- 上下文调试页的详细模块可以分别开关，避免日常角色扮演界面过载。

## [0.11.0] - 2026-08-09

### Added

- 使用模型 tokenizer 计算上下文占用，未知模型保留启发式回退。
- 剧情 Delta 支持 JSON Schema 结构化输出，并通过 Pydantic 严格校验。
- 前端接入 TanStack Query，统一缓存工作区和故事数据。
- 为模型级 Token 计算和结构化剧情提取增加回归测试。

### Changed

- 将原有总控制器拆为系统、模板、故事、记忆和状态五组路由。
- 将 OpenAI 兼容接口拆成独立供应商适配器，复用 HTTP 连接并重试暂时性故障。
- 将聊天页中的资料库、设置中心、消息和头像拆成独立组件。
- `ChatWorkspace.tsx` 从约 101 KB 缩减到约 46 KB。

## [0.10.0] - 2026-08-09

### Added

- 引入 Alembic 1.18 管理 SQLAlchemy 业务数据库结构。
- 增加包含 25 张业务表、索引、外键和唯一约束的 `0001` 基线迁移。
- 后端启动时自动执行尚未完成的 revision。
- 增加空库升级、旧库接管、ORM 差异检查和 downgrade/upgrade 往返测试。

### Changed

- 没有 Alembic 版本号的旧数据库会先补齐现有字段和历史数据，再 stamp 到基线版本。
- `database.py` 中的手写迁移只保留为旧库接管桥梁，新结构变化统一写入 Alembic revision。

## [0.9.0] - 2026-08-09

### Added

- 使用 LangGraph StateGraph 编排完整对话流程。
- 为上下文、模型、工具、强制收尾、回复保存、记忆、剧情 Delta 和审计建立独立节点。
- 模型结果通过条件边进入工具循环或回复保存流程。
- 使用独立 SQLite Checkpointer 保存每个节点完成后的可序列化状态。
- 增加工具循环、步数上限、模型失败和持久化检查点回归测试。

### Changed

- 保留原有 `AgentRuntime.run_turn` 接口，FastAPI、前端、RAG、记忆和状态服务无需改动。
- 更新本机模型设置时会安全替换 LangGraph Runtime，并关闭旧检查点连接。

## [0.8.1] - 2026-08-09

### Changed

- 资料编辑窗口改为宽屏居中浮层，较小屏幕下自动贴合可用空间。
- 客户端中的 Persona 统一改称“主控人物”。

### Fixed

- 当前故事中的主控人物快照现在可以单独移除，不会删除资料库模板。

## [0.8.0] - 2026-08-09

### Added

- 主控人物资料库；新建故事时可选择玩家身份并生成独立快照。
- 角色开场白、备选开场白、示例对话、标签、创作者备注和专属系统提示词。
- 角色搜索、收藏、复制，以及 SillyTavern V2 JSON 与 PNG 角色卡导入导出。
- 角色与主控人物可绑定专属世界书，创建故事时自动复制对应词条。
- 世界书次要关键词、常驻、大小写、扫描深度、插入位置、互斥组、递归激活和 Token 预算。
- 顶栏收藏列表，可查看收藏内容并跳转到原消息。

### Changed

- 主控人物、角色、世界书在故事中使用快照，后续剧情修改不会覆盖资料库原件。
- 世界书编辑器默认保留常用字段，其余选项收进高级设置。

## [0.7.0] - 2026-08-09

### Changed

- 重做主聊天界面：消息、工具栏、故事列表和输入区采用连续阅读布局。
- 调整桌面端、平板和手机端的页面尺寸与导航排列。
- 用户消息移到右侧，角色消息保留在左侧，头像改为圆形。

### Added

- 删除故事并同步清理消息、记忆、状态和场景数据。
- 为角色模板、故事角色副本和用户分别设置本地头像。
- 通过 NDJSON 返回模型流式正文，并支持中途停止生成。
- 同一条角色回复保存多个候选版本，可以前后切换或重新生成。
- 消息复制、收藏、编辑、剧情截断和快捷操作栏。
- 从任意消息创建故事分支，并用检查点恢复为新分支。
- 阅读旧消息时暂停自动滚动，提供回到底部按钮和键盘快捷键。

## [0.6.0] - 2026-08-08

### Changed

- 对话保持在主界面，故事资料改为可以随时收起的右侧抽屉。
- 角色和世界书改为弹窗管理，关闭后仍停留在原来的对话位置。
- `App.tsx` 缩为前端入口，聊天页面与界面偏好分别放入 `pages` 和 `hooks`。
- 后端 API 按系统、模板、故事、记忆和状态分为五组路由，公开 URL 保持不变。
- 重写客户端主要说明和 README，减少生硬的内部术语。

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
- React client with trace inspection, runtime settings and local API configuration.
- FastAPI test suite and production frontend build.
