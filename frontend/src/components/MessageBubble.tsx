import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import type { Message, MessageVariant, StoryCharacter } from "../types";
import { Avatar } from "./Avatar";

export interface MessageBubbleProps {
  message: Message;
  character: StoryCharacter | null;
  userAvatar: string;
  variants: MessageVariant[];
  bookmarked: boolean;
  busy: boolean;
  onEdit: (id: string, content: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onBookmark: (id: string) => Promise<void>;
  onRegenerate: (id: string) => Promise<void>;
  onVariant: (id: string, direction: -1 | 1) => Promise<void>;
  onBranch: (id: string) => Promise<void>;
  onCheckpoint: (id: string) => Promise<void>;
}

export function MessageBubble(props: MessageBubbleProps) {
  const { message, character, userAvatar, variants, bookmarked, busy } = props;
  const assistant = message.role === "assistant";
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(message.content);
  useEffect(() => setContent(message.content), [message.content]);
  const selectedVariant = variants.findIndex((item) => item.selected);
  const pending = message.id.startsWith("pending-");

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!content.trim()) return;
    await props.onEdit(message.id, content.trim());
    setEditing(false);
  }

  return <div id={`message-${message.id}`} className={`message-row ${assistant ? "assistant" : "user"}`}>
    <Avatar value={assistant ? character?.avatar ?? "" : userAvatar} fallback={assistant ? (character?.name ?? "S").charAt(0) : "你"} />
    <div className="message-column">
      <div className="message-meta">{assistant ? character?.name ?? "Saraswati" : "你"}<span>{formatTime(message.created_at)}{bookmarked && " · 已收藏"}</span></div>
      {editing
        ? <form className="message-editor" onSubmit={save}><textarea value={content} onChange={(event) => setContent(event.target.value)} rows={5} /><footer><button type="button" onClick={() => setEditing(false)}>取消</button><button>保存修改</button></footer></form>
        : <div className="bubble">{message.content}</div>}
      {!editing && !pending && <div className="message-toolbar">
        {assistant && variants.length > 1 && <span className="variant-switcher">
          <button disabled={busy || selectedVariant <= 0} onClick={() => void props.onVariant(message.id, -1)}>‹</button>
          {selectedVariant + 1}/{variants.length}
          <button disabled={busy || selectedVariant >= variants.length - 1} onClick={() => void props.onVariant(message.id, 1)}>›</button>
        </span>}
        <button disabled={busy} onClick={() => { setContent(message.content); setEditing(true); }}>编辑</button>
        <button onClick={() => void navigator.clipboard.writeText(message.content)}>复制</button>
        <button className={bookmarked ? "active" : ""} onClick={() => void props.onBookmark(message.id)}>{bookmarked ? "取消收藏" : "收藏"}</button>
        {assistant && <button disabled={busy} onClick={() => void props.onRegenerate(message.id)}>重生成</button>}
        <button onClick={() => void props.onCheckpoint(message.id)}>检查点</button>
        <button onClick={() => void props.onBranch(message.id)}>创建分支</button>
        <button className="danger" disabled={busy} onClick={() => void props.onDelete(message.id)}>删除</button>
      </div>}
    </div>
  </div>;
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
