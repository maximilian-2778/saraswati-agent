import { useState } from "react";
import type { FormEvent } from "react";

import type { Chat, CharacterTemplate, WorldBookTemplate } from "../types";

export function StorySidebar(props: {
  chats: Chat[];
  selectedChatId: string | null;
  characterTemplates: CharacterTemplate[];
  worldBookTemplates: WorldBookTemplate[];
  onSelect: (id: string) => void;
  onCreate: (title: string, characterIds: string[], worldBookIds: string[]) => Promise<void>;
}) {
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [characterIds, setCharacterIds] = useState<string[]>([]);
  const [worldBookIds, setWorldBookIds] = useState<string[]>([]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    await props.onCreate(title.trim(), characterIds, worldBookIds);
    setTitle("");
    setCharacterIds([]);
    setWorldBookIds([]);
    setCreating(false);
  }

  return <aside className="sidebar">
    <div className="brand"><div className="brand-mark">स</div><div><strong>Saraswati</strong><span>角色扮演</span></div></div>
    <button className="new-chat-button" onClick={() => setCreating((value) => !value)}><span>＋</span> 新建故事</button>
    {creating && <form className="create-card" onSubmit={submit}>
      <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="故事名称" autoFocus />
      <TemplateChecklist label="角色（可多选）" items={props.characterTemplates.map((item) => ({ id: item.id, label: item.name }))} selected={characterIds} onSelected={setCharacterIds} />
      <TemplateChecklist label="世界书（可多选）" items={props.worldBookTemplates.map((item) => ({ id: item.id, label: item.title }))} selected={worldBookIds} onSelected={setWorldBookIds} />
      <small className="snapshot-hint">加入故事后可以单独修改，不会改动角色库和世界书库。</small>
      <button className="primary-button">创建</button>
    </form>}
    <p className="section-label">故事</p>
    <nav className="chat-list">{props.chats.map((chat) => <button key={chat.id} className={chat.id === props.selectedChatId ? "chat-item active" : "chat-item"} onClick={() => props.onSelect(chat.id)}><span className="book-icon">◈</span><span><strong>{chat.title}</strong><small>{formatDate(chat.updated_at)}</small></span></button>)}</nav>
    <div className="sidebar-note">重要数值修改前会请你确认<br />旧剧情可以随时查看来源</div>
  </aside>;
}

function TemplateChecklist(props: { label: string; items: { id: string; label: string }[]; selected: string[]; onSelected: (ids: string[]) => void }) {
  return <fieldset className="template-checklist"><legend>{props.label}</legend>{props.items.length === 0 ? <small>还没有可选内容</small> : props.items.map((item) => <label key={item.id}><input type="checkbox" checked={props.selected.includes(item.id)} onChange={(event) => props.onSelected(event.target.checked ? [...props.selected, item.id] : props.selected.filter((id) => id !== item.id))} /><span>{item.label}</span></label>)}</fieldset>;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(new Date(value));
}
