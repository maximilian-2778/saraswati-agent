import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import type { Message, MessageVariant, PluginExtension, StoryCharacter } from "../types";
import { Avatar } from "./Avatar";
import { MessagePluginFrame } from "./MessagePluginFrame";
import { MessageTokenUsage } from "./TokenUsage";
import type { TokenUsage } from "./TokenUsage";

export interface MessageBubbleProps {
  message: Message;
  chatId: string;
  depth: number;
  character: StoryCharacter | null;
  messagePlugins: PluginExtension[];
  userAvatar: string;
  variants: MessageVariant[];
  tokenUsage?: TokenUsage;
  bookmarked: boolean;
  busy: boolean;
  variantEnabled: boolean;
  onEdit: (id: string, content: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onBookmark: (id: string) => Promise<void>;
  onRegenerate: (id: string) => Promise<void>;
  onVariant: (id: string, direction: -1 | 1) => Promise<void>;
  onBranch: (id: string) => Promise<void>;
  onCheckpoint: (id: string) => Promise<void>;
  onPluginSend: (content: string) => Promise<void>;
  onPluginRefresh: () => Promise<void>;
}

export function MessageBubble(props: MessageBubbleProps) {
  const { message, character, userAvatar, variants, bookmarked, busy } = props;
  const assistant = message.role === "assistant";
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(message.content);
  const [pluginRendered, setPluginRendered] = useState(false);
  useEffect(() => setContent(message.content), [message.content]);
  useEffect(() => setPluginRendered(false), [message.content]);
  const selectedVariant = variants.findIndex((item) => item.selected);
  const pending = message.id.startsWith("pending-");
  const messagePlugin = assistant ? props.messagePlugins.find((item) => matchesMessageSurface(item, message.content, character)) : undefined;

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!content.trim()) return;
    await props.onEdit(message.id, content.trim());
    setEditing(false);
  }

  return <div id={`message-${message.id}`} className={`message-row ${assistant ? "assistant" : "user"}`}>
    <Avatar value={assistant ? character?.avatar ?? "" : userAvatar} fallback={assistant ? (character?.name ?? "S").charAt(0) : "你"} />
    <div className="message-column">
      <div className="message-meta">{assistant ? character?.name ?? "Saraswati" : "你"}<span>{formatTime(message.created_at)}{bookmarked && " · 已收藏"}{assistant && props.tokenUsage && <MessageTokenUsage usage={props.tokenUsage} />}</span></div>
      {editing
        ? <form className="message-editor" onSubmit={save}><textarea value={content} onChange={(event) => setContent(event.target.value)} rows={5} /><footer><button type="button" onClick={() => setEditing(false)}>取消</button><button>保存修改</button></footer></form>
        : <>
          <div className={`bubble${pluginRendered ? " plugin-render-source" : ""}`}>{message.content}</div>
          {messagePlugin && <MessagePluginFrame
            key={`${messagePlugin.id}:${message.id}:${message.content}`}
            plugin={messagePlugin}
            chatId={props.chatId}
            message={message}
            character={character}
            depth={props.depth}
            onRendered={setPluginRendered}
            onSend={props.onPluginSend}
            onRefresh={props.onPluginRefresh}
          />}
        </>}
      {!editing && !pending && <div className="message-toolbar">
        {assistant && props.variantEnabled && variants.length > 1 && <span className="variant-switcher">
          <button disabled={busy || selectedVariant <= 0} onClick={() => void props.onVariant(message.id, -1)}>‹</button>
          {selectedVariant + 1}/{variants.length}
          <button disabled={busy || selectedVariant >= variants.length - 1} onClick={() => void props.onVariant(message.id, 1)}>›</button>
        </span>}
        <button disabled={busy} onClick={() => { setContent(message.content); setEditing(true); }}>编辑</button>
        <button onClick={() => void navigator.clipboard.writeText(message.content)}>复制</button>
        <button className={bookmarked ? "active" : ""} onClick={() => void props.onBookmark(message.id)}>{bookmarked ? "取消收藏" : "收藏"}</button>
        {assistant && props.variantEnabled && <button disabled={busy} onClick={() => void props.onRegenerate(message.id)}>重生成</button>}
        <button onClick={() => void props.onCheckpoint(message.id)}>检查点</button>
        <button onClick={() => void props.onBranch(message.id)}>创建分支</button>
        <button className="danger" disabled={busy} onClick={() => void props.onDelete(message.id)}>删除</button>
      </div>}
    </div>
  </div>;
}

function matchesMessageSurface(plugin: PluginExtension, content: string, character: StoryCharacter | null) {
  const frontend = plugin.frontend;
  if (!plugin.enabled || !frontend?.surfaces.includes("message")) return false;
  const source = content.toLowerCase();
  if (frontend.message_patterns.some((item) => source.includes(item.toLowerCase()))) return true;
  const compatibility = character?.compatibility_data as { original_card?: Record<string, unknown> } | undefined;
  const original = compatibility?.original_card as { data?: { extensions?: Record<string, unknown> }; extensions?: Record<string, unknown> } | undefined;
  const extensions = original?.data?.extensions ?? original?.extensions ?? {};
  return frontend.character_extensions.some((name) => Object.hasOwn(extensions, name));
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
