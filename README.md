# Saraswati Agent

[![CI](https://github.com/maximilian-2778/saraswati-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/maximilian-2778/saraswati-agent/actions/workflows/ci.yml)
![Python 3.13](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![React](https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=black)

Saraswati Agent 是一个长篇角色扮演聊天客户端。我做这个项目，是因为普通聊天窗口聊久以后很容易忘记人物关系、物品数量和前面的约定。

它目前可以自动整理旧剧情，按当前话题找回相关片段，并单独记录金币、物品、人物状态和故事时间。角色回复仍由你配置的大模型生成。

## 现在能做什么

- 保存多个故事，各自拥有独立的对话和记录。
- 建立可复用的角色与世界书，添加到故事时会生成一份故事内版本。
- 自动整理逐轮摘要、章节回顾和长篇回顾。
- 改写旧消息后，重新检查受影响的摘要、状态和场景记录。
- 记录物品、金币、人物状态、地点、计划和悬念；重要修改需要用户确认。
- 维护场景层级、当前位置、NPC 关系和在场情况。
- 从旧对话中搜索与当前内容相关的回忆，并显示匹配理由。
- 检查回复里的数字是否与已确认记录冲突。
- 查看每轮用了哪些上下文、调用了哪些工具，以及大致占用了多少 Token。
- 单独配置对话模型、Embedding 模型和 Reranker。

没有配置模型时，程序会使用本地演示模式。演示模式适合检查界面和数据流程，不会生成正式的角色回复。

## 界面

对话一直保留在主窗口。角色、世界书、故事资料和设置按需弹出，用完可以直接收起。

“故事资料”中包含剧情摘要、时间线、人物与场景、物品和状态记录、相关回忆及运行检查。大多数时候不需要打开它，后台会继续整理内容。

## 技术栈

- 后端：Python 3.13、FastAPI、Pydantic、SQLAlchemy、SQLite、httpx
- 前端：React、TypeScript、Vite、CSS
- 模型接口：OpenAI 兼容的 Chat Completions 与 Embeddings
- 检索：本地混合排序，可选独立 Reranker
- 测试：pytest、FastAPI TestClient、TypeScript 构建、固定 RAG 评测集

## 本地运行

需要 Python 3.13、Node.js 和项目虚拟环境。启动时打开两个 PowerShell 终端。

后端：

```powershell
.\scripts\start_backend.ps1
```

前端：

```powershell
.\scripts\start_frontend.ps1
```

然后访问 `http://127.0.0.1:5173`。FastAPI 接口文档位于 `http://127.0.0.1:8000/docs`。

脚本无法运行时，可以使用下面的等价命令：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
cd frontend
npm run dev
```

## 配置模型

打开右上角“设置”，填写 API 地址、API Key 和模型名。保存后可以直接测试连接。

API Key 保存在本机的 `data/settings.json`，聊天数据保存在 `data/saraswati_v1.db`。这两个文件都已加入 Git 忽略规则。配置文件没有额外加密，请勿上传或分享。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_rag_eval.py
.\.venv\Scripts\python.exe scripts\run_long_context_eval.py
cd frontend
npm run build
```

- `pytest` 检查 API、消息改写、记忆、状态和场景回放。
- `run_rag_eval.py` 输出 Recall@1 和 MRR。
- `run_long_context_eval.py` 模拟 300 轮对话，检查上下文裁剪。
- `npm run build` 执行 TypeScript 检查并生成前端构建。

## 代码结构

```text
backend/
  api.py                 API 汇总入口
  controllers.py         HTTP 处理函数
  routers/               按系统、模板、故事、记忆、状态分组的路由
  services/              对话、记忆、检索、状态和场景逻辑

frontend/src/
  App.tsx                前端入口
  pages/                 页面
  hooks/                 可复用状态逻辑
  MemoryHub.tsx          可收起的故事资料抽屉
```

## 其他文档

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)：后端数据流和模块职责
- [`docs/SETTINGS.md`](docs/SETTINGS.md)：设置项说明
- [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md)：功能范围与验收项目
- [`CHANGELOG.md`](CHANGELOG.md)：版本记录

## 当前范围

这是一个单机项目，数据默认留在本机。登录、多人协作、云端同步、流式输出和安装包还没有完成。
