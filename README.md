# Saraswati Agent

[![CI](https://github.com/maximilian-2778/saraswati-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/maximilian-2778/saraswati-agent/actions/workflows/ci.yml)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=black)

一个面向长篇角色扮演的 Agent 原生聊天客户端。它不只是把消息转发给大模型，而是通过“上下文组装 → RAG 记忆召回 → 模型决策 → 工具执行 → 状态审批 → 生成后审计”的运行链路，解决长对话失忆、精确数值漂移和运行过程不可解释的问题。

## 主要功能

- 可信摘要森林：每轮生成带原文指纹的叶子，并逐级压缩成引用子节点的章节与篇章。
- 失效与回退：改写楼层后自动标记旧分支失效，注入时下钻到仍可信的节点，也可一键重建。
- 记忆覆盖诊断：显示漏摘、失效、覆盖率以及当前真正注入模型的摘要节点。
- 故事时间线：自动识别显式时间表达，也支持手动补充锚点。
- 场景树：按“世界 › 区域 › 建筑 › 房间”维护地点层级，并明确当前位置。
- NPC 关系图：跟踪核心度、在场状态、位置、外观、伤势以及人物间关系。
- 分类剧情台账：集中管理物品、NPC、场景、计划与悬念，并保留审核流程。
- 可复用角色库：角色模板独立于故事，一个故事可绑定多个角色副本。
- 可复用世界书库：世界书模板支持触发词、优先级和多故事复用。
- 故事快照隔离：创建或绑定时复制模板，剧情修改不会覆盖原始设定。
- 分档混合 RAG：多视角查询综合向量、关键词、重要度和时间，高可信命中注入原文，其余注入摘要。
- 独立 Reranker：可接不同供应商的 `/rerank` 模型，失败时无感降级为本地排序。
- 事件溯源状态账本：金币、属性、物品和地点等当前事实由已批准事件顺序回放得到。
- 人工审核：Agent 只能提出状态变更建议，批准后才写入正式状态。
- 一致性审计：生成后检查回复中的数值是否与已批准状态冲突。
- Agent 运行轨迹：查看上下文组装、模型响应、工具调用和执行结果。
- 可视化设置中心：配置模型 API、生成参数、Agent/RAG 参数和界面偏好。
- 离线演示模式：没有 API Key 也可以完整体验数据流和核心功能。

## 技术栈

- 后端：Python 3.13、FastAPI、Pydantic、SQLAlchemy、SQLite、httpx。
- 前端：React、TypeScript、Vite、原生 CSS。
- AI：OpenAI 兼容 Chat Completions/Embeddings、工具调用、混合 RAG。
- 工程化：pytest、FastAPI TestClient、Git、环境变量配置。

## 第一次运行

在项目根目录打开两个 PowerShell 终端。

终端一启动后端：

```powershell
.\scripts\start_backend.ps1
```

这条脚本会使用项目自己的 `.venv`，在 `http://127.0.0.1:8000` 启动 FastAPI。接口文档位于 `http://127.0.0.1:8000/docs`。

终端二启动前端：

```powershell
.\scripts\start_frontend.ps1
```

这条脚本会进入 `frontend` 目录并启动 Vite。浏览器打开 `http://127.0.0.1:5173` 即可使用。

如果 PowerShell 阻止脚本运行，也可以直接执行等价命令：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
cd frontend
npm run dev
```

## 配置真实模型

启动应用后点击右上角“设置”，在“模型 API”中填写地址、API Key 和模型名，再点击“保存并测试连接”。服务只要兼容 OpenAI 的 Chat Completions 接口即可。也可以复制 `.env.example` 为 `.env` 手动配置。

设置中心还可以调整温度、Top-P、输出长度、Agent 最大步数、近期上下文条数、RAG 召回量和混合检索权重。未完整填写模型配置时自动使用演示模式。API Key 保存在本机 `data/settings.json`，接口只返回末四位提示，不返回明文；该文件已被 Git 忽略。

## 创建故事与设定

先从顶部“角色库”和“世界书库”维护可复用模板。新建故事时填写标题并多选需要的模板，系统会为该故事创建独立副本。后续也可以继续绑定模板，或只编辑故事副本；原始模板不会被剧情变化覆盖。故事的所有角色都会进入上下文，带关键词的世界书只在当前消息命中时注入，关键词留空则作为常驻词条。

故事开始后，右侧“记忆中枢”会为每轮回复建立带原文指纹的 L0 叶子。默认每 8 个同级根压缩为 L1 章节，每 4 个章节继续形成更高层篇章；节点保存子节点 ID，因此楼层改写后可以识别受影响的整条祖先链。近期窗口继续发送原文，窗口外历史才由最高可信摘要代替。物品、人物、场景和悬念的变化先进入待审核台账，批准事件按顺序重放后才形成 Agent 使用的当前事实。

场景树和 NPC 图谱位于记忆中枢的“世界”页签。Agent 会在地点变化、人物登离场或关系变化时调用专门工具；手动添加入口用于修正模型遗漏。

## 测试与构建

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run build
```

第一条运行后端自动化测试；第二组命令执行 TypeScript 检查并生成前端生产构建。

## 文档导航

- [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md)：1.0 功能范围与验收标准。
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)：架构、模块职责和数据流。
- [`docs/SETTINGS.md`](docs/SETTINGS.md)：设置中心参数说明和安全注意事项。

## 项目边界

当前版本是适合校招展示的单机 MVP，不是生产级多用户平台。它已经实现完整 Agent 数据闭环，但暂未包含登录鉴权、云端部署、流式输出、独立重排模型和大规模向量数据库。这样做是为了把重点放在 Agent 架构、叙事记忆、状态一致性和可解释性上。
