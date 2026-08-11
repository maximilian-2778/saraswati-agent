import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { api } from "../api";
import { Avatar, AvatarPicker, fileToDataUrl } from "./Avatar";
import { HelpTip } from "./HelpTip";
import { ClassicalIcon } from "./ClassicalIcon";
import { PresetManager } from "./PresetManager";
import { ExtensionSettings } from "./ExtensionSettings";
import { EMPTY_WORLD_ENTRY, worldEntryToDraft } from "../utils/worldBookDraft";
import type { WorldEntryDraft } from "../utils/worldBookDraft";
import type {
  Chat, CharacterTemplate, PersonaTemplate, StoryCharacter, StoryPersona,
  StoryWorldBook, WorldBookTemplate,
} from "../types";

export type LibraryKind = "characters" | "personas" | "world" | "presets" | "extensions";

export function GlobalNav({ onOpen }: { onOpen: (page: LibraryKind) => void }) {
  return (
    <nav className="global-nav" aria-label="主导航">
      <button onClick={() => onOpen("characters")}><ClassicalIcon name="character" /><span>角色</span></button>
      <button onClick={() => onOpen("personas")}><ClassicalIcon name="persona" /><span>主控人物</span></button>
      <button onClick={() => onOpen("world")}><ClassicalIcon name="world" /><span>世界书</span></button>
      <button onClick={() => onOpen("presets")}><ClassicalIcon name="preset" /><span>预设</span></button>
      <button onClick={() => onOpen("extensions")}><ClassicalIcon name="extension" /><span>扩展</span></button>
    </nav>
  );
}

export function LibraryWorkspace(props: {
  page: LibraryKind;
  onClose: () => void;
  selectedChat: Chat | null;
  characterTemplates: CharacterTemplate[];
  worldBookTemplates: WorldBookTemplate[];
  personaTemplates: PersonaTemplate[];
  storyPersona: StoryPersona | null;
  onCharacters: (items: CharacterTemplate[]) => void;
  onStoryCharacters: (items: StoryCharacter[]) => void;
  onWorldBooks: (items: WorldBookTemplate[]) => void;
  onPersonas: (items: PersonaTemplate[]) => void;
  onStoryPersona: (item: StoryPersona | null) => void;
  onChatChanged: () => Promise<void>;
  onPresetActivated: () => Promise<void>;
  onError: (reason: unknown) => void;
  error: string | null;
}) {
  const [presetNotice, setPresetNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const title = props.page === "characters" ? "角色" : props.page === "personas" ? "主控人物" : props.page === "world" ? "世界书" : props.page === "presets" ? "写作预设" : "扩展";
  const specializedPage = props.page === "presets" || props.page === "extensions";
  return (
    <div className="library-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) props.onClose(); }}>
    <main className={`library-workspace${specializedPage ? " preset-library-workspace" : ""}${props.page === "extensions" ? " extension-library-workspace" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
      <header className="topbar library-topbar">
        <div>
          <p className="eyebrow">{props.page === "presets" ? "写作配置" : props.page === "extensions" ? "EXTENSION LIBRARY" : "故事设定"}</p>
          <div className="library-title-row">
            {props.page === "extensions" && <ClassicalIcon name="extension" />}
            <h1>{title}</h1>
            {props.page === "extensions" && <HelpTip text="在这里管理可复用的技能与外部服务。技能保存工作方法和参考资料，服务则负责连接其他程序。" />}
          </div>
        </div>
        <button className="icon-button" onClick={props.onClose} aria-label="关闭">×</button>
      </header>
      {props.error && <div className="error-banner">{props.error}</div>}
      {presetNotice && <div className={`library-notice ${presetNotice.kind}`}>{presetNotice.text}</div>}
      {props.page === "characters" ? (
        <CharacterLibrary
          selectedChat={props.selectedChat}
          templates={props.characterTemplates}
          onTemplates={props.onCharacters}
          onStoryItems={props.onStoryCharacters}
          onChatChanged={props.onChatChanged}
          onError={props.onError}
          worldBooks={props.worldBookTemplates}
        />
      ) : props.page === "personas" ? (
        <PersonaLibrary
          selectedChat={props.selectedChat}
          templates={props.personaTemplates}
          storyPersona={props.storyPersona}
          worldBooks={props.worldBookTemplates}
          onTemplates={props.onPersonas}
          onStoryPersona={props.onStoryPersona}
          onError={props.onError}
        />
      ) : props.page === "world" ? (
        <WorldLibrary
          selectedChat={props.selectedChat}
          templates={props.worldBookTemplates}
          onTemplates={props.onWorldBooks}
          onError={props.onError}
        />
      ) : props.page === "presets" ? (
        <div className="library-content preset-library-content">
          <PresetManager
            onActivated={props.onPresetActivated}
            onNotice={(kind, text) => setPresetNotice({ kind, text })}
          />
        </div>
      ) : (
        <div className="library-content extension-library-content">
          <ExtensionSettings selectedChatId={props.selectedChat?.id ?? null} />
        </div>
      )}
    </main>
    </div>
  );
}

const EMPTY_PERSONA = { name: "", avatar: "", identity: "", personality: "", appearance: "", speaking_style: "", world_book_ids: [] as string[] };

function PersonaLibrary(props: {
  selectedChat: Chat | null;
  templates: PersonaTemplate[];
  storyPersona: StoryPersona | null;
  worldBooks: WorldBookTemplate[];
  onTemplates: (items: PersonaTemplate[]) => void;
  onStoryPersona: (item: StoryPersona | null) => void;
  onError: (reason: unknown) => void;
}) {
  const [editing, setEditing] = useState<{ scope: "template" | "story"; id: string | null } | null>(null);
  const [draft, setDraft] = useState(EMPTY_PERSONA);
  function edit(scope: "template" | "story", item?: PersonaTemplate | StoryPersona) {
    setEditing({ scope, id: item?.id ?? null });
    setDraft(item ? { name: item.name, avatar: item.avatar, identity: item.identity, personality: item.personality, appearance: item.appearance, speaking_style: item.speaking_style, world_book_ids: item.world_book_ids } : EMPTY_PERSONA);
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editing || !draft.name.trim()) return;
    try {
      if (editing.scope === "template") {
        if (editing.id) await api.updatePersonaTemplate(editing.id, draft);
        else await api.createPersonaTemplate(draft);
        props.onTemplates(await api.personaTemplates());
      } else if (props.selectedChat) {
        props.onStoryPersona(await api.updateStoryPersona(props.selectedChat.id, draft));
      }
      setEditing(null);
    } catch (reason) { props.onError(reason); }
  }
  async function attach(id: string) {
    if (!props.selectedChat) return;
    try { props.onStoryPersona(await api.attachPersona(props.selectedChat.id, id)); }
    catch (reason) { props.onError(reason); }
  }
  async function remove(id: string) {
    try { await api.deletePersonaTemplate(id); props.onTemplates(await api.personaTemplates()); }
    catch (reason) { props.onError(reason); }
  }
  async function removeFromStory() {
    if (!props.selectedChat) return;
    try {
      await api.deleteStoryPersona(props.selectedChat.id);
      props.onStoryPersona(null);
      setEditing(null);
    } catch (reason) { props.onError(reason); }
  }
  const set = <K extends keyof typeof EMPTY_PERSONA>(key: K, value: (typeof EMPTY_PERSONA)[K]) => setDraft({ ...draft, [key]: value });
  return <div className="library-content">
    <LibraryColumn title="主控人物库" note="选择你在故事中扮演的人物。" action="＋ 新建主控人物" onAction={() => edit("template")}>
      {props.templates.length === 0 ? <p className="muted">还没有主控人物。</p> : props.templates.map((item) => <LibraryCard key={item.id} title={item.name} detail={item.identity || item.personality || "暂无描述"} badge="模板" avatar={item.avatar}>
        <button onClick={() => void attach(item.id)} disabled={!props.selectedChat}>用于当前故事</button><button onClick={() => edit("template", item)}>编辑</button><button className="delete-button" onClick={() => void remove(item.id)}>删除</button>
      </LibraryCard>)}
    </LibraryColumn>
    <LibraryColumn title={`当前故事的主控人物${props.selectedChat ? ` · ${props.selectedChat.title}` : ""}`} note="这里的修改只影响当前故事。">
      {!props.selectedChat ? <p className="muted">请先选择故事。</p> : !props.storyPersona ? <p className="muted">当前故事没有设置主控人物。</p> : <LibraryCard title={props.storyPersona.name} detail={props.storyPersona.identity || props.storyPersona.personality || "暂无描述"} badge="故事快照" avatar={props.storyPersona.avatar}><button onClick={() => edit("story", props.storyPersona!)}>编辑</button><button className="delete-button" onClick={() => void removeFromStory()}>从故事移除</button></LibraryCard>}
    </LibraryColumn>
    {editing && <form className="library-editor" onSubmit={save}>
      <div className="action-heading"><h3>{editing.scope === "template" ? "编辑主控人物" : "编辑故事中的主控人物"}</h3><button type="button" onClick={() => setEditing(null)}>关闭</button></div>
      <AvatarPicker value={draft.avatar} fallback={draft.name.charAt(0) || "你"} onChange={(value) => set("avatar", value)} />
      <input value={draft.name} onChange={(event) => set("name", event.target.value)} placeholder="名称" autoFocus />
      <textarea value={draft.identity} onChange={(event) => set("identity", event.target.value)} placeholder="身份描述" rows={3} />
      <textarea value={draft.personality} onChange={(event) => set("personality", event.target.value)} placeholder="性格" rows={3} />
      <textarea value={draft.appearance} onChange={(event) => set("appearance", event.target.value)} placeholder="外貌" rows={2} />
      <textarea value={draft.speaking_style} onChange={(event) => set("speaking_style", event.target.value)} placeholder="说话方式" rows={2} />
      <fieldset className="template-checklist"><legend>专属世界书</legend>{props.worldBooks.map((item) => <label key={item.id}><input type="checkbox" checked={draft.world_book_ids.includes(item.id)} onChange={(event) => set("world_book_ids", event.target.checked ? [...draft.world_book_ids, item.id] : draft.world_book_ids.filter((id) => id !== item.id))} />{item.title}</label>)}</fieldset>
      <button className="primary-button">保存</button>
    </form>}
  </div>;
}

const EMPTY_CHARACTER = { name: "", identity: "", personality: "", speaking_style: "", scenario: "", avatar: "", appearance: "", first_message: "", alternate_greetings: [] as string[], example_dialogue: "", tags: [] as string[], creator_notes: "", system_prompt: "", post_history_instructions: "", creator: "", character_version: "", favorite: false, world_book_ids: [] as string[], compatibility_data: {} as Record<string, unknown> };

function CharacterLibrary(props: {
  selectedChat: Chat | null;
  templates: CharacterTemplate[];
  onTemplates: (items: CharacterTemplate[]) => void;
  onStoryItems: (items: StoryCharacter[]) => void;
  onChatChanged: () => Promise<void>;
  onError: (reason: unknown) => void;
  worldBooks: WorldBookTemplate[];
}) {
  const [storyItems, setStoryItems] = useState<StoryCharacter[]>([]);
  const [editing, setEditing] = useState<{ scope: "template" | "story"; id: string | null } | null>(null);
  const [draft, setDraft] = useState(EMPTY_CHARACTER);
  const [search, setSearch] = useState("");

  async function refreshStory() {
    const items = props.selectedChat ? await api.storyCharacters(props.selectedChat.id) : [];
    setStoryItems(items);
    props.onStoryItems(items);
  }
  useEffect(() => { void refreshStory().catch(props.onError); }, [props.selectedChat?.id]);

  function edit(scope: "template" | "story", item?: CharacterTemplate | StoryCharacter) {
    setEditing({ scope, id: item?.id ?? null });
    setDraft(item ? {
      name: item.name, identity: item.identity, personality: item.personality,
      speaking_style: item.speaking_style, scenario: item.scenario, avatar: item.avatar,
      appearance: item.appearance, first_message: item.first_message,
      alternate_greetings: item.alternate_greetings, example_dialogue: item.example_dialogue,
      tags: item.tags, creator_notes: item.creator_notes, system_prompt: item.system_prompt,
      post_history_instructions: item.post_history_instructions, creator: item.creator,
      character_version: item.character_version, favorite: item.favorite,
      world_book_ids: item.world_book_ids, compatibility_data: item.compatibility_data,
    } : EMPTY_CHARACTER);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editing || !draft.name.trim()) return;
    try {
      if (editing.scope === "template") {
        if (editing.id) await api.updateCharacterTemplate(editing.id, draft);
        else await api.createCharacterTemplate(draft);
        props.onTemplates(await api.characterTemplates());
      } else if (props.selectedChat && editing.id) {
        await api.updateStoryCharacter(props.selectedChat.id, editing.id, draft);
        await refreshStory();
      }
      setEditing(null);
    } catch (reason) { props.onError(reason); }
  }

  async function attach(id: string) {
    if (!props.selectedChat) return;
    try { await api.attachCharacter(props.selectedChat.id, id); await refreshStory(); await props.onChatChanged(); }
    catch (reason) { props.onError(reason); }
  }

  async function remove(scope: "template" | "story", id: string) {
    try {
      if (scope === "template") {
        await api.deleteCharacterTemplate(id);
        props.onTemplates(await api.characterTemplates());
      } else if (props.selectedChat) {
        await api.deleteStoryCharacter(props.selectedChat.id, id);
        await refreshStory();
      }
    } catch (reason) { props.onError(reason); }
  }

  async function duplicate(id: string) {
    try { await api.duplicateCharacterTemplate(id); props.onTemplates(await api.characterTemplates()); }
    catch (reason) { props.onError(reason); }
  }

  async function importCard(file: File | undefined) {
    if (!file) return;
    let embedded: WorldBookTemplate[] = [];
    try {
      const raw = file.name.toLowerCase().endsWith(".png") ? await readPngCharacterCard(file) : JSON.parse(await file.text());
      const data = raw.data ?? raw;
      embedded = data.character_book ? await importWorldBookData(data.character_book, `${data.name || "角色"} · 世界书`) : [];
      const created = await api.createCharacterTemplate({ ...EMPTY_CHARACTER, name: data.name || "导入角色", avatar: file.name.toLowerCase().endsWith(".png") ? await fileToDataUrl(file) : "", identity: data.description || data.identity || "", personality: data.personality || "", scenario: data.scenario || "", first_message: data.first_mes || data.first_message || "", alternate_greetings: data.alternate_greetings || [], example_dialogue: data.mes_example || data.example_dialogue || "", tags: data.tags || [], creator_notes: data.creator_notes || "", system_prompt: data.system_prompt || "", post_history_instructions: data.post_history_instructions || "", creator: data.creator || "", character_version: data.character_version || "", world_book_ids: embedded.map((item) => item.id), compatibility_data: { source_format: raw.spec || "chara_card_v1", original_card: raw } });
      props.onTemplates([created, ...props.templates]);
    } catch (reason) {
      if (embedded.length) await rollbackWorldBookTemplates(embedded);
      props.onError(reason);
    }
  }

  const visibleTemplates = props.templates
    .filter((item) => `${item.name} ${item.tags.join(" ")} ${item.identity}`.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => Number(b.favorite) - Number(a.favorite));

  return (
    <div className="library-content">
      <LibraryColumn title="角色库" note="这里的角色可以添加到多个故事。" action="＋ 新建角色" onAction={() => edit("template")}>
        <div className="library-tools"><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索角色" /><label className="file-button">导入角色卡<input type="file" accept=".json,.png,application/json,image/png" onChange={(event) => void importCard(event.target.files?.[0])} /></label></div>
        {visibleTemplates.length === 0 ? <p className="muted">没有找到角色。</p> : visibleTemplates.map((item) => (
          <LibraryCard key={item.id} title={`${item.favorite ? "★ " : ""}${item.name}`} detail={item.identity || item.personality || "暂无补充设定"} badge={item.tags.length ? item.tags.join(" · ") : "模板"} avatar={item.avatar}>
            <button onClick={() => attach(item.id)} disabled={!props.selectedChat}>添加到故事</button>
            <button onClick={() => edit("template", item)}>编辑</button>
            <button onClick={() => void duplicate(item.id)}>复制</button>
            <button onClick={() => downloadCharacterCard(item)}>导出 JSON</button>
            {item.avatar.startsWith("data:image/png") && <button onClick={() => downloadPngCharacterCard(item)}>导出 PNG</button>}
            <button className="delete-button" onClick={() => void remove("template", item.id)}>删除</button>
          </LibraryCard>
        ))}
      </LibraryColumn>
      <LibraryColumn title={`当前故事中的角色${props.selectedChat ? ` · ${props.selectedChat.title}` : ""}`} note="这里的修改只影响当前故事。">
        {!props.selectedChat ? <p className="muted">请先从左侧选择一个故事。</p> : storyItems.length === 0 ? <p className="muted">这个故事尚未绑定角色。</p> : storyItems.map((item) => (
          <LibraryCard key={item.id} title={item.name} detail={item.identity || item.personality || "暂无补充设定"} badge={item.source_template_id ? "当前故事" : "已有角色"} avatar={item.avatar}>
            <button onClick={() => edit("story", item)}>编辑</button>
            <button className="delete-button" onClick={() => void remove("story", item.id)}>移除</button>
          </LibraryCard>
        ))}
      </LibraryColumn>
      {editing && <CharacterEditor draft={draft} onDraft={setDraft} scope={editing.scope} worldBooks={props.worldBooks} onSubmit={save} onCancel={() => setEditing(null)} />}
    </div>
  );
}

function CharacterEditor(props: {
  draft: typeof EMPTY_CHARACTER;
  onDraft: (value: typeof EMPTY_CHARACTER) => void;
  scope: "template" | "story";
  worldBooks: WorldBookTemplate[];
  onSubmit: (event: FormEvent) => void;
  onCancel: () => void;
}) {
  const set = <K extends keyof typeof EMPTY_CHARACTER>(key: K, value: (typeof EMPTY_CHARACTER)[K]) => props.onDraft({ ...props.draft, [key]: value });
  return (
    <form className="library-editor" onSubmit={props.onSubmit}>
      <div className="action-heading"><h3>{props.scope === "template" ? "编辑角色" : "编辑当前故事中的角色"}</h3><button type="button" onClick={props.onCancel}>关闭</button></div>
      <AvatarPicker value={props.draft.avatar} fallback={props.draft.name.charAt(0) || "角"} onChange={(value) => set("avatar", value)} />
      <input value={props.draft.name} onChange={(e) => set("name", e.target.value)} placeholder="角色名" autoFocus />
      <textarea value={props.draft.identity} onChange={(e) => set("identity", e.target.value)} placeholder="身份与背景" rows={3} />
      <textarea value={props.draft.personality} onChange={(e) => set("personality", e.target.value)} placeholder="性格" rows={3} />
      <textarea value={props.draft.appearance} onChange={(e) => set("appearance", e.target.value)} placeholder="外貌" rows={2} />
      <textarea value={props.draft.speaking_style} onChange={(e) => set("speaking_style", e.target.value)} placeholder="说话风格" rows={2} />
      <textarea value={props.draft.scenario} onChange={(e) => set("scenario", e.target.value)} placeholder="当前情境" rows={3} />
      <textarea value={props.draft.first_message} onChange={(e) => set("first_message", e.target.value)} placeholder="开场白" rows={4} />
      <textarea value={props.draft.alternate_greetings.join("\n")} onChange={(e) => set("alternate_greetings", e.target.value.split("\n").filter(Boolean))} placeholder="备选开场白，每行一条" rows={4} />
      <textarea value={props.draft.example_dialogue} onChange={(e) => set("example_dialogue", e.target.value)} placeholder="示例对话" rows={4} />
      <input value={props.draft.tags.join("，")} onChange={(e) => set("tags", e.target.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean))} placeholder="标签，用逗号分隔" />
      <details className="advanced-settings"><summary>更多设定</summary><div className="world-form-row"><label><span>作者 <HelpTip text="角色卡原作者或整理者；导入角色卡时会自动读取。" /></span><input value={props.draft.creator} onChange={(e) => set("creator", e.target.value)} placeholder="作者" /></label><label><span>角色版本 <HelpTip text="用于区分同一角色卡的不同修订版本，不会影响角色扮演内容。" /></span><input value={props.draft.character_version} onChange={(e) => set("character_version", e.target.value)} placeholder="例如 1.0" /></label></div><textarea value={props.draft.creator_notes} onChange={(e) => set("creator_notes", e.target.value)} placeholder="创作者备注" rows={3} /><textarea value={props.draft.system_prompt} onChange={(e) => set("system_prompt", e.target.value)} placeholder="角色专属系统提示词" rows={4} /><label className="field-with-help"><span>历史记录后的补充指令 <HelpTip text="放在对话历史之后的角色专属指令，通常比普通角色描述更接近本轮生成。" /></span><textarea value={props.draft.post_history_instructions} onChange={(e) => set("post_history_instructions", e.target.value)} placeholder="可留空" rows={4} /></label><fieldset className="template-checklist"><legend>角色专属世界书</legend>{props.worldBooks.map((item) => <label key={item.id}><input type="checkbox" checked={props.draft.world_book_ids.includes(item.id)} onChange={(event) => set("world_book_ids", event.target.checked ? [...props.draft.world_book_ids, item.id] : props.draft.world_book_ids.filter((id) => id !== item.id))} />{item.title}</label>)}</fieldset></details>
      <label className="inline-check"><input type="checkbox" checked={props.draft.favorite} onChange={(event) => set("favorite", event.target.checked)} />收藏角色</label>
      <button className="primary-button">保存</button>
    </form>
  );
}

function WorldLibrary(props: {
  selectedChat: Chat | null;
  templates: WorldBookTemplate[];
  onTemplates: (items: WorldBookTemplate[]) => void;
  onError: (reason: unknown) => void;
}) {
  const [storyItems, setStoryItems] = useState<StoryWorldBook[]>([]);
  const [selectedTemplates, setSelectedTemplates] = useState<string[]>([]);
  const [selectedStoryItems, setSelectedStoryItems] = useState<string[]>([]);
  const [batchBusy, setBatchBusy] = useState(false);
  const [editing, setEditing] = useState<{ scope: "template" | "story"; id: string | null } | null>(null);
  const [draft, setDraft] = useState<WorldEntryDraft>(EMPTY_WORLD_ENTRY);
  async function refreshStory() { setStoryItems(props.selectedChat ? await api.storyWorldBooks(props.selectedChat.id) : []); }
  useEffect(() => {
    setSelectedStoryItems([]);
    void refreshStory().catch(props.onError);
  }, [props.selectedChat?.id]);
  useEffect(() => {
    const available = new Set(props.templates.map((item) => item.id));
    setSelectedTemplates((before) => before.filter((id) => available.has(id)));
  }, [props.templates]);
  useEffect(() => {
    const available = new Set(storyItems.map((item) => item.id));
    setSelectedStoryItems((before) => before.filter((id) => available.has(id)));
  }, [storyItems]);

  function edit(scope: "template" | "story", item?: WorldBookTemplate | StoryWorldBook) {
    setEditing({ scope, id: item?.id ?? null });
    setDraft(item ? worldEntryToDraft(item) : EMPTY_WORLD_ENTRY);
  }
  const payload = () => ({
    title: draft.title.trim(), content: draft.content.trim(), priority: draft.priority, enabled: draft.enabled,
    keywords: draft.keywords.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean),
    secondary_keywords: draft.secondaryKeywords.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean),
    constant: draft.constant, case_sensitive: draft.caseSensitive, scan_depth: draft.scanDepth,
    insertion_position: draft.insertionPosition, group_name: draft.groupName,
    recursive: draft.recursive, scope: draft.scope,
    selective_logic: draft.selectiveLogic, probability: draft.probability,
    match_whole_words: draft.matchWholeWords, prevent_recursion: draft.preventRecursion,
    depth: draft.depth, sticky: draft.sticky, cooldown: draft.cooldown, delay: draft.delay,
    compatibility_data: draft.compatibilityData,
  });

  async function importBook(file: File | undefined) {
    if (!file) return;
    try {
      const created = await importWorldBookData(JSON.parse(await file.text()), file.name.replace(/\.json$/i, ""));
      props.onTemplates(sortWorldBooks([...created, ...props.templates]));
    } catch (reason) { props.onError(reason); }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editing || !draft.title.trim() || !draft.content.trim()) return;
    try {
      if (editing.scope === "template") {
        if (editing.id) await api.updateWorldBookTemplate(editing.id, payload());
        else await api.createWorldBookTemplate(payload());
        props.onTemplates(await api.worldBookTemplates());
      } else if (props.selectedChat && editing.id) {
        await api.updateStoryWorldBook(props.selectedChat.id, editing.id, payload());
        await refreshStory();
      }
      setEditing(null);
    } catch (reason) { props.onError(reason); }
  }
  async function attach(id: string) {
    if (!props.selectedChat) return;
    try {
      const created = await api.attachWorldBook(props.selectedChat.id, id);
      setStoryItems((before) => sortWorldBooks([created, ...before]));
    }
    catch (reason) { props.onError(reason); }
  }
  async function batchAttach() {
    if (!props.selectedChat || !selectedTemplates.length) return;
    const attachedIds = new Set(storyItems.map((item) => item.source_template_id).filter(Boolean));
    const pendingIds = selectedTemplates.filter((id) => !attachedIds.has(id));
    if (!pendingIds.length) { setSelectedTemplates([]); return; }
    try {
      setBatchBusy(true);
      const created = await api.attachWorldBooks(props.selectedChat.id, pendingIds);
      setSelectedTemplates([]);
      setStoryItems((before) => sortWorldBooks([...created, ...before]));
    } catch (reason) { props.onError(reason); }
    finally { setBatchBusy(false); }
  }
  async function remove(scope: "template" | "story", id: string) {
    try {
      if (scope === "template") { await api.deleteWorldBookTemplate(id); props.onTemplates(await api.worldBookTemplates()); }
      else if (props.selectedChat) { await api.deleteStoryWorldBook(props.selectedChat.id, id); await refreshStory(); }
    } catch (reason) { props.onError(reason); }
  }
  function toggleSelected(scope: "template" | "story", id: string, checked: boolean) {
    const update = scope === "template" ? setSelectedTemplates : setSelectedStoryItems;
    update((before) => checked ? [...new Set([...before, id])] : before.filter((item) => item !== id));
  }
  function toggleAll(scope: "template" | "story", checked: boolean) {
    if (scope === "template") setSelectedTemplates(checked ? props.templates.map((item) => item.id) : []);
    else setSelectedStoryItems(checked ? storyItems.map((item) => item.id) : []);
  }
  async function batchEnable(enabled: boolean) {
    if (!selectedStoryItems.length || !props.selectedChat) return;
    try {
      setBatchBusy(true);
      await api.batchStoryWorldBooks(props.selectedChat.id, selectedStoryItems, enabled ? "enable" : "disable");
      await refreshStory();
    } catch (reason) { props.onError(reason); }
    finally { setBatchBusy(false); }
  }
  async function batchRemove(scope: "template" | "story") {
    const ids = scope === "template" ? selectedTemplates : selectedStoryItems;
    if (!ids.length || (scope === "story" && !props.selectedChat)) return;
    const label = scope === "template" ? "世界书库中的条目" : "当前故事中的世界书";
    if (!window.confirm(`确定删除选中的 ${ids.length} 个${label}吗？此操作无法撤销。`)) return;
    try {
      setBatchBusy(true);
      if (scope === "template") {
        await api.batchWorldBookTemplates(ids, "delete");
        setSelectedTemplates([]);
        props.onTemplates(await api.worldBookTemplates());
      } else if (props.selectedChat) {
        await api.batchStoryWorldBooks(props.selectedChat.id, ids, "delete");
        setSelectedStoryItems([]);
        await refreshStory();
      }
    } catch (reason) { props.onError(reason); }
    finally { setBatchBusy(false); }
  }
  return (
    <div className="library-content">
      <LibraryColumn title="世界书库" note="这里保存可以重复使用的世界设定。" action="＋ 新建世界书" onAction={() => edit("template")}>
        <div className="library-tools"><label className="file-button">导入世界书<input type="file" accept=".json,application/json" onChange={(event) => { void importBook(event.target.files?.[0]); event.target.value = ""; }} /></label></div>
        {props.templates.length > 0 && <WorldBookBatchBar count={selectedTemplates.length} total={props.templates.length} busy={batchBusy} onAll={(checked) => toggleAll("template", checked)} onAdd={() => void batchAttach()} addDisabled={!props.selectedChat} onDelete={() => void batchRemove("template")} />}
        {props.templates.length === 0 ? <p className="muted">还没有世界书模板。</p> : props.templates.map((item) => (
          <LibraryCard key={item.id} title={item.title} detail={item.content} badge={`${item.enabled ? "已启用" : "已停用"} · 模板 · 优先级 ${item.priority}`} selected={selectedTemplates.includes(item.id)} onSelected={(checked) => toggleSelected("template", item.id, checked)}>
            <button onClick={() => attach(item.id)} disabled={!props.selectedChat || storyItems.some((storyItem) => storyItem.source_template_id === item.id)}>{storyItems.some((storyItem) => storyItem.source_template_id === item.id) ? "已添加" : "添加到故事"}</button><button onClick={() => edit("template", item)}>编辑</button><button className="delete-button" onClick={() => void remove("template", item.id)}>删除</button>
          </LibraryCard>
        ))}
      </LibraryColumn>
      <LibraryColumn title={`当前故事使用的世界书${props.selectedChat ? ` · ${props.selectedChat.title}` : ""}`} note="这里的修改只影响当前故事。">
        {props.selectedChat && storyItems.length > 0 && <WorldBookBatchBar count={selectedStoryItems.length} total={storyItems.length} busy={batchBusy} onAll={(checked) => toggleAll("story", checked)} onEnable={(enabled) => void batchEnable(enabled)} onDelete={() => void batchRemove("story")} />}
        {!props.selectedChat ? <p className="muted">请先从左侧选择一个故事。</p> : storyItems.length === 0 ? <p className="muted">这个故事尚未绑定世界书。</p> : storyItems.map((item) => (
          <LibraryCard key={item.id} title={item.title} detail={item.content} badge={`${item.enabled ? "已启用" : "已停用"} · ${item.source_template_id ? "当前故事" : "已有设定"}`} selected={selectedStoryItems.includes(item.id)} onSelected={(checked) => toggleSelected("story", item.id, checked)}>
            <button onClick={() => edit("story", item)}>编辑</button><button className="delete-button" onClick={() => void remove("story", item.id)}>移除</button>
          </LibraryCard>
        ))}
      </LibraryColumn>
      {editing && (
        <form className="library-editor" onSubmit={save}>
          <div className="action-heading"><h3>{editing.scope === "template" ? "编辑世界书" : "编辑当前故事的世界书"}</h3><button type="button" onClick={() => setEditing(null)}>关闭</button></div>
          <input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="标题" autoFocus />
          <label className="field-with-help"><span>触发词 <HelpTip text="最近对话出现其中任意一个词时，这条世界书会被启用。" /></span><input value={draft.keywords} onChange={(e) => setDraft({ ...draft, keywords: e.target.value })} placeholder="用逗号分隔" /></label>
          <textarea value={draft.content} onChange={(e) => setDraft({ ...draft, content: e.target.value })} placeholder="世界设定" rows={6} />
          <div className="world-form-row"><label><span>优先级 <HelpTip text="多条内容同时生效时，数值较高的排在前面；同一互斥组只保留最高项。" /></span><input type="number" min={0} max={100} value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: Number(e.target.value) })} /></label><label className="inline-check"><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />启用</label></div>
          <details className="advanced-settings"><summary>高级设置</summary>
            <label className="field-with-help"><span>次要关键词 <HelpTip text="填写后，触发词和次要关键词需要各命中至少一个，词条才会启用。" /></span><input value={draft.secondaryKeywords} onChange={(e) => setDraft({ ...draft, secondaryKeywords: e.target.value })} placeholder="用逗号分隔" /></label>
            <div className="world-form-row"><label><span>扫描深度 <HelpTip text="检查最近多少条消息。数值越大，较早出现的触发词也能生效。" /></span><input type="number" min={1} max={100} value={draft.scanDepth} onChange={(e) => setDraft({ ...draft, scanDepth: Number(e.target.value) })} /></label></div>
            <label><span>插入位置 <HelpTip text="控制词条相对聊天记录的位置。越靠后，通常对本轮回复的影响越直接。" /></span><select value={draft.insertionPosition} onChange={(e) => setDraft({ ...draft, insertionPosition: e.target.value as WorldEntryDraft["insertionPosition"] })}><option value="before_history">对话记录前</option><option value="after_history">对话记录后</option><option value="system">系统提示词</option></select></label>
            <label><span>互斥组 <HelpTip text="组名相同的词条不会同时启用，只保留优先级最高的一条。留空表示不分组。" /></span><input value={draft.groupName} onChange={(e) => setDraft({ ...draft, groupName: e.target.value })} /></label>
            <label><span>归属 <HelpTip text="标记这条设定通常用于全部故事、特定角色、主控人物或当前故事。" /></span><select value={draft.scope} onChange={(e) => setDraft({ ...draft, scope: e.target.value as WorldEntryDraft["scope"] })}><option value="global">通用</option><option value="character">角色专属</option><option value="persona">主控人物专属</option><option value="story">故事专属</option></select></label>
            <label><span>次要词逻辑 <HelpTip text="控制次要关键词需要命中任意、全部，或采用排除条件。没有填写次要关键词时不会影响触发。" /></span><select value={draft.selectiveLogic} onChange={(e) => setDraft({ ...draft, selectiveLogic: e.target.value as WorldEntryDraft["selectiveLogic"] })}><option value="and_any">命中任意</option><option value="and_all">命中全部</option><option value="not_any">均不命中</option><option value="not_all">不全部命中</option></select></label>
            <div className="world-settings-grid"><label><span>触发概率 <HelpTip text="满足关键词条件后实际启用的概率。100 表示每次都启用。" /></span><input type="number" min={0} max={100} value={draft.probability} onChange={(e) => setDraft({ ...draft, probability: Number(e.target.value) })} /></label><label><span>插入深度 <HelpTip text="从对话末尾向前计算的插入位置。数值越小，内容越接近最新消息。" /></span><input type="number" min={0} max={100} value={draft.depth} onChange={(e) => setDraft({ ...draft, depth: Number(e.target.value) })} /></label><label><span>持续轮数 <HelpTip text="触发后继续保持生效的轮数；0 表示只在本轮生效。" /></span><input type="number" min={0} value={draft.sticky} onChange={(e) => setDraft({ ...draft, sticky: Number(e.target.value) })} /></label><label><span>冷却轮数 <HelpTip text="一次触发结束后，需要等待多少轮才允许再次触发。" /></span><input type="number" min={0} value={draft.cooldown} onChange={(e) => setDraft({ ...draft, cooldown: Number(e.target.value) })} /></label><label><span>延迟轮数 <HelpTip text="故事开始后至少经过多少轮，这条内容才允许触发。" /></span><input type="number" min={0} value={draft.delay} onChange={(e) => setDraft({ ...draft, delay: Number(e.target.value) })} /></label></div>
            <div className="world-check-grid"><label><input type="checkbox" checked={draft.constant} onChange={(e) => setDraft({ ...draft, constant: e.target.checked })} /><span>常驻条目 <HelpTip text="不检查触发词，每轮都加入上下文。" /></span></label><label><input type="checkbox" checked={draft.caseSensitive} onChange={(e) => setDraft({ ...draft, caseSensitive: e.target.checked })} /><span>区分大小写 <HelpTip text="开启后，英文触发词必须同时匹配大小写。" /></span></label><label><input type="checkbox" checked={draft.matchWholeWords} onChange={(e) => setDraft({ ...draft, matchWholeWords: e.target.checked })} /><span>整词匹配 <HelpTip text="只匹配完整单词，避免关键词作为其他单词的一部分时误触发。" /></span></label><label><input type="checkbox" checked={draft.recursive} onChange={(e) => setDraft({ ...draft, recursive: e.target.checked })} /><span>递归激活 <HelpTip text="已经启用的世界书内容也可以继续触发其他词条。" /></span></label><label><input type="checkbox" checked={draft.preventRecursion} onChange={(e) => setDraft({ ...draft, preventRecursion: e.target.checked })} /><span>阻止递归传播 <HelpTip text="这条内容可以正常生效，但不会再用自己的正文触发其他词条。" /></span></label></div>
          </details>
          <button className="primary-button">保存</button>
        </form>
      )}
    </div>
  );
}

function LibraryColumn(props: { title: string; note: string; action?: string; onAction?: () => void; children: ReactNode }) {
  return <section className="library-column"><div className="library-column-heading"><div><h2>{props.title}</h2><p>{props.note}</p></div>{props.action && <button onClick={props.onAction}>{props.action}</button>}</div><div className="library-card-list">{props.children}</div></section>;
}

function WorldBookBatchBar(props: {
  count: number;
  total: number;
  busy: boolean;
  onAll: (checked: boolean) => void;
  onAdd?: () => void;
  addDisabled?: boolean;
  onEnable?: (enabled: boolean) => void;
  onDelete: () => void;
}) {
  const allSelected = props.total > 0 && props.count === props.total;
  return <div className="world-batch-bar">
    <label><input type="checkbox" checked={allSelected} disabled={!props.total || props.busy} onChange={(event) => props.onAll(event.target.checked)} />全选</label>
    <span>已选 {props.count} 项</span>
    {props.onAdd && <button disabled={!props.count || props.busy || props.addDisabled} onClick={props.onAdd}>批量添加到故事</button>}
    {props.onEnable && <button disabled={!props.count || props.busy} onClick={() => props.onEnable?.(true)}>批量启用</button>}
    {props.onEnable && <button disabled={!props.count || props.busy} onClick={() => props.onEnable?.(false)}>批量停用</button>}
    <button className="delete-button" disabled={!props.count || props.busy} onClick={props.onDelete}>批量删除</button>
  </div>;
}

function LibraryCard(props: { title: string; detail: string; badge: string; avatar?: string; selected?: boolean; onSelected?: (checked: boolean) => void; children: ReactNode }) {
  return <article className={`library-card${props.selected ? " selected" : ""}`}><header>{props.onSelected && <label className="library-card-select" aria-label={`选择 ${props.title}`}><input type="checkbox" checked={Boolean(props.selected)} onChange={(event) => props.onSelected?.(event.target.checked)} /></label>}{props.avatar !== undefined && <Avatar value={props.avatar} fallback={props.title.charAt(0)} />}<div><strong>{props.title}</strong><span>{props.badge}</span></div></header><p>{props.detail}</p><footer>{props.children}</footer></article>;
}

async function importWorldBookData(raw: Record<string, any>, fallbackName: string): Promise<WorldBookTemplate[]> {
  const sourceEntries = Array.isArray(raw.entries) ? raw.entries : Object.values(raw.entries || {});
  if (!sourceEntries.length) throw new Error("文件中没有可导入的世界书条目");
  const entries: object[] = [];
  const logic = ["and_any", "not_all", "not_any", "and_all"] as const;
  for (const [index, entry] of sourceEntries.entries()) {
    if (!entry || typeof entry !== "object" || !String(entry.content || "").trim()) continue;
    const rawPosition = entry.extensions?.position ?? entry.position;
    const position = rawPosition === 1 || rawPosition === "after_char" ? "after_history" : rawPosition === 4 || rawPosition === 6 ? "system" : "before_history";
    entries.push({
        title: String(entry.comment || entry.name || `${fallbackName} ${index + 1}`).slice(0, 120),
        keywords: (Array.isArray(entry.key) ? entry.key : entry.keys || []).map(String).slice(0, 30),
        secondary_keywords: (Array.isArray(entry.keysecondary) ? entry.keysecondary : entry.secondary_keys || []).map(String).slice(0, 30),
        content: String(entry.content), priority: boundedNumber(entry.order ?? entry.insertion_order, 100, 0, 10_000),
        enabled: entry.enabled !== undefined ? Boolean(entry.enabled) : !entry.disable, constant: Boolean(entry.constant), case_sensitive: Boolean(entry.caseSensitive ?? entry.case_sensitive),
        scan_depth: boundedNumber(entry.scanDepth ?? entry.extensions?.scan_depth, 4, 1, 100), insertion_position: position,
        group_name: String(entry.group || "").slice(0, 100), recursive: !entry.excludeRecursion,
        scope: "global", selective_logic: logic[boundedNumber(entry.selectiveLogic ?? entry.extensions?.selectiveLogic, 0, 0, 3)] || "and_any",
        probability: entry.useProbability === false ? 100 : boundedNumber(entry.probability, 100, 0, 100),
        match_whole_words: Boolean(entry.matchWholeWords), prevent_recursion: Boolean(entry.preventRecursion),
        depth: boundedNumber(entry.depth, 4, 0, 100), sticky: boundedNumber(entry.sticky, 0, 0, 10_000),
        cooldown: boundedNumber(entry.cooldown, 0, 0, 10_000), delay: boundedNumber(entry.delay, 0, 0, 10_000),
        compatibility_data: { source_format: "sillytavern_world_info", original_book: { ...raw, entries: undefined }, original_entry: entry },
    });
  }
  if (!entries.length) throw new Error("世界书中没有包含正文的有效条目");
  return api.importWorldBookTemplates(entries);
}

async function rollbackWorldBookTemplates(items: WorldBookTemplate[]) {
  try {
    await api.batchWorldBookTemplates(items.map((item) => item.id), "delete");
  } catch {
    // Preserve the original character-import error if cleanup also fails.
  }
}

function boundedNumber(value: unknown, fallback: number, minimum: number, maximum: number) {
  const parsed = Number(value);
  return Math.max(minimum, Math.min(maximum, Number.isFinite(parsed) ? parsed : fallback));
}

function sortWorldBooks<T extends WorldBookTemplate | StoryWorldBook>(items: T[]): T[] {
  return items.sort((left, right) => right.priority - left.priority || right.updated_at.localeCompare(left.updated_at));
}

async function readPngCharacterCard(file: File): Promise<Record<string, any>> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (!signature.every((value, index) => bytes[index] === value)) throw new Error("这不是有效的 PNG 角色卡");
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 8;
  let legacyCard: Record<string, any> | null = null;
  while (offset + 12 <= bytes.length) {
    const length = view.getUint32(offset);
    if (length > bytes.length - offset - 12) throw new Error("PNG 角色卡数据块不完整");
    const type = new TextDecoder().decode(bytes.slice(offset + 4, offset + 8));
    if (type === "tEXt") {
      const chunk = bytes.slice(offset + 8, offset + 8 + length);
      const zero = chunk.indexOf(0);
      if (zero < 1) { offset += 12 + length; continue; }
      const key = new TextDecoder().decode(chunk.slice(0, zero));
      if (key === "chara" || key === "ccv3") {
        const encoded = new TextDecoder("latin1").decode(chunk.slice(zero + 1));
        try {
          const binary = atob(encoded);
          const decoded = new TextDecoder().decode(Uint8Array.from(binary, (char) => char.charCodeAt(0)));
          const parsed = JSON.parse(decoded) as Record<string, any>;
          if (key === "ccv3") return parsed;
          legacyCard = parsed;
        } catch (reason) {
          throw new Error(`${key} 角色卡元数据无法解析：${reason instanceof Error ? reason.message : "格式无效"}`);
        }
      }
    }
    offset += 12 + length;
  }
  if (legacyCard) return legacyCard;
  throw new Error("PNG 中没有找到角色卡数据");
}

function downloadCharacterCard(item: CharacterTemplate) {
  const card = characterCardData(item);
  const blob = new Blob([JSON.stringify(card, null, 2)], { type: "application/json" });
  downloadBlob(blob, `${safeFileName(item.name)}.json`);
}

function characterCardData(item: CharacterTemplate) {
  const original = item.compatibility_data?.original_card as Record<string, any> | undefined;
  const card = original ? structuredClone(original) : {
    spec: "chara_card_v2",
    spec_version: "2.0",
    data: {},
  };
  if (card.spec !== "chara_card_v3") {
    card.spec = "chara_card_v2";
    card.spec_version = "2.0";
  }
  card.data = {
      ...(card.data || {}),
      name: item.name, description: item.identity, personality: item.personality,
      scenario: item.scenario, first_mes: item.first_message,
      alternate_greetings: item.alternate_greetings, mes_example: item.example_dialogue,
      tags: item.tags, creator_notes: item.creator_notes, system_prompt: item.system_prompt,
      post_history_instructions: item.post_history_instructions, creator: item.creator,
      character_version: item.character_version,
      extensions: { ...(card.data?.extensions || {}), saraswati: { appearance: item.appearance, speaking_style: item.speaking_style } },
    };
  return card;
}

function downloadPngCharacterCard(item: CharacterTemplate) {
  const raw = atob(item.avatar.split(",", 2)[1] || "");
  const png = Uint8Array.from(raw, (char) => char.charCodeAt(0));
  const json = new TextEncoder().encode(JSON.stringify(characterCardData(item)));
  const encoded = new TextEncoder().encode(btoa(String.fromCharCode(...json)));
  const keyword = new TextEncoder().encode("chara");
  const data = new Uint8Array(keyword.length + 1 + encoded.length);
  data.set(keyword); data[keyword.length] = 0; data.set(encoded, keyword.length + 1);
  const chunk = createPngTextChunk(data);
  const output = new Uint8Array(png.length + chunk.length);
  output.set(png.slice(0, -12));
  output.set(chunk, png.length - 12);
  output.set(png.slice(-12), png.length - 12 + chunk.length);
  downloadBlob(new Blob([output.buffer as ArrayBuffer], { type: "image/png" }), `${safeFileName(item.name)}.png`);
}

function createPngTextChunk(data: Uint8Array): Uint8Array {
  const type = new TextEncoder().encode("tEXt");
  const result = new Uint8Array(data.length + 12);
  new DataView(result.buffer).setUint32(0, data.length);
  result.set(type, 4); result.set(data, 8);
  new DataView(result.buffer).setUint32(data.length + 8, crc32(new Uint8Array([...type, ...data])));
  return result;
}

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function safeFileName(value: string) { return value.replace(/[\\/:*?"<>|]/g, "_"); }

function downloadBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}
