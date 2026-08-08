# Saraswati Agent

[![CI](https://github.com/maximilian-2778/saraswati-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/maximilian-2778/saraswati-agent/actions/workflows/ci.yml)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=black)

一个面向长篇角色扮演的 Agent 原生聊天客户端。它不只是把消息转发给大模型，而是通过“上下文组装 → RAG 记忆召回 → 模型决策 → 工具执行 → 状态审批 → 生成后审计”的运行链路，解决长对话失忆、精确数值漂移和运行过程不可解释的问题。

## 主要功能

- 分层记忆：情节、事实、摘要和隐性记忆分别保存。
- 独立角色档案：管理身份、性格、说话风格和当前情境。
- 关键词世界书：词条支持触发词、常驻模式、优先级和启停控制。
- 混合 RAG：综合向量相似度、关键词、重要度和时间衰减召回历史。
- 结构化状态账本：金币、属性、物品、地点等精确事实不交给模型猜测。
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

新建故事时只需要填写存档标题。创建后在右侧“角色”板块填写角色档案，在“世界书”板块维护世界设定。角色档案每轮都会进入上下文；带关键词的世界书只在当前消息命中关键词时注入，关键词留空则作为常驻词条。

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

当前版本是适合校招展示的单机 MVP，不是生产级多用户平台。它已经实现完整 Agent 数据闭环，但暂未包含登录鉴权、云端部署、流式输出、重排模型和大规模向量数据库。这样做是为了把重点放在 Agent 架构、记忆、状态一致性和可解释性上。
