import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Chat, PluginExtension } from "../types";

const CHANNEL = "saraswati.plugin.v1";
const STORAGE_LIMIT = 100 * 1024;

interface PluginRequest {
  channel: typeof CHANNEL;
  type: "request";
  id: string;
  method: string;
  params?: Record<string, unknown>;
}

export function PluginPanel({ plugin, story, onClose }: {
  plugin: PluginExtension;
  story: Chat | null;
  onClose: () => void;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(plugin.frontend?.height ?? 620);
  const [fault, setFault] = useState("");
  const permissions = useMemo(() => new Set(plugin.frontend?.permissions ?? []), [plugin.frontend]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    async function onMessage(event: MessageEvent) {
      if (event.source !== frameRef.current?.contentWindow || !isPluginRequest(event.data)) return;
      const request = event.data;
      try {
        const result = await execute(request.method, request.params ?? {});
        respond(request.id, { ok: true, result });
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : "插件请求失败";
        setFault(message);
        respond(request.id, { ok: false, error: message });
      }
    }

    async function execute(method: string, params: Record<string, unknown>): Promise<unknown> {
      if (method === "host.getContext") {
        requirePermission("context.read");
        return { plugin: { id: plugin.id, name: plugin.name, version: plugin.version }, story };
      }
      if (method === "chat.listMessages") {
        requirePermission("chat.read");
        return api.messages(requireStory());
      }
      if (method === "worldbook.list") {
        requirePermission("worldbook.read");
        return api.worldBook(requireStory());
      }
      if (method === "storage.get") {
        requirePermission("storage");
        const key = safeStorageKey(params.key);
        const value = localStorage.getItem(storageKey(plugin.id, key));
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
      if (method === "ui.setHeight") {
        const value = Number(params.height);
        if (!Number.isFinite(value)) throw new Error("无效的界面高度");
        setHeight(Math.max(320, Math.min(value, 900)));
        return true;
      }
      throw new Error(`宿主不支持插件方法：${method}`);
    }

    function requirePermission(permission: string) {
      if (!permissions.has(permission as never)) throw new Error(`插件未获得权限：${permission}`);
    }

    function requireStory() {
      if (!story?.id) throw new Error("请先为插件选择一个故事");
      return story.id;
    }

    function respond(id: string, payload: Record<string, unknown>) {
      frameRef.current?.contentWindow?.postMessage({ channel: CHANNEL, type: "response", id, ...payload }, "*");
    }

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [permissions, plugin.id, plugin.name, plugin.version, story]);

  if (!plugin.frontend) return null;
  const src = api.pluginFrontendUrl(plugin.id, plugin.frontend.entry);

  function announceReady() {
    setFault("");
    frameRef.current?.contentWindow?.postMessage({
      channel: CHANNEL,
      type: "event",
      event: "host.ready",
      payload: {
        protocolVersion: 1,
        pluginId: plugin.id,
        permissions: plugin.frontend?.permissions ?? [],
        storyAvailable: Boolean(story),
      },
    }, "*");
  }

  return <div className="plugin-panel-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="plugin-panel" role="dialog" aria-modal="true" aria-labelledby="plugin-panel-title">
      <header>
        <div><small>沙箱插件</small><h3 id="plugin-panel-title">{plugin.frontend.title || plugin.name}</h3><p>{story ? `当前故事：${story.title}` : "未选择故事，只能使用不依赖故事的功能"}</p></div>
        <button className="ghost-button" onClick={onClose} aria-label="关闭插件界面">关闭</button>
      </header>
      <div className="plugin-panel-permissions">
        <span>权限</span>{plugin.frontend.permissions.length ? plugin.frontend.permissions.map((item) => <code key={item}>{item}</code>) : <small>无数据权限</small>}
      </div>
      {fault && <p className="plugin-panel-error">{fault}</p>}
      <iframe
        ref={frameRef}
        title={plugin.frontend.title || plugin.name}
        src={src}
        sandbox="allow-scripts"
        style={{ height }}
        onLoad={announceReady}
      />
    </section>
  </div>;
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
