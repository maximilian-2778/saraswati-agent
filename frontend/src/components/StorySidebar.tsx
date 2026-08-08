import { useState } from "react";
import type { FormEvent } from "react";

import type { Chat, CharacterTemplate, PersonaTemplate, WorldBookTemplate } from "../types";

export function StorySidebar(props: {
  chats: Chat[];
  selectedChatId: string | null;
  characterTemplates: CharacterTemplate[];
  worldBookTemplates: WorldBookTemplate[];
  personaTemplates: PersonaTemplate[];
  onSelect: (id: string) => void;
  onCreate: (title: string, characterIds: string[], worldBookIds: string[], personaId: string | null) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");
  const [characterIds, setCharacterIds] = useState<string[]>([]);
  const [worldBookIds, setWorldBookIds] = useState<string[]>([]);
  const [personaId, setPersonaId] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    await props.onCreate(title.trim(), characterIds, worldBookIds, personaId || null);
    setTitle("");
    setCharacterIds([]);
    setWorldBookIds([]);
    setPersonaId("");
    setCreating(false);
  }

  return <aside className="sidebar">
    <div className="brand"><div className="brand-mark">स</div><div><strong>Saraswati</strong><span>角色扮演</span></div></div>
    <button className="new-chat-button" onClick={() => setCreating((value) => !value)}><span>＋</span> 新建故事</button>
    {creating && <form className="create-card" onSubmit={submit}>
      <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="故事名称" autoFocus />
      <label className="field"><span>玩家身份</span><select value={personaId} onChange={(event) => setPersonaId(event.target.value)}><option value="">默认身份</option>{props.personaTemplates.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <TemplateChecklist label="角色（可多选）" items={props.characterTemplates.map((item) => ({ id: item.id, label: item.name }))} selected={characterIds} onSelected={setCharacterIds} />
      <TemplateChecklist label="世界书（可多选）" items={props.worldBookTemplates.map((item) => ({ id: item.id, label: item.title }))} selected={worldBookIds} onSelected={setWorldBookIds} />
      <button className="primary-button">创建</button>
    </form>}
    <p className="section-label">故事</p>
    <nav className="chat-list">{props.chats.map((chat) => <div className="chat-entry" key={chat.id}><button className={chat.id === props.selectedChatId ? "chat-item active" : "chat-item"} onClick={() => { props.onSelect(chat.id); setConfirmDeleteId(null); }}><span className="story-avatar">{chat.title.trim().charAt(0) || "故"}</span><span><strong>{chat.title}</strong><small>{formatDate(chat.updated_at)}</small></span></button><button className={`story-delete${confirmDeleteId === chat.id ? " confirming" : ""}`} aria-label={`删除故事 ${chat.title}`} title={confirmDeleteId === chat.id ? "再次点击确认删除" : "删除故事"} onClick={() => { if (confirmDeleteId === chat.id) { void props.onDelete(chat.id); setConfirmDeleteId(null); } else setConfirmDeleteId(chat.id); }}>{confirmDeleteId === chat.id ? "确认" : "×"}</button></div>)}</nav>
  </aside>;
}

function TemplateChecklist(props: { label: string; items: { id: string; label: string }[]; selected: string[]; onSelected: (ids: string[]) => void }) {
  return <fieldset className="template-checklist"><legend>{props.label}</legend>{props.items.length === 0 ? <small>还没有可选内容</small> : props.items.map((item) => <label key={item.id}><input type="checkbox" checked={props.selected.includes(item.id)} onChange={(event) => props.onSelected(event.target.checked ? [...props.selected, item.id] : props.selected.filter((id) => id !== item.id))} /><span>{item.label}</span></label>)}</fieldset>;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(new Date(value));
}
