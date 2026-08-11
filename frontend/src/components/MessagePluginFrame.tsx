import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Message, PluginExtension, StoryCharacter } from "../types";

const CHANNEL = "saraswati.plugin.v1";
const STORAGE_LIMIT = 100 * 1024;

interface PluginRequest {
  channel: typeof CHANNEL;
  type: "request";
  id: string;
  method: string;
  params?: Record<string, unknown>;
}

export function MessagePluginFrame({ plugin, chatId, message, character, depth, onRendered, onSend, onRefresh }: {
  plugin: PluginExtension;
  chatId: string;
  message: Message;
  character: StoryCharacter | null;
  depth: number;
  onRendered: (rendered: boolean) => void;
  onSend: (content: string) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(180);
  const [rendered, setRendered] = useState(false);
  const permissions = new Set(plugin.frontend?.permissions ?? []);

  useEffect(() => {
    setRendered(false);
    onRendered(false);
  }, [message.content, onRendered, plugin.id]);

  useEffect(() => {
    async function onMessage(event: MessageEvent) {
      if (event.source !== frameRef.current?.contentWindow || !isPluginRequest(event.data)) return;
      const request = event.data;
      try {
        const result = await execute(request.method, request.params ?? {});
        respond(request.id, { ok: true, result });
      } catch (reason) {
        respond(request.id, { ok: false, error: reason instanceof Error ? reason.message : "插件请求失败" });
      }
    }

    async function execute(method: string, params: Record<string, unknown>): Promise<unknown> {
      if (method === "surface.setRendered") {
        const value = Boolean(params.rendered);
        setRendered(value);
        onRendered(value);
        if (params.height !== undefined) resize(params.height);
        return true;
      }
      if (method === "ui.setHeight") {
        resize(params.height);
        return true;
      }
      if (method === "host.getContext") {
        requirePermission("context.read");
        return { plugin: { id: plugin.id, name: plugin.name, version: plugin.version }, chat_id: chatId, message_id: message.id };
      }
      if (method === "chat.listMessages") {
        requirePermission("chat.read");
        return api.messages(chatId);
      }
      if (method === "chat.send") {
        requirePermission("chat.write");
        const content = String(params.content ?? "").trim();
        if (!content) throw new Error("发送内容不能为空");
        await onSend(content);
        return true;
      }
      if (method === "chat.updateMessage") {
        requirePermission("chat.write");
        const messageId = String(params.messageId ?? "");
        const content = String(params.content ?? "").trim();
        if (!messageId || !content) throw new Error("消息编号和正文不能为空");
        const updated = await api.updateMessage(chatId, messageId, content);
        await onRefresh();
        return updated;
      }
      if (method === "worldbook.list") {
        requirePermission("worldbook.read");
        return api.storyWorldBooks(chatId);
      }
      if (method === "worldbook.update") {
        requirePermission("worldbook.write");
        const id = String(params.id ?? "");
        const patch = params.patch && typeof params.patch === "object" ? params.patch as Record<string, unknown> : {};
        const current = (await api.storyWorldBooks(chatId)).find((item) => item.id === id);
        if (!current) throw new Error("世界书条目不存在");
        return api.updateStoryWorldBook(chatId, id, worldBookPayload({ ...current, ...patch }));
      }
      if (method === "variables.get") {
        requirePermission("storage");
        return readVariables(plugin.id, variableStorageKey(chatId, character?.id ?? null, message.id, params));
      }
      if (method === "variables.set") {
        requirePermission("storage");
        const key = variableStorageKey(chatId, character?.id ?? null, message.id, params);
        writeVariables(plugin.id, key, params.value);
        return true;
      }
      if (method === "variables.getAll") {
        requirePermission("storage");
        const messages = await api.messages(chatId);
        const through = messages.findIndex((item) => item.id === String(params.messageId ?? message.id));
        return Object.assign(
          {},
          readVariables(plugin.id, "vars.global"),
          character ? readVariables(plugin.id, `vars.character.${character.id}`) : {},
          readVariables(plugin.id, `vars.chat.${chatId}`),
          ...messages.slice(0, through < 0 ? messages.length : through + 1).map((item) => readVariables(plugin.id, `vars.message.${item.id}`)),
        );
      }
      if (method === "storage.get") {
        requirePermission("storage");
        const value = localStorage.getItem(storageKey(plugin.id, safeStorageKey(params.key)));
        return value === null ? null : JSON.parse(value);
      }
      if (method === "storage.set") {
        requirePermission("storage");
        const key = safeStorageKey(params.key);
        const value = JSON.stringify(params.value ?? null);
        if (value.length > STORAGE_LIMIT) throw new Error("插件存储单项不能超过 100 KiB");
        localStorage.setItem(storageKey(plugin.id, key), value);
        return true;
      }
      throw new Error(`消息表面不支持插件方法：${method}`);
    }

    function requirePermission(permission: string) {
      if (!permissions.has(permission as never)) throw new Error(`插件未获得权限：${permission}`);
    }

    function resize(value: unknown) {
      const next = Number(value);
      if (!Number.isFinite(next)) throw new Error("无效的界面高度");
      setHeight(Math.max(80, Math.min(next, 1200)));
    }

    function respond(id: string, payload: Record<string, unknown>) {
      frameRef.current?.contentWindow?.postMessage({ channel: CHANNEL, type: "response", id, ...payload }, "*");
    }

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [chatId, character, depth, message, onRefresh, onRendered, onSend, permissions, plugin.id, plugin.name, plugin.version]);

  if (!plugin.frontend) return null;

  function sendMessageContext() {
    frameRef.current?.contentWindow?.postMessage({
      channel: CHANNEL,
      type: "event",
      event: "host.message",
      payload: {
        protocolVersion: 1,
        pluginId: plugin.id,
        chatId,
        message: permissions.has("message.read") ? { ...message, depth } : null,
        character: permissions.has("character.read") ? character : null,
      },
    }, "*");
  }

  return <iframe
    ref={frameRef}
    className={`message-plugin-frame${rendered ? " rendered" : ""}`}
    title={`${plugin.name} · ${message.id}`}
    src={api.pluginFrontendUrl(plugin.id, plugin.frontend.entry)}
    sandbox="allow-scripts"
    style={{ height }}
    onLoad={sendMessageContext}
  />;
}

function isPluginRequest(value: unknown): value is PluginRequest {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<PluginRequest>;
  return item.channel === CHANNEL && item.type === "request" && typeof item.id === "string" && typeof item.method === "string";
}

function safeStorageKey(value: unknown) {
  const key = String(value ?? "").trim();
  if (!/^[a-zA-Z0-9_.-]{1,64}$/.test(key)) throw new Error("插件存储键格式无效");
  return key;
}

function storageKey(pluginId: string, key: string) {
  return `saraswati.plugin.${pluginId}.${key}`;
}

function variableStorageKey(chatId: string, characterId: string | null, messageId: string, params: Record<string, unknown>) {
  const type = String(params.type ?? "chat");
  if (type === "global") return "vars.global";
  if (type === "character") return `vars.character.${characterId ?? "none"}`;
  if (type === "message") return `vars.message.${String(params.messageId ?? messageId)}`;
  return `vars.chat.${chatId}`;
}

function readVariables(pluginId: string, key: string): Record<string, unknown> {
  try {
    const value = localStorage.getItem(storageKey(pluginId, key));
    const parsed = value ? JSON.parse(value) : {};
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch { return {}; }
}

function writeVariables(pluginId: string, key: string, value: unknown) {
  const serialized = JSON.stringify(value ?? {});
  if (serialized.length > STORAGE_LIMIT) throw new Error("变量数据单项不能超过 100 KiB");
  localStorage.setItem(storageKey(pluginId, key), serialized);
}

function worldBookPayload(item: Record<string, unknown>) {
  const keys = ["title", "keywords", "secondary_keywords", "content", "priority", "enabled", "constant", "case_sensitive", "scan_depth", "insertion_position", "group_name", "recursive", "token_budget", "scope", "selective_logic", "probability", "match_whole_words", "prevent_recursion", "depth", "sticky", "cooldown", "delay", "compatibility_data"];
  return Object.fromEntries(keys.map((key) => [key, item[key]]));
}
