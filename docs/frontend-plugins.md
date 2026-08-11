# 前端插件协议（v1）

Saraswati 插件可以通过 `frontend` 字段提供一个在 sandbox iframe 中运行的本地界面。前端插件默认没有故事数据权限，安装后默认停用；声明数据权限的插件还需要用户明确授权。

## 清单

```json
{
  "id": "story-dashboard",
  "name": "剧情仪表盘",
  "version": "0.1.0",
  "frontend": {
    "entry": "frontend/index.html",
    "title": "剧情仪表盘",
    "height": 640,
    "surfaces": ["panel"],
    "permissions": ["context.read", "chat.read", "worldbook.read", "storage"]
  }
}
```

支持的权限：

- `context.read`：读取当前插件和所选故事的基本信息；
- `chat.read`：读取所选故事的消息；
- `chat.write`：从插件发送内容或修改已有消息；
- `message.read`：读取消息表面正在渲染的单条消息；
- `character.read`：读取当前角色及导入卡保留的兼容数据；
- `worldbook.read`：读取所选故事的世界书条目；
- `worldbook.write`：修改当前故事中的世界书条目；
- `storage`：使用由宿主提供的插件私有 JSON 存储。

入口必须是插件包内存在的 HTML 文件。普通插件只允许访问入口文件所在目录下的资源，并设置禁止网络连接、外部 frame、表单提交和父页面访问的内容安全策略。内置 `tavern-card-frontend` 为兼容酒馆角色卡的外部 HTML 前端，外部 HTTPS 页面会先经宿主兼容代理注入必要的 jQuery 依赖，再在沙箱内部嵌入；外部页面仍不能访问 Saraswati 父页面或 RPC 权限之外的数据。

## RPC

插件和宿主通过 `window.postMessage` 通信，频道固定为 `saraswati.plugin.v1`。

请求：

```js
parent.postMessage({
  channel: "saraswati.plugin.v1",
  type: "request",
  id: "request-1",
  method: "chat.listMessages",
  params: {}
}, "*");
```

响应：

```js
{
  channel: "saraswati.plugin.v1",
  type: "response",
  id: "request-1",
  ok: true,
  result: []
}
```

失败响应会包含 `error` 字符串。宿主会验证消息来源是否为当前插件 iframe，并在执行每个方法前检查清单权限。

## 方法

- `host.getContext()`
- `chat.listMessages()`
- `chat.send({ content })`
- `chat.updateMessage({ messageId, content })`
- `worldbook.list()`
- `worldbook.update({ id, patch })`
- `variables.get({ type, messageId? })`
- `variables.set({ type, messageId?, value })`
- `variables.getAll({ messageId })`
- `storage.get({ key })`
- `storage.set({ key, value })`
- `ui.setHeight({ height })`

插件载入后会收到 `host.ready` 事件，其中包含协议版本、插件标识、已授予权限和当前是否选择了故事。

`surfaces` 支持插件管理页弹窗 `panel` 和聊天消息内嵌 `message`。消息插件还必须通过 `message_patterns` 声明直接匹配文本，或通过 `character_extensions` 声明需要识别的角色卡扩展字段。

首个内置消息插件位于 `bundled_plugins/tavern-card-frontend`，用于兼容酒馆角色卡的显示正则与 HTML 前端。

## 酒馆角色卡兼容核心

内置兼容器 `tavern-card-frontend` 在消息 iframe 中提供独立实现的 `window.TavernHelper`。它不是酒馆助手源码的副本，而是把 Saraswati 的故事数据映射到常用酒馆接口：

- 消息：`getChatMessages`、`setChatMessage`、`setChatMessages`；
- 变量：`getVariables`、`getAllVariables`、`replaceVariables`、`updateVariablesWith`、`insertVariables`、`deleteVariable`；
- MVU：`Mvu.getMvuData`、`Mvu.replaceMvuData`，并从消息的 `JSONPatch` 累积楼层变量；
- 世界书：`getWorldbook`、`getWorldbookEntries`、`getLorebookEntries`、`updateWorldbookWith`；
- 角色：`getCharData`、`getCharacter`、当前角色名称与 ID；
- 事件：`eventOn`、`eventOnce`、`eventEmit`、常用 `tavern_events` 与 `iframe_events`；
- Slash：`/send`、`/trigger <正文>`、`/pass`、`/echo`、`/setvar`、`/getvar`；
- 页面运行库：常用 jQuery 风格 DOM API 与 Lodash 数据 API，包括酒馆角色卡常用的 `$(...).load(url)` 外部前端加载行为。

生成模型、音频、扩展安装、任意远程脚本执行以及酒馆专属界面控制尚不属于兼容核心。调用未支持的 Slash 命令会返回明确错误，插件仍保持 `sandbox="allow-scripts"`，不能直接访问 Saraswati 父页面。
