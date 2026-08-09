# Saraswati Agent

[![CI](https://github.com/maximilian-2778/saraswati-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/maximilian-2778/saraswati-agent/actions/workflows/ci.yml)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=black)
![LangGraph](https://img.shields.io/badge/Agent-LangGraph-1C3C3C)

用于长篇角色扮演的本地聊天客户端，支持剧情摘要、状态记录和历史记忆检索。

## 功能

- 多故事管理
- 故事删除
- 可复用的角色、主控人物和世界书资料库
- 可复用的写作预设：主提示词、文风、禁写项和历史后指令
- SillyTavern Chat Completion 预设 JSON 导入导出
- 写作提示词排序、启停、消息角色、In-Chat Depth 和 `{{char}}` / `{{user}}` 宏
- 故事创建时复制资料快照，故事内修改不会覆盖原模板
- 角色开场白、备选开场白、示例对话、标签和专属提示词
- SillyTavern V2 JSON 与 PNG 角色卡导入导出
- 世界书关键词激活、常驻、扫描深度、互斥组、递归激活和 Token 预算
- 角色头像与用户头像
- 模型回复流式输出与随时停止
- 回复重生成和多候选切换
- 消息编辑、复制、收藏、收藏列表和剧情截断
- 故事分支与检查点恢复
- 逐轮摘要、章节回顾和长篇回顾
- 场景层级、人物关系和故事时间记录
- 物品、数值、人物状态、计划与悬念记录
- RAG 历史记忆检索和可选 Reranker
- 物品与数值变化自动采用，保留修改历史并支持一键撤销
- 生成后 Delta 自动补齐时间、场景、NPC、物品和精确状态
- 消息改写后的相关记录更新
- OpenAI 兼容的对话、结构化输出与 Embedding 接口
- 按模型 tokenizer 管理上下文预算
- 可选上下文调试模式：分段 Token、裁剪、世界书触发、RAG 分数和最终 Prompt
- 模型调用耗时、输入输出 Token 与可配置费用估算
- LangGraph 状态图编排、条件工具循环和本地节点检查点

未配置模型时仍可管理故事资料，但发送消息前必须连接兼容的模型 API。

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 后端 | Python 3.13、FastAPI、Pydantic、SQLAlchemy、Alembic、SQLite、httpx |
| Agent 编排 | LangGraph StateGraph、条件边、SQLite Checkpointer |
| 前端 | React、TypeScript、TanStack Query、Vite、CSS |
| 模型接口 | OpenAI-compatible Chat Completions、Embeddings |
| 测试 | pytest、FastAPI TestClient、TypeScript build、RAG 评测脚本 |

## 本地运行

需要 Python 3.13、Node.js 和项目虚拟环境。

启动后端：

```powershell
.\scripts\start_backend.ps1
```

启动前端：

```powershell
.\scripts\start_frontend.ps1
```

前端地址：`http://127.0.0.1:5180`

API 文档：`http://127.0.0.1:8010/docs`

也可以直接运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8010
cd frontend
npm run dev
```

## 模型配置

在客户端右上角打开“设置”，填写 API 地址、API Key 和模型名称。

- 模型配置保存在 `data/settings.json`
- 聊天数据保存在 `data/saraswati_v1.db`
- Agent 节点检查点保存在 `data/langgraph_checkpoints.db`
- 以上文件已加入 `.gitignore`

API Key 以明文保存在本机配置文件中，请勿上传或分享该文件。

## 数据库迁移

后端启动时会自动执行尚未完成的 Alembic revision。常用开发命令：

```powershell
# 查看当前数据库版本
.\.venv\Scripts\python.exe -m alembic current

# 修改 ORM 模型后生成候选迁移
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "change description"

# 检查 ORM 模型是否存在尚未生成的结构变化
.\.venv\Scripts\python.exe -m alembic check

# 手动升级到最新版本
.\.venv\Scripts\python.exe -m alembic upgrade head
```

`--autogenerate` 生成的是候选脚本。字段改名、数据搬迁和 SQLite 表重建需要检查后再提交。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_rag_eval.py
.\.venv\Scripts\python.exe scripts\run_long_context_eval.py
cd frontend
npm run build
```

## 目录

```text
backend/
  api.py                 路由入口
  controller_helpers.py  路由共享的查询与回放函数
  routers/               系统、模板、故事、记忆和状态接口
  providers/             模型供应商适配器
  services/              对话、记忆、检索、状态和场景逻辑
    agent.py              LangGraph Runtime 生命周期与兼容入口
    agent_graph.py        状态、节点、条件边和工作流定义
    narrative_delta_apply.py  生成后变化的去重与应用
    presets.py            预设默认模块与酒馆 JSON 转换

alembic/
  env.py                  迁移运行环境
  versions/               按顺序保存数据库 revision

frontend/src/
  App.tsx                前端入口
  pages/                 聊天工作区
  components/            资料库、设置、消息与通用组件
  hooks/                 TanStack Query 与界面偏好 hooks
  MemoryHub.tsx          故事资料面板
```

## 文档

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/SETTINGS.md`](docs/SETTINGS.md)
- [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md)
- [`docs/ROADMAP.md`](docs/ROADMAP.md)
- [`CHANGELOG.md`](CHANGELOG.md)

## 开发状态

项目目前以本地单机运行。登录、云端同步、多人协作和桌面安装包尚未完成。
