import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import type { Chat, CharacterTemplate, PersonaTemplate, WorldBookTemplate } from "../types";
import { ArchiveDiagram } from "./ArchiveDiagram";

export function StorySidebar(props: {
  chats: Chat[];
  selectedChatId: string | null;
  generatingChatId: string | null;
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
    <ArchiveDiagram />
    <div className="brand"><div className="brand-mark">स</div><div><strong>Saraswati</strong></div></div>
    <button className="new-chat-button" onClick={() => setCreating((value) => !value)}><span>＋</span> 新建故事</button>
    {creating && <form className="create-card" onSubmit={submit}>
      <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="故事名称" autoFocus />
      <PersonaPicker items={props.personaTemplates} value={personaId} onChange={setPersonaId} />
      <TemplateChecklist label="角色（可多选）" items={props.characterTemplates.map((item) => ({ id: item.id, label: item.name }))} selected={characterIds} onSelected={setCharacterIds} />
      <TemplateChecklist label="世界书（可多选）" items={props.worldBookTemplates.map((item) => ({ id: item.id, label: item.title }))} selected={worldBookIds} onSelected={setWorldBookIds} />
      <button className="primary-button">创建</button>
    </form>}
    <p className="section-label">故事</p>
    <nav className="chat-list">{props.chats.map((chat, index) => <div className="chat-entry" key={chat.id}><button className={chat.id === props.selectedChatId ? "chat-item active" : "chat-item"} onClick={() => { props.onSelect(chat.id); setConfirmDeleteId(null); }}><span className="story-avatar" aria-hidden="true"><small>卷</small><b>{String(index + 1).padStart(2, "0")}</b></span><span><strong>{chat.title}</strong><small>{formatDate(chat.updated_at)}</small>{chat.id === props.generatingChatId && <em className="story-generation-status"><i aria-hidden="true" />生成中</em>}</span></button><button className={`story-delete${confirmDeleteId === chat.id ? " confirming" : ""}`} aria-label={`删除故事 ${chat.title}`} title={confirmDeleteId === chat.id ? "再次点击确认删除" : "删除故事"} onClick={() => { if (confirmDeleteId === chat.id) { void props.onDelete(chat.id); setConfirmDeleteId(null); } else setConfirmDeleteId(chat.id); }}>{confirmDeleteId === chat.id ? "确认" : "×"}</button></div>)}</nav>
  </aside>;
}

function PersonaPicker(props: { items: PersonaTemplate[]; value: string; onChange: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const selected = props.items.find((item) => item.id === props.value);

  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    window.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", escape);
    };
  }, [open]);

  function choose(id: string) {
    props.onChange(id);
    setOpen(false);
  }

  return <div className={`persona-picker${open ? " open" : ""}`} ref={root}>
    <span className="persona-picker-label">主控人物</span>
    <button type="button" className={`persona-picker-trigger${selected ? " has-persona" : ""}`} aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
      {selected && <PersonaPortrait item={selected} />}
      <span className="persona-picker-copy">
        <strong>{selected?.name ?? "暂不设置"}</strong>
        <small>{selected ? selected.identity || selected.personality || "主控人物设定" : "稍后也可以在故事中绑定"}</small>
      </span>
      <i aria-hidden="true" />
    </button>
    {open && <div className="persona-picker-menu" role="listbox" aria-label="选择主控人物">
      <button type="button" role="option" aria-selected={!props.value} className={`no-persona${!props.value ? " selected" : ""}`} onClick={() => choose("")}>
        <span><strong>暂不设置</strong><small>创建后再选择主控人物</small></span>
        <b aria-hidden="true">{!props.value ? "✓" : ""}</b>
      </button>
      {props.items.map((item) => <button type="button" role="option" aria-selected={item.id === props.value} className={item.id === props.value ? "selected" : ""} key={item.id} onClick={() => choose(item.id)}>
        <PersonaPortrait item={item} />
        <span><strong>{item.name}</strong><small>{item.identity || item.personality || "主控人物设定"}</small></span>
        <b aria-hidden="true">{item.id === props.value ? "✓" : ""}</b>
      </button>)}
      {props.items.length === 0 && <p>还没有主控人物模板</p>}
    </div>}
  </div>;
}

function PersonaPortrait({ item }: { item?: PersonaTemplate }) {
  return <span className={`persona-portrait${item?.avatar ? " has-image" : ""}`} aria-hidden="true">
    <span>{item?.name?.trim().slice(0, 1) || "◇"}</span>
    {item?.avatar && <img src={item.avatar} alt="" onError={(event) => { event.currentTarget.style.display = "none"; }} />}
  </span>;
}

function TemplateChecklist(props: { label: string; items: { id: string; label: string }[]; selected: string[]; onSelected: (ids: string[]) => void }) {
  return <fieldset className="template-checklist"><legend>{props.label}</legend>{props.items.length === 0 ? <small>还没有可选内容</small> : props.items.map((item) => <label key={item.id}><input type="checkbox" checked={props.selected.includes(item.id)} onChange={(event) => props.onSelected(event.target.checked ? [...props.selected, item.id] : props.selected.filter((id) => id !== item.id))} /><span>{item.label}</span></label>)}</fieldset>;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(new Date(value));
}
