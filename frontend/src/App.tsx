import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { api } from "./api";
import type {
  AgentTrace,
  AppSettings,
  AuditIssue,
  Chat,
  CharacterProfile,
  Memory,
  MemoryKind,
  Message,
  RetrievedMemory,
  RuntimeInfo,
  SettingsUpdate,
  StateEntry,
  StateProposal,
  WorldBookEntry,
} from "./types";

type InspectorTab = "character" | "world" | "state" | "memory" | "audit" | "trace";
type SettingsTab = "model" | "generation" | "agent" | "appearance";
type ThemeName = "ink" | "midnight";

interface UiPreferences {
  theme: ThemeName;
  fontScale: number;
  compactMessages: boolean;
  reduceMotion: boolean;
}

export default function App() {
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [chats, setChats] = useState<Chat[]>([]);
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [retrieved, setRetrieved] = useState<RetrievedMemory[]>([]);
  const [stateEntries, setStateEntries] = useState<StateEntry[]>([]);
  const [proposals, setProposals] = useState<StateProposal[]>([]);
  const [audits, setAudits] = useState<AuditIssue[]>([]);
  const [traces, setTraces] = useState<AgentTrace[]>([]);
  const [activeTab, setActiveTab] = useState<InspectorTab>("character");
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [uiPreferences, setUiPreferences] = useState<UiPreferences>(loadUiPreferences);
  const bottomRef = useRef<HTMLDivElement>(null);

  const selectedChat = useMemo(
    () => chats.find((chat) => chat.id === selectedChatId) ?? null,
    [chats, selectedChatId],
  );

  useEffect(() => {
    void initialize();
  }, []);

  useEffect(() => {
    if (selectedChatId) void loadChat(selectedChatId);
  }, [selectedChatId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  async function initialize() {
    try {
      setLoading(true);
      const [runtimeInfo, chatList] = await Promise.all([api.runtime(), api.chats()]);
      setRuntime(runtimeInfo);
      setChats(chatList);
      if (chatList.length) setSelectedChatId(chatList[0].id);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  }

  async function loadChat(chatId: string) {
    try {
      setLoading(true);
      const [messageList, memoryList, stateList, proposalList, auditList, traceList] =
        await Promise.all([
          api.messages(chatId),
          api.memories(chatId),
          api.state(chatId),
          api.proposals(chatId),
          api.audits(chatId),
          api.traces(chatId),
        ]);
      setMessages(messageList);
      setMemories(memoryList);
      setStateEntries(stateList);
      setProposals(proposalList);
      setAudits(auditList);
      setTraces(traceList);
      setRetrieved([]);
      setError(null);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  }

  async function refreshInspector(chatId: string) {
    const [memoryList, stateList, proposalList, auditList, traceList] = await Promise.all([
      api.memories(chatId),
      api.state(chatId),
      api.proposals(chatId),
      api.audits(chatId),
      api.traces(chatId),
    ]);
    setMemories(memoryList);
    setStateEntries(stateList);
    setProposals(proposalList);
    setAudits(auditList);
    setTraces(traceList);
  }

  async function createChat(title: string) {
    try {
      const chat = await api.createChat(title);
      setChats((current) => [chat, ...current]);
      setSelectedChatId(chat.id);
      setActiveTab("character");
      setError(null);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!selectedChatId || !content || sending) return;

    try {
      setSending(true);
      setDraft("");
      setError(null);
      const turn = await api.sendMessage(selectedChatId, content);
      setMessages((current) => [
        ...current,
        turn.user_message,
        turn.assistant_message,
      ]);
      setRetrieved(turn.retrieved_memories);
      if (turn.state_proposals.length) setActiveTab("state");
      if (turn.audit_issues.length) setActiveTab("audit");
      await refreshInspector(selectedChatId);
    } catch (reason) {
      setDraft(content);
      setError(errorMessage(reason));
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      className={`app-shell theme-${uiPreferences.theme}${uiPreferences.compactMessages ? " compact-messages" : ""}${uiPreferences.reduceMotion ? " reduce-motion" : ""}`}
      style={{ "--font-scale": uiPreferences.fontScale } as CSSProperties}
    >
      <Sidebar
        chats={chats}
        selectedChatId={selectedChatId}
        onSelect={setSelectedChatId}
        onCreate={createChat}
      />

      <main className="conversation-pane">
        <header className="topbar">
          <div>
            <p className="eyebrow">SARASWATI AGENT</p>
            <h1>{selectedChat?.title ?? "选择或创建一个故事"}</h1>
          </div>
          <div className="topbar-actions">
            <div className={`provider-badge ${runtime?.provider_mode === "demo" ? "demo" : "live"}`}>
              <span className="status-dot" />
              {runtime?.provider_mode === "demo"
                ? "演示模式"
                : runtime?.model ?? "模型已连接"}
            </div>
            <button className="settings-button" onClick={() => setSettingsOpen(true)} aria-label="打开设置">
              ⚙ <span>设置</span>
            </button>
          </div>
        </header>

        {error && <div className="error-banner">{error}</div>}

        <section className="message-list">
          {!selectedChatId ? (
            <EmptyState title="从左侧建立第一个存档" detail="给故事一个名字，再写下角色或世界设定。" />
          ) : loading && messages.length === 0 ? (
            <EmptyState title="正在展开书页…" detail="读取消息、记忆和世界状态。" />
          ) : messages.length === 0 ? (
            <EmptyState title="故事尚未开始" detail="在下方写下第一句话。" />
          ) : (
            messages.map((message) => <MessageBubble key={message.id} message={message} />)
          )}
          {sending && (
            <div className="message-row assistant">
              <div className="avatar">S</div>
              <div className="bubble thinking"><i /><i /><i /></div>
            </div>
          )}
          <div ref={bottomRef} />
        </section>

        <form className="composer" onSubmit={sendMessage}>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder={selectedChatId ? "继续你的故事…" : "请先创建存档"}
            disabled={!selectedChatId || sending}
            rows={2}
          />
          <div className="composer-footer">
            <span>Enter 发送 · Shift + Enter 换行</span>
            <button className="primary-button" disabled={!draft.trim() || !selectedChatId || sending}>
              {sending ? "生成中" : "发送"}
            </button>
          </div>
        </form>
      </main>

      <Inspector
        chatId={selectedChatId}
        activeTab={activeTab}
        onTab={setActiveTab}
        memories={memories}
        retrieved={retrieved}
        stateEntries={stateEntries}
        proposals={proposals}
        audits={audits}
        traces={traces}
        onRefresh={() => {
          if (selectedChatId) return refreshInspector(selectedChatId);
        }}
        onError={(reason) => setError(errorMessage(reason))}
      />
      {settingsOpen && (
        <SettingsModal
          preferences={uiPreferences}
          onPreferences={setUiPreferences}
          onRuntime={setRuntime}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  );
}

function Sidebar({
  chats,
  selectedChatId,
  onSelect,
  onCreate,
}: {
  chats: Chat[];
  selectedChatId: string | null;
  onSelect: (id: string) => void;
  onCreate: (title: string) => Promise<void>;
}) {
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    await onCreate(title.trim());
    setTitle("");
    setCreating(false);
  }

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">स</div>
        <div><strong>Saraswati</strong><span>叙事与记忆</span></div>
      </div>
      <button className="new-chat-button" onClick={() => setCreating((value) => !value)}>
        <span>＋</span> 新建故事
      </button>
      {creating && (
        <form className="create-card" onSubmit={submit}>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="存档标题" autoFocus />
          <button className="primary-button">创建</button>
        </form>
      )}
      <p className="section-label">故事存档</p>
      <nav className="chat-list">
        {chats.map((chat) => (
          <button
            key={chat.id}
            className={chat.id === selectedChatId ? "chat-item active" : "chat-item"}
            onClick={() => onSelect(chat.id)}
          >
            <span className="book-icon">◈</span>
            <span><strong>{chat.title}</strong><small>{formatDate(chat.updated_at)}</small></span>
          </button>
        ))}
      </nav>
      <div className="sidebar-note">状态修改需要你的确认<br />记忆召回均可追溯来源</div>
    </aside>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const assistant = message.role === "assistant";
  return (
    <div className={`message-row ${assistant ? "assistant" : "user"}`}>
      {assistant && <div className="avatar">S</div>}
      <div className="message-column">
        <div className="message-meta">{assistant ? "Saraswati" : "你"}<span>{formatTime(message.created_at)}</span></div>
        <div className="bubble">{message.content}</div>
      </div>
    </div>
  );
}

function Inspector(props: {
  chatId: string | null;
  activeTab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  memories: Memory[];
  retrieved: RetrievedMemory[];
  stateEntries: StateEntry[];
  proposals: StateProposal[];
  audits: AuditIssue[];
  traces: AgentTrace[];
  onRefresh: () => Promise<void> | void;
  onError: (reason: unknown) => void;
}) {
  const tabs: { id: InspectorTab; label: string; count?: number }[] = [
    { id: "character", label: "角色" },
    { id: "world", label: "世界书" },
    { id: "state", label: "状态", count: props.proposals.filter((item) => item.status === "pending").length },
    { id: "memory", label: "记忆", count: props.memories.length },
    { id: "audit", label: "审计", count: props.audits.filter((item) => item.status === "open").length },
    { id: "trace", label: "轨迹" },
  ];

  return (
    <aside className="inspector">
      <div className="inspector-title"><span>运行观察台</span><small>可解释 · 可审核</small></div>
      <div className="tabs">
        {tabs.map((tab) => (
          <button key={tab.id} className={props.activeTab === tab.id ? "active" : ""} onClick={() => props.onTab(tab.id)}>
            {tab.label}{Boolean(tab.count) && <em>{tab.count}</em>}
          </button>
        ))}
      </div>
      <div className="inspector-content">
        {!props.chatId ? (
          <EmptyState title="暂无数据" detail="选择存档后查看 Agent 的内部状态。" />
        ) : props.activeTab === "character" ? (
          <CharacterPanel chatId={props.chatId} onError={props.onError} />
        ) : props.activeTab === "world" ? (
          <WorldBookPanel chatId={props.chatId} onError={props.onError} />
        ) : props.activeTab === "state" ? (
          <StatePanel {...props} chatId={props.chatId} />
        ) : props.activeTab === "memory" ? (
          <MemoryPanel {...props} chatId={props.chatId} />
        ) : props.activeTab === "audit" ? (
          <AuditPanel {...props} chatId={props.chatId} />
        ) : (
          <TracePanel traces={props.traces} />
        )}
      </div>
    </aside>
  );
}

function CharacterPanel({ chatId, onError }: { chatId: string; onError: (reason: unknown) => void }) {
  const [profile, setProfile] = useState<CharacterProfile | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setProfile(null);
    void api.character(chatId).then(setProfile).catch(onError);
  }, [chatId]);

  function update(key: keyof CharacterProfile, value: string) {
    setProfile((current) => current ? { ...current, [key]: value } : current);
    setSaved(false);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!profile) return;
    try {
      const updated = await api.updateCharacter(chatId, {
        name: profile.name,
        identity: profile.identity,
        personality: profile.personality,
        speaking_style: profile.speaking_style,
        scenario: profile.scenario,
      });
      setProfile(updated);
      setSaved(true);
    } catch (reason) {
      onError(reason);
    }
  }

  if (!profile) return <p className="muted">正在读取角色档案…</p>;
  return (
    <form className="panel-stack character-form" onSubmit={submit}>
      <PanelHeading title="角色档案" note="这里的内容会作为稳定角色约束进入每轮上下文" />
      <label><span>角色名</span><input value={profile.name} onChange={(e) => update("name", e.target.value)} placeholder="例如：守门人阿斯塔" /></label>
      <label><span>身份与背景</span><textarea value={profile.identity} onChange={(e) => update("identity", e.target.value)} placeholder="身份、经历、能力与重要关系" rows={4} /></label>
      <label><span>性格</span><textarea value={profile.personality} onChange={(e) => update("personality", e.target.value)} placeholder="核心性格、价值观、喜恶与行为边界" rows={4} /></label>
      <label><span>说话风格</span><textarea value={profile.speaking_style} onChange={(e) => update("speaking_style", e.target.value)} placeholder="语气、措辞习惯、称呼方式和禁用表达" rows={3} /></label>
      <label><span>当前情境</span><textarea value={profile.scenario} onChange={(e) => update("scenario", e.target.value)} placeholder="故事开场地点、角色目标和与玩家的关系" rows={4} /></label>
      <div className="panel-form-footer"><small>{saved ? "已保存，下一轮对话开始生效" : "修改后请保存"}</small><button className="primary-button">保存角色</button></div>
    </form>
  );
}

interface WorldEntryDraft {
  title: string;
  keywords: string;
  content: string;
  priority: number;
  enabled: boolean;
}

const EMPTY_WORLD_ENTRY: WorldEntryDraft = {
  title: "",
  keywords: "",
  content: "",
  priority: 50,
  enabled: true,
};

function WorldBookPanel({ chatId, onError }: { chatId: string; onError: (reason: unknown) => void }) {
  const [entries, setEntries] = useState<WorldBookEntry[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [draft, setDraft] = useState<WorldEntryDraft>(EMPTY_WORLD_ENTRY);

  useEffect(() => {
    setEntries([]);
    setShowForm(false);
    setEditingId(null);
    void api.worldBook(chatId).then(setEntries).catch(onError);
  }, [chatId]);

  function startCreate() {
    setEditingId(null);
    setDraft(EMPTY_WORLD_ENTRY);
    setShowForm(true);
  }

  function startEdit(entry: WorldBookEntry) {
    setEditingId(entry.id);
    setDraft({
      title: entry.title,
      keywords: entry.keywords.join("，"),
      content: entry.content,
      priority: entry.priority,
      enabled: entry.enabled,
    });
    setShowForm(true);
  }

  function payload(value: WorldEntryDraft) {
    return {
      title: value.title.trim(),
      keywords: value.keywords.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean),
      content: value.content.trim(),
      priority: value.priority,
      enabled: value.enabled,
    };
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft.title.trim() || !draft.content.trim()) return;
    try {
      if (editingId) await api.updateWorldEntry(chatId, editingId, payload(draft));
      else await api.createWorldEntry(chatId, payload(draft));
      setEntries(await api.worldBook(chatId));
      setShowForm(false);
      setEditingId(null);
      setDraft(EMPTY_WORLD_ENTRY);
    } catch (reason) {
      onError(reason);
    }
  }

  async function toggle(entry: WorldBookEntry) {
    try {
      await api.updateWorldEntry(chatId, entry.id, { ...entry, enabled: !entry.enabled });
      setEntries(await api.worldBook(chatId));
    } catch (reason) {
      onError(reason);
    }
  }

  async function remove(entryId: string) {
    if (confirmDeleteId !== entryId) {
      setConfirmDeleteId(entryId);
      return;
    }
    try {
      await api.deleteWorldEntry(chatId, entryId);
      setEntries((current) => current.filter((entry) => entry.id !== entryId));
      setConfirmDeleteId(null);
    } catch (reason) {
      onError(reason);
    }
  }

  return (
    <div className="panel-stack">
      <div className="action-heading"><PanelHeading title="世界书" note="关键词命中时才注入；无关键词的词条始终生效" /><button onClick={startCreate}>＋ 新建词条</button></div>
      {showForm && (
        <form className="world-entry-form" onSubmit={save}>
          <input value={draft.title} onChange={(e) => setDraft((value) => ({ ...value, title: e.target.value }))} placeholder="词条标题" autoFocus />
          <input value={draft.keywords} onChange={(e) => setDraft((value) => ({ ...value, keywords: e.target.value }))} placeholder="触发关键词，用逗号分隔；留空表示常驻" />
          <textarea value={draft.content} onChange={(e) => setDraft((value) => ({ ...value, content: e.target.value }))} placeholder="需要告诉 Agent 的世界设定" rows={6} />
          <div className="world-form-row"><label><span>优先级</span><input type="number" min={0} max={100} value={draft.priority} onChange={(e) => setDraft((value) => ({ ...value, priority: Number(e.target.value) }))} /></label><label className="inline-check"><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft((value) => ({ ...value, enabled: e.target.checked }))} /> 启用</label></div>
          <footer><button type="button" onClick={() => setShowForm(false)}>取消</button><button className="primary-button">{editingId ? "保存修改" : "创建词条"}</button></footer>
        </form>
      )}
      {entries.length === 0 && !showForm ? <p className="muted">还没有世界书词条。无关键词词条适合保存世界常识，有关键词词条适合按需触发。</p> : entries.map((entry) => (
        <article className={`world-entry-card${entry.enabled ? "" : " disabled"}`} key={entry.id}>
          <header><div><strong>{entry.title}</strong><small>优先级 {entry.priority}</small></div><button className={entry.enabled ? "enabled" : ""} onClick={() => toggle(entry)}>{entry.enabled ? "已启用" : "已停用"}</button></header>
          <div className="keyword-list">{entry.keywords.length ? entry.keywords.map((keyword) => <span key={keyword}>{keyword}</span>) : <span>常驻</span>}</div>
          <p>{entry.content}</p>
          <footer><button onClick={() => startEdit(entry)}>编辑</button><button className="delete-button" onClick={() => remove(entry.id)}>{confirmDeleteId === entry.id ? "确认删除" : "删除"}</button></footer>
        </article>
      ))}
    </div>
  );
}

function StatePanel(props: {
  chatId: string;
  stateEntries: StateEntry[];
  proposals: StateProposal[];
  onRefresh: () => Promise<void> | void;
  onError: (reason: unknown) => void;
}) {
  const [entity, setEntity] = useState("玩家");
  const [key, setKey] = useState("金币");
  const [value, setValue] = useState("100");

  async function create(event: FormEvent) {
    event.preventDefault();
    try {
      let parsed: unknown = value;
      try { parsed = JSON.parse(value); } catch { /* 普通文本直接保存为字符串 */ }
      await api.createProposal(props.chatId, {
        entity,
        key,
        new_value: parsed,
        reason: "用户手动设置",
      });
      await props.onRefresh();
    } catch (reason) { props.onError(reason); }
  }

  async function resolve(id: string, action: "approve" | "reject") {
    try {
      await api.resolveProposal(props.chatId, id, action);
      await props.onRefresh();
    } catch (reason) { props.onError(reason); }
  }

  const pending = props.proposals.filter((item) => item.status === "pending");
  return (
    <div className="panel-stack">
      <PanelHeading title="当前事实" note="数据库中的唯一精确状态" />
      {props.stateEntries.length === 0 ? <p className="muted">还没有已批准状态。</p> : props.stateEntries.map((entry) => (
        <div className="state-row" key={entry.id}>
          <div><strong>{entry.entity}</strong><span>{entry.key}</span></div>
          <code>{displayValue(entry.value)}</code><small>v{entry.version}</small>
        </div>
      ))}
      <PanelHeading title="待审核建议" note={`${pending.length} 条等待决定`} />
      {pending.length === 0 ? <p className="muted">Agent 暂未提出修改。</p> : pending.map((item) => (
        <article className="proposal-card" key={item.id}>
          <header><strong>{item.entity}.{item.key}</strong><span>待审核</span></header>
          <div className="value-change"><code>{displayValue(item.old_value)}</code><b>→</b><code>{displayValue(item.new_value)}</code></div>
          <p>{item.reason}</p>
          <footer><button onClick={() => resolve(item.id, "reject")}>拒绝</button><button className="approve" onClick={() => resolve(item.id, "approve")}>批准</button></footer>
        </article>
      ))}
      <PanelHeading title="手动建立状态" note="用于世界初始值和测试" />
      <form className="mini-form" onSubmit={create}>
        <div className="two-columns"><input value={entity} onChange={(e) => setEntity(e.target.value)} placeholder="实体" /><input value={key} onChange={(e) => setKey(e.target.value)} placeholder="字段" /></div>
        <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="值，例如 87 或 剑冢" />
        <button>创建审核建议</button>
      </form>
    </div>
  );
}

function MemoryPanel(props: {
  chatId: string;
  memories: Memory[];
  retrieved: RetrievedMemory[];
  onRefresh: () => Promise<void> | void;
  onError: (reason: unknown) => void;
}) {
  const [kind, setKind] = useState<MemoryKind>("semantic");
  const [content, setContent] = useState("");
  const scoreMap = new Map(props.retrieved.map((item) => [item.memory.id, item]));

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!content.trim()) return;
    try {
      await api.createMemory(props.chatId, { kind, content: content.trim(), importance: 0.7 });
      setContent("");
      await props.onRefresh();
    } catch (reason) { props.onError(reason); }
  }

  async function summarize() {
    try { await api.summarize(props.chatId); await props.onRefresh(); }
    catch (reason) { props.onError(reason); }
  }

  return (
    <div className="panel-stack">
      <div className="panel-heading action-heading"><div><h3>分层记忆</h3><p>最近召回会显示评分依据</p></div><button onClick={summarize}>总结近期</button></div>
      {props.memories.length === 0 ? <p className="muted">对话后会自动生成情节记忆。</p> : props.memories.map((memory) => {
        const hit = scoreMap.get(memory.id);
        return (
          <article className={`memory-card ${hit ? "retrieved" : ""}`} key={memory.id}>
            <header><span className={`kind ${memory.kind}`}>{memoryKindLabel(memory.kind)}</span>{hit && <strong>{hit.score.toFixed(3)}</strong>}</header>
            <p>{memory.content}</p>
            <footer><span>重要度 {memory.importance.toFixed(1)}</span><span>召回 {memory.access_count} 次</span></footer>
            {hit && <small>{hit.retrieval_reason}</small>}
          </article>
        );
      })}
      <PanelHeading title="写入记忆" note="只保存跨多轮仍有价值的信息" />
      <form className="mini-form" onSubmit={create}>
        <select value={kind} onChange={(e) => setKind(e.target.value as MemoryKind)}><option value="semantic">事实记忆</option><option value="implicit">隐性记忆</option><option value="summary">剧情摘要</option><option value="episodic">情节记忆</option></select>
        <textarea value={content} onChange={(e) => setContent(e.target.value)} placeholder="例如：守门人害怕银色铃铛。" rows={4} />
        <button>保存记忆</button>
      </form>
    </div>
  );
}

function AuditPanel(props: { chatId: string; audits: AuditIssue[]; onRefresh: () => Promise<void> | void; onError: (reason: unknown) => void }) {
  async function resolve(id: string, action: "resolve" | "dismiss") {
    try { await api.resolveAudit(props.chatId, id, action); await props.onRefresh(); }
    catch (reason) { props.onError(reason); }
  }
  return (
    <div className="panel-stack">
      <PanelHeading title="一致性审计" note="根据已批准状态检查模型回复" />
      {props.audits.length === 0 ? <p className="muted">尚未发现状态冲突。</p> : props.audits.map((issue) => (
        <article className={`audit-card ${issue.status}`} key={issue.id}>
          <header><strong>{auditCategoryLabel(issue.category)}</strong><span>{auditStatusLabel(issue.status)}</span></header>
          <p>{issue.description}</p>
          <div className="audit-values"><span>期望 <code>{displayValue(issue.expected_value)}</code></span><span>实际 <code>{displayValue(issue.actual_value)}</code></span></div>
          <blockquote>{issue.evidence}</blockquote>
          {issue.status === "open" && <footer><button onClick={() => resolve(issue.id, "dismiss")}>忽略</button><button className="approve" onClick={() => resolve(issue.id, "resolve")}>已修复</button></footer>}
        </article>
      ))}
    </div>
  );
}

function TracePanel({ traces }: { traces: AgentTrace[] }) {
  return (
    <div className="panel-stack">
      <PanelHeading title="Agent 轨迹" note="查看上下文、模型和工具执行过程" />
      {traces.length === 0 ? <p className="muted">发送消息后会记录执行轨迹。</p> : traces.map((trace) => (
        <details className="trace-card" key={trace.id}>
          <summary><span>步骤 {trace.step}</span><strong>{traceEventLabel(trace.event_type)}</strong><time>{formatTime(trace.created_at)}</time></summary>
          <pre>{JSON.stringify(trace.payload, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}

function PanelHeading({ title, note }: { title: string; note: string }) {
  return <div className="panel-heading"><h3>{title}</h3><p>{note}</p></div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><div>✦</div><h2>{title}</h2><p>{detail}</p></div>;
}

function SettingsModal({
  preferences,
  onPreferences,
  onRuntime,
  onClose,
}: {
  preferences: UiPreferences;
  onPreferences: (value: UiPreferences) => void;
  onRuntime: (value: RuntimeInfo) => void;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("model");
  const [current, setCurrent] = useState<AppSettings | null>(null);
  const [form, setForm] = useState<SettingsUpdate | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [draftPreferences, setDraftPreferences] = useState(preferences);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    void api.settings()
      .then((settings) => {
        setCurrent(settings);
        setForm(settingsToUpdate(settings));
      })
      .catch((reason) => setNotice({ kind: "error", text: errorMessage(reason) }));
  }, []);

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  function updateField<K extends keyof SettingsUpdate>(key: K, value: SettingsUpdate[K]) {
    setForm((valueBefore) => valueBefore ? { ...valueBefore, [key]: value } : valueBefore);
  }

  async function saveSettings(showSavedMessage = true): Promise<boolean> {
    if (!form) return false;
    try {
      setBusy(true);
      setNotice(null);
      const saved = await api.updateSettings({
        ...form,
        api_key: apiKey.trim() || null,
      });
      const runtimeInfo = await api.runtime();
      setCurrent(saved);
      setForm(settingsToUpdate(saved));
      setApiKey("");
      persistUiPreferences(draftPreferences);
      onPreferences(draftPreferences);
      onRuntime(runtimeInfo);
      if (showSavedMessage) setNotice({ kind: "ok", text: "设置已保存并立即生效。" });
      return true;
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function testConnection() {
    const saved = await saveSettings(false);
    if (!saved) return;
    try {
      setBusy(true);
      const result = await api.testSettings();
      setNotice({ kind: "ok", text: result.message });
    } catch (reason) {
      setNotice({ kind: "error", text: errorMessage(reason) });
    } finally {
      setBusy(false);
    }
  }

  function restoreDefaults() {
    if (!form) return;
    setForm({
      ...form,
      temperature: 0.8,
      top_p: 1,
      max_output_tokens: 2048,
      presence_penalty: 0,
      frequency_penalty: 0,
      request_timeout: 90,
      max_agent_steps: 4,
      recent_message_limit: 16,
      rag_limit: 5,
      vector_weight: 0.55,
      keyword_weight: 0.25,
      importance_weight: 0.15,
      recency_weight: 0.05,
    });
    setDraftPreferences(DEFAULT_UI_PREFERENCES);
    setNotice({ kind: "ok", text: "已恢复推荐值，点击“保存并应用”后生效。" });
  }

  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "model", label: "模型 API" },
    { id: "generation", label: "生成参数" },
    { id: "agent", label: "Agent 与记忆" },
    { id: "appearance", label: "界面与隐私" },
  ];
  const weightTotal = form
    ? form.vector_weight + form.keyword_weight + form.importance_weight + form.recency_weight
    : 0;

  return (
    <div className="settings-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <header className="settings-header">
          <div><p className="eyebrow">SARASWATI CONTROL</p><h2 id="settings-title">设置中心</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="关闭设置">×</button>
        </header>
        <div className="settings-layout">
          <nav className="settings-nav">
            {tabs.map((tab) => (
              <button key={tab.id} className={activeTab === tab.id ? "active" : ""} onClick={() => setActiveTab(tab.id)}>
                {tab.label}
              </button>
            ))}
            <button className="restore-button" onClick={restoreDefaults} disabled={!form || busy}>恢复推荐值</button>
          </nav>
          <div className="settings-content">
            {!form || !current ? (
              <p className="settings-loading">正在读取本机设置…</p>
            ) : activeTab === "model" ? (
              <div className="settings-section">
                <SettingsHeading title="模型 API" detail="兼容 OpenAI Chat Completions 接口的服务都可以接入。" />
                <label className="settings-field"><span>API 地址</span><small>通常以 /v1 结尾，例如 https://api.example.com/v1</small><input value={form.llm_base_url ?? ""} onChange={(e) => updateField("llm_base_url", e.target.value || null)} placeholder="https://api.example.com/v1" /></label>
                <label className="settings-field"><span>API Key</span><small>{current.api_key_configured ? `已保存：${current.api_key_hint}；留空表示保持不变` : "尚未配置，只保存在本机 data/settings.json"}</small><input type="password" autoComplete="off" value={apiKey} onChange={(e) => { setApiKey(e.target.value); if (e.target.value) updateField("clear_api_key", false); }} placeholder={current.api_key_configured ? "••••••••（保持不变）" : "sk-..."} /></label>
                {current.api_key_configured && <label className="check-row danger-check"><input type="checkbox" checked={form.clear_api_key} onChange={(e) => updateField("clear_api_key", e.target.checked)} /><span>保存时删除已存储的 API Key</span></label>}
                <div className="settings-grid">
                  <label className="settings-field"><span>对话模型</span><small>负责回复和工具调用</small><input value={form.llm_model ?? ""} onChange={(e) => updateField("llm_model", e.target.value || null)} placeholder="模型名称" /></label>
                  <label className="settings-field"><span>Embedding 模型</span><small>留空时使用本地哈希向量</small><input value={form.embedding_model ?? ""} onChange={(e) => updateField("embedding_model", e.target.value || null)} placeholder="可选" /></label>
                </div>
                <NumberSetting label="请求超时" note="模型最长等待时间（秒）" value={form.request_timeout} min={5} max={600} step={5} onChange={(value) => updateField("request_timeout", value)} />
                <div className={`connection-state ${current.provider_mode === "demo" ? "demo" : "live"}`}><span className="status-dot" /><div><strong>{current.provider_mode === "demo" ? "当前为演示模式" : "真实模型模式"}</strong><small>{current.provider_mode === "demo" ? "完整填写地址、Key 和模型名后切换" : current.llm_model}</small></div></div>
              </div>
            ) : activeTab === "generation" ? (
              <div className="settings-section">
                <SettingsHeading title="生成参数" detail="推荐先使用默认值；参数越极端，角色回复越容易失控。" />
                <NumberSetting label="温度 Temperature" note="越高越随机，角色扮演推荐 0.7～1.0" value={form.temperature} min={0} max={2} step={0.05} onChange={(value) => updateField("temperature", value)} />
                <NumberSetting label="Top-P" note="控制候选词范围，通常保持 1" value={form.top_p} min={0.05} max={1} step={0.05} onChange={(value) => updateField("top_p", value)} />
                <NumberSetting label="最大输出 Token" note="限制单次回复长度，也影响费用" value={form.max_output_tokens} min={64} max={32768} step={64} onChange={(value) => updateField("max_output_tokens", Math.round(value))} />
                <NumberSetting label="Presence Penalty" note="正值鼓励引入尚未出现的新内容" value={form.presence_penalty} min={-2} max={2} step={0.1} onChange={(value) => updateField("presence_penalty", value)} />
                <NumberSetting label="Frequency Penalty" note="正值减少重复用词和重复表达" value={form.frequency_penalty} min={-2} max={2} step={0.1} onChange={(value) => updateField("frequency_penalty", value)} />
              </div>
            ) : activeTab === "agent" ? (
              <div className="settings-section">
                <SettingsHeading title="Agent 与上下文" detail="这些参数决定每轮可以思考几步，以及携带多少历史信息。" />
                <NumberSetting label="最大 Agent 步数" note="模型和工具往返的上限；越高越慢且更贵" value={form.max_agent_steps} min={1} max={12} step={1} onChange={(value) => updateField("max_agent_steps", Math.round(value))} />
                <NumberSetting label="近期原文条数" note="直接放入上下文的最近消息数量" value={form.recent_message_limit} min={2} max={100} step={2} onChange={(value) => updateField("recent_message_limit", Math.round(value))} />
                <NumberSetting label="RAG 召回条数" note="每轮注入的相关长期记忆上限" value={form.rag_limit} min={1} max={30} step={1} onChange={(value) => updateField("rag_limit", Math.round(value))} />
                <div className="subsection-title"><strong>混合 RAG 权重</strong><small>系统会自动按总和归一化 · 当前总和 {weightTotal.toFixed(2)}</small></div>
                <div className="settings-grid">
                  <NumberSetting label="向量语义" note="意思是否相近" value={form.vector_weight} min={0} max={1} step={0.05} onChange={(value) => updateField("vector_weight", value)} compact />
                  <NumberSetting label="关键词" note="字面线索重合" value={form.keyword_weight} min={0} max={1} step={0.05} onChange={(value) => updateField("keyword_weight", value)} compact />
                  <NumberSetting label="记忆重要度" note="人工或 Agent 标记" value={form.importance_weight} min={0} max={1} step={0.05} onChange={(value) => updateField("importance_weight", value)} compact />
                  <NumberSetting label="时间新鲜度" note="近期记忆略微优先" value={form.recency_weight} min={0} max={1} step={0.05} onChange={(value) => updateField("recency_weight", value)} compact />
                </div>
                {weightTotal <= 0 && <p className="field-error">至少有一项 RAG 权重必须大于 0。</p>}
              </div>
            ) : (
              <div className="settings-section">
                <SettingsHeading title="界面与隐私" detail="界面偏好保存在浏览器中，模型配置保存在本机后端。" />
                <label className="settings-field"><span>配色主题</span><small>选择适合长时间阅读的背景</small><select value={draftPreferences.theme} onChange={(e) => setDraftPreferences((value) => ({ ...value, theme: e.target.value as ThemeName }))}><option value="ink">墨黑金色</option><option value="midnight">深夜蓝色</option></select></label>
                <NumberSetting label="文字缩放" note="只影响客户端显示，不影响模型上下文" value={draftPreferences.fontScale} min={0.85} max={1.25} step={0.05} onChange={(value) => setDraftPreferences((before) => ({ ...before, fontScale: value }))} />
                <label className="check-row"><input type="checkbox" checked={draftPreferences.compactMessages} onChange={(e) => setDraftPreferences((value) => ({ ...value, compactMessages: e.target.checked }))} /><span><strong>紧凑消息间距</strong><small>同屏显示更多对话内容</small></span></label>
                <label className="check-row"><input type="checkbox" checked={draftPreferences.reduceMotion} onChange={(e) => setDraftPreferences((value) => ({ ...value, reduceMotion: e.target.checked }))} /><span><strong>减少动画</strong><small>关闭滚动和生成指示动画</small></span></label>
                <div className="privacy-note"><strong>本地数据说明</strong><p>聊天、记忆和状态保存在 SQLite；模型配置保存在 <code>data/settings.json</code>。这两个位置都已被 Git 忽略。API Key 不会返回到前端页面，但本机配置文件不是加密保险箱，请勿共享该文件。</p></div>
              </div>
            )}
          </div>
        </div>
        {notice && <div className={`settings-notice ${notice.kind}`}>{notice.text}</div>}
        <footer className="settings-footer">
          <button className="secondary-button" onClick={testConnection} disabled={!form || busy || weightTotal <= 0}>{busy ? "处理中…" : "保存并测试连接"}</button>
          <div><button className="ghost-button" onClick={onClose}>取消</button><button className="primary-button" onClick={() => void saveSettings()} disabled={!form || busy || weightTotal <= 0}>{busy ? "保存中…" : "保存并应用"}</button></div>
        </footer>
      </section>
    </div>
  );
}

function SettingsHeading({ title, detail }: { title: string; detail: string }) {
  return <div className="settings-heading"><h3>{title}</h3><p>{detail}</p></div>;
}

function NumberSetting({ label, note, value, min, max, step, onChange, compact = false }: {
  label: string;
  note: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  compact?: boolean;
}) {
  return (
    <label className={`number-setting${compact ? " compact" : ""}`}>
      <span><strong>{label}</strong><small>{note}</small></span>
      <input type="range" value={value} min={min} max={max} step={step} onChange={(e) => onChange(Number(e.target.value))} />
      <input type="number" value={value} min={min} max={max} step={step} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function settingsToUpdate(settings: AppSettings): SettingsUpdate {
  return {
    llm_base_url: settings.llm_base_url,
    api_key: null,
    clear_api_key: false,
    llm_model: settings.llm_model,
    embedding_model: settings.embedding_model,
    temperature: settings.temperature,
    top_p: settings.top_p,
    max_output_tokens: settings.max_output_tokens,
    presence_penalty: settings.presence_penalty,
    frequency_penalty: settings.frequency_penalty,
    request_timeout: settings.request_timeout,
    max_agent_steps: settings.max_agent_steps,
    recent_message_limit: settings.recent_message_limit,
    rag_limit: settings.rag_limit,
    vector_weight: settings.vector_weight,
    keyword_weight: settings.keyword_weight,
    importance_weight: settings.importance_weight,
    recency_weight: settings.recency_weight,
  };
}

const DEFAULT_UI_PREFERENCES: UiPreferences = {
  theme: "ink",
  fontScale: 1,
  compactMessages: false,
  reduceMotion: false,
};

function loadUiPreferences(): UiPreferences {
  try {
    const stored = JSON.parse(localStorage.getItem("saraswati-ui-settings") ?? "null");
    return stored ? { ...DEFAULT_UI_PREFERENCES, ...stored } : DEFAULT_UI_PREFERENCES;
  } catch {
    return DEFAULT_UI_PREFERENCES;
  }
}

function persistUiPreferences(value: UiPreferences) {
  localStorage.setItem("saraswati-ui-settings", JSON.stringify(value));
}

function displayValue(value: unknown) {
  if (value === null || value === undefined) return "未设置";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function memoryKindLabel(kind: MemoryKind) {
  return { episodic: "情节", semantic: "事实", summary: "摘要", implicit: "隐性" }[kind];
}

function auditCategoryLabel(category: string) {
  return {
    numeric_state_conflict: "数值状态冲突",
  }[category] ?? category;
}

function auditStatusLabel(status: string) {
  return {
    open: "待处理",
    resolved: "已修复",
    dismissed: "已忽略",
  }[status] ?? status;
}

function traceEventLabel(eventType: string) {
  return {
    context_built: "上下文组装完成",
    model_response: "模型返回结果",
    tool_call: "调用工具",
    tool_result: "工具执行结果",
    model_error: "模型调用失败",
    turn_completed: "本轮执行完成",
  }[eventType] ?? eventType;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric" }).format(new Date(value));
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "发生了未知错误";
}
