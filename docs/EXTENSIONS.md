# 扩展系统

Saraswati 把“扩展”分为两层：

- **Skill**：说明、知识、工作流、模板和资源。它告诉 Agent 应该怎样完成一类任务。
- **Plugin**：可安装的功能包，可同时包含 Skill、MCP 工具服务和配套资源。

独立 Skill 仍可直接安装；需要完整分发时，则把一个或多个 Skill 与工具服务装进同一个 Plugin。

## Skill 接口

把 Skill 放在：

```text
data/extensions/skills/<skill-id>/
  SKILL.md
  references/     # 可选，按需读取
  templates/      # 可选，按需读取
  assets/         # 可选，按需读取
  scripts/        # 可选，只作为资源；Saraswati 不直接执行
```

最小 `SKILL.md`：

```markdown
---
name: Story Dice
description: Use an entropy tool to resolve tabletop dice checks.
version: 1.0.0
tags: [rpg, dice]
---

# Story Dice

Never invent a roll. Call the configured dice tool and narrate its result.
```

加载分为三层：

1. 每轮只提供 `id + name + description`，控制上下文成本。
2. 模型调用 `activate_skill(name)` 后读取完整 `SKILL.md`。
3. 模型按主说明返回的资源列表调用 `activate_skill(name, resource)` 读取单个附属文件。

用户也可以用 `/skill-id` 显式启用本轮 Skill。顶部导航“预设”后的“扩展”工作区负责安装、导出、归档、全局启停和重新扫描。

### 安装、依赖与故事范围

- 可以直接导入 ZIP；压缩包先进入隔离目录，路径、体积、文件数、符号链接、可执行文件和不可见 Unicode 校验通过后才移入活动目录。
- YAML frontmatter 使用 SafeLoader，支持嵌套 `prerequisites` / `setup`、`platforms`、`license`、`compatibility` 等元数据。
- `required_environment_variables`、`prerequisites.env_vars` 与 `prerequisites.commands` 会形成就绪检查；缺少依赖或平台不兼容的 Skill 不可启用。
- 来源、安装时间、内容摘要、查看次数、使用次数和最后使用时间保存在本机侧车数据中。
- 归档是可恢复移动，不直接删除文件；导出的 ZIP 不包含 Saraswati 的来源侧车文件。
- 每个故事可选择“跟随全局”或“仅所选”。白名单同时约束元数据提示、`activate_skill` schema 和工具执行，不能只靠前端隐藏。

### 当前安全边界

- Skill id、文件数和总大小有限制。
- 附属资源必须位于 Skill 目录内，拒绝绝对路径、`..` 和符号链接逃逸。
- ZIP 安装会拒绝不可见 Unicode 和可执行文件；本地手工放入的目录会显示警告。
- 第三方 Skill 默认只读；Agent 没有创建、修改或删除 Skill 的接口。
- `scripts/` 只是协议兼容资源，当前运行时不会执行其中脚本。

## Plugin 包接口

Saraswati 使用下列目录结构，并兼容 Codex 的 `.codex-plugin/plugin.json` 清单：

```text
data/extensions/plugins/<plugin-id>/
  .saraswati-plugin/plugin.json   # 或 .codex-plugin/plugin.json
  skills/                         # 可选，可包含多个 Skill
    <skill-id>/SKILL.md
  .mcp.json                       # 可选，可声明多个 MCP 服务
  assets/                         # 可选，插件资源
  server.py / dist/...            # 可选，由 MCP stdio 配置启动
```

插件可以作为 ZIP 安装或直接放入上述本机目录。ZIP 中允许携带实现工具所需的代码；Saraswati 不把第三方模块导入自身进程，而是按 MCP 配置在隔离的子进程或网络连接中调用。新发现和新安装的插件均默认停用；含本机程序的插件还必须由用户单独信任。

一个插件可声明多个 MCP 服务。`.mcp.json` 同时接受 `mcpServers` 和 `mcp_servers` 包装格式，也接受直接的服务映射。`${PLUGIN_ROOT}` 可用于引用插件内文件，因此导出的插件换一台设备后仍能找到自己的入口程序。

### MCP 工具服务

支持三种 MCP 客户端传输：

- **Streamable HTTP**：当前 MCP HTTP 标准传输。
- **SSE**：兼容仍使用旧 SSE transport 的服务。
- **stdio**：启动受信任的本机 MCP 进程；不经过 shell，新登记时必须显式确认信任。

没有现成插件包时，也可在顶部“扩展”工作区快速创建单服务工具插件：

- `id`：稳定短标识符，例如 `dice-server`
- `name`：显示名称
- `url`：HTTP/SSE endpoint
- `command + args`：stdio 启动程序与逐项参数
- `environment_variables`：允许从 Saraswati 宿主继承给 stdio 子进程的环境变量名称
- `description`：能力说明
- `allowed_tools`：可选工具白名单，留空表示接受该服务器发现的全部工具
- `auth_token`：可选 Bearer Token；只写入独立凭据文件，不出现在清单或 API 返回值中

远程 MCP 必须使用 `https://`；只有 `localhost`、`127.0.0.1` 和 `::1` 可以使用明文 HTTP。新登记的 Plugin 默认停用，用户必须显式开启。连接测试会完成 MCP initialize 和工具发现。

MCP 工具进入模型前会变成：

```text
<plugin-id>__<remote-tool-name>
```

因此第三方 Plugin 无法用重名覆盖 `write_memory`、`propose_state_change` 等内置工具。一个 Plugin 连接失败时只标记该扩展错误，不阻止聊天服务启动。

Saraswati 自建插件的清单保存在：

```text
data/extensions/plugins/<plugin-id>/.saraswati-plugin/plugin.json
```

扩展目录属于本机数据并已加入 `.gitignore`。

认证头单独保存在 `data/extensions/plugin-secrets.json`，API 只返回“是否已配置”和 header 名称。该文件不是云端密钥保险库，仍应依靠操作系统账户与磁盘权限保护；归档 Plugin 时对应凭据会被移除。

## API

```text
GET   /api/extensions
POST  /api/extensions/reload
PATCH /api/extensions/skills/{skill_id}
POST  /api/extensions/skills/install
GET   /api/extensions/skills/{skill_id}/export
DELETE /api/extensions/skills/{skill_id}
GET   /api/extensions/chats/{chat_id}/skills
PUT   /api/extensions/chats/{chat_id}/skills
POST  /api/extensions/plugins
POST  /api/extensions/plugins/install
PATCH /api/extensions/plugins/{plugin_id}
POST  /api/extensions/plugins/{plugin_id}/trust
GET   /api/extensions/plugins/{plugin_id}/export
DELETE /api/extensions/plugins/{plugin_id}
POST  /api/extensions/plugins/{plugin_id}/test
```

## 仍未开放的能力

- 不把第三方 Python/JavaScript 模块直接导入 Saraswati 主进程；可执行能力通过受信任的 MCP 子进程接入。
- 不允许覆盖内置工具。
- 尚未支持 MCP OAuth、扩展商店、发布者签名和自动更新。
- 尚未开放任意 React 组件；未来 UI 扩展会使用受控 Widget Schema。
- 不开放自主编写或自我修改 Skill：Saraswati 当前定位是安全的第三方扩展宿主，Skill 由开发者或用户审核后安装。
- MCP 当前采用短连接，尚未实现常驻进程监督、热重载与崩溃孤儿回收。
