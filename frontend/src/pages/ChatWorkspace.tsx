import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { api } from "../api";
import { MemoryHub } from "../MemoryHub";
import type { MemoryHubTab } from "../MemoryHub";
import { DEFAULT_UI_PREFERENCES, useUiPreferences } from "../hooks/useUiPreferences";
import type { ThemeName, UiPreferences } from "../hooks/useUiPreferences";
import { StorySidebar } from "../components/StorySidebar";
import type {
  AgentTrace,
  AppSettings,
  AuditIssue,
  Chat,
  CharacterProfile,
  CharacterTemplate,
  Memory,
  MemoryCoverage,
  MemoryKind,
  Message,
  MessageVariant,
  NarrativeNode,
  NarrativeDelta,
  Npc,
  RetrievedMemory,
  RuntimeInfo,
  SceneNode,
  SettingsUpdate,
  StateEntry,
  StateProposal,
  StoryCharacter,
  StoryCheckpoint,
  StoryWorldBook,
  TimelineAnchor,
  WorldBookEntry,
  WorldBookTemplate,
} from "../types";

type InspectorTab = MemoryHubTab;
type LegacyInspectorTab = "state" | "memory" | "audit" | "trace";
type LibraryKind = "characters" | "world";
type SettingsTab = "model" | "generation" | "agent" | "appearance";

export default function App() {
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [chats, setChats] = useState<Chat[]>([]);
  const [selectedChatId, setSelectedChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [messageVariants, setMessageVariants] = useState<Record<string, MessageVariant[]>>({});
  const [bookmarkedIds, setBookmarkedIds] = useState<Set<string>>(new Set());
  const [checkpoints, setCheckpoints] = useState<StoryCheckpoint[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [memoryGraph, setMemoryGraph] = useState<NarrativeNode[]>([]);
  const [deltas, setDeltas] = useState<NarrativeDelta[]>([]);
  const [memoryCoverage, setMemoryCoverage] = useState<MemoryCoverage | null>(null);
  const [scenes, setScenes] = useState<SceneNode[]>([]);
  const [npcs, setNpcs] = useState<Npc[]>([]);
  const [retrieved, setRetrieved] = useState<RetrievedMemory[]>([]);
  const [stateEntries, setStateEntries] = useState<StateEntry[]>([]);
  const [proposals, setProposals] = useState<StateProposal[]>([]);
  const [audits, setAudits] = useState<AuditIssue[]>([]);
  const [traces, setTraces] = useState<AgentTrace[]>([]);
  const [timeline, setTimeline] = useState<TimelineAnchor[]>([]);
  const [activeTab, setActiveTab] = useState<InspectorTab>("summary");
  const [libraryOpen, setLibraryOpen] = useState<LibraryKind | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [characterTemplates, setCharacterTemplates] = useState<CharacterTemplate[]>([]);
  const [storyCharacters, setStoryCharacters] = useState<StoryCharacter[]>([]);
  const [worldBookTemplates, setWorldBookTemplates] = useState<WorldBookTemplate[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { preferences: uiPreferences, setPreferences: setUiPreferences } = useUiPreferences();
  const bottomRef = useRef<HTMLDivElement>(null);
  const messageListRef = useRef<HTMLElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamTimerRef = useRef<number | null>(null);
  const streamResolveRef = useRef<(() => void) | null>(null);
  const streamingRef = useRef<{ id: string; content: string } | null>(null);
  const autoScrollRef = useRef(true);
  const [showJumpToBottom, setShowJumpToBottom] = useState(false);

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
    if (autoScrollRef.current) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => {
    function onShortcut(event: KeyboardEvent) {
      if (event.key === "Escape" && sending) {
        event.preventDefault();
        void stopGeneration();
        return;
      }
      if (!event.altKey || sending) return;
      const lastAssistant = [...messages].reverse().find((item) => item.role === "assistant");
      if (!lastAssistant) return;
      if (event.key.toLowerCase() === "r") {
        event.preventDefault();
        void regenerateMessage(lastAssistant.id);
      } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        event.preventDefault();
        void selectVariant(lastAssistant.id, event.key === "ArrowLeft" ? -1 : 1);
      }
    }
    window.addEventListener("keydown", onShortcut);
    return () => window.removeEventListener("keydown", onShortcut);
  }, [messages, messageVariants, selectedChatId, sending]);

  async function initialize() {
    try {
      setLoading(true);
      const [runtimeInfo, chatList, characters, worldBooks] = await Promise.all([
        api.runtime(), api.chats(), api.characterTemplates(), api.worldBookTemplates(),
      ]);
      setRuntime(runtimeInfo);
      setChats(chatList);
      setCharacterTemplates(characters);
      setWorldBookTemplates(worldBooks);
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
      const [messageList, variantList, bookmarkList, checkpointList, storyCharacterList, memoryList, graph, coverage, deltaList, sceneList, npcList, timelineList, stateList, proposalList, auditList, traceList] =
        await Promise.all([
          api.messages(chatId),
          api.messageVariants(chatId),
          api.bookmarks(chatId),
          api.checkpoints(chatId),
          api.storyCharacters(chatId),
          api.memories(chatId),
          api.memoryGraph(chatId),
          api.memoryCoverage(chatId),
          api.narrativeDeltas(chatId),
          api.scenes(chatId),
          api.npcs(chatId),
          api.timeline(chatId),
          api.state(chatId),
          api.proposals(chatId),
          api.audits(chatId),
          api.traces(chatId),
        ]);
      setMessages(messageList);
      setMessageVariants(groupVariants(variantList));
      setBookmarkedIds(new Set(bookmarkList.filter((item) => item.bookmarked).map((item) => item.message_id)));
      setCheckpoints(checkpointList);
      setStoryCharacters(storyCharacterList);
      setMemories(memoryList);
      setMemoryGraph(graph);
      setMemoryCoverage(coverage);
      setDeltas(deltaList);
      setScenes(sceneList);
      setNpcs(npcList);
      setTimeline(timelineList);
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
    const [memoryList, graph, coverage, deltaList, sceneList, npcList, timelineList, stateList, proposalList, auditList, traceList] = await Promise.all([
      api.memories(chatId),
      api.memoryGraph(chatId),
      api.memoryCoverage(chatId),
      api.narrativeDeltas(chatId),
      api.scenes(chatId),
      api.npcs(chatId),
      api.timeline(chatId),
      api.state(chatId),
      api.proposals(chatId),
      api.audits(chatId),
      api.traces(chatId),
    ]);
    setMemories(memoryList);
    setMemoryGraph(graph);
    setMemoryCoverage(coverage);
    setDeltas(deltaList);
    setScenes(sceneList);
    setNpcs(npcList);
    setTimeline(timelineList);
    setStateEntries(stateList);
    setProposals(proposalList);
    setAudits(auditList);
    setTraces(traceList);
  }

  async function createChat(title: string, characterIds: string[], worldBookIds: string[]) {
    try {
      const chat = await api.createChat(title, characterIds, worldBookIds);
      setChats((current) => [chat, ...current]);
      setSelectedChatId(chat.id);
      setActiveTab("summary");
      setLibraryOpen(null);
      setError(null);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }

  async function deleteChat(chatId: string) {
    try {
      await api.deleteChat(chatId);
      const remaining = chats.filter((chat) => chat.id !== chatId);
      setChats(remaining);
      if (selectedChatId === chatId) {
        setSelectedChatId(remaining[0]?.id ?? null);
        setMessages([]);
        setStoryCharacters([]);
        setError(null);
      }
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!selectedChatId || !content || sending) return;

    const controller = new AbortController();
    abortControllerRef.current = controller;
    const optimisticId = `pending-${Date.now()}`;
    const streamingId = `stream-${Date.now()}`;
    let streamedContent = "";
    setSending(true);
    setDraft("");
    setError(null);
    setMessages((current) => [...current, {
      id: optimisticId,
      chat_id: selectedChatId,
      role: "user",
      content,
      created_at: new Date().toISOString(),
    }]);
    try {
      const turn = await api.streamMessage(selectedChatId, content, {
        onUser: (message) => {
          setMessages((current) => current.map((item) => item.id === optimisticId ? message : item));
        },
        onChunk: (chunk) => {
          streamedContent += chunk;
          streamingRef.current = { id: streamingId, content: streamedContent };
          setMessages((current) => {
            const exists = current.some((item) => item.id === streamingId);
            if (exists) return current.map((item) => item.id === streamingId ? { ...item, content: streamedContent } : item);
            return [...current, {
              id: streamingId,
              chat_id: selectedChatId,
              role: "assistant",
              content: streamedContent,
              created_at: new Date().toISOString(),
            }];
          });
        },
        onDone: (turn) => {
          streamingRef.current = null;
          setMessages((current) => {
            const withoutTemporary = current.filter((item) => item.id !== optimisticId && item.id !== streamingId && item.id !== turn.user_message.id);
            return [...withoutTemporary, turn.user_message, turn.assistant_message];
          });
        },
      }, controller.signal);
      abortControllerRef.current = null;
      setRetrieved(turn.retrieved_memories);
      if (turn.state_proposals.length) setActiveTab("ledger");
      if (turn.audit_issues.length) setActiveTab("diagnostics");
      await refreshInspector(selectedChatId);
    } catch (reason) {
      if (!isAbortError(reason)) {
        setDraft(content);
        setMessages((current) => current.filter((item) => item.id !== optimisticId));
        setError(errorMessage(reason));
      } else {
        streamingRef.current = null;
        await loadChat(selectedChatId);
      }
    } finally {
      abortControllerRef.current = null;
      setSending(false);
    }
  }

  function animateMessage(messageId: string, fullContent: string): Promise<void> {
    if (streamTimerRef.current !== null) window.clearInterval(streamTimerRef.current);
    streamResolveRef.current?.();
    const chunkSize = Math.max(1, Math.ceil(fullContent.length / 100));
    let offset = 0;
    streamingRef.current = { id: messageId, content: "" };
    return new Promise((resolve) => {
      streamResolveRef.current = resolve;
      streamTimerRef.current = window.setInterval(() => {
        offset = Math.min(fullContent.length, offset + chunkSize);
        const visible = fullContent.slice(0, offset);
        streamingRef.current = { id: messageId, content: visible };
        setMessages((current) => current.map((item) => item.id === messageId ? { ...item, content: visible } : item));
        if (offset >= fullContent.length) {
          if (streamTimerRef.current !== null) window.clearInterval(streamTimerRef.current);
          streamTimerRef.current = null;
          streamingRef.current = null;
          streamResolveRef.current = null;
          resolve();
        }
      }, 18);
    });
  }

  async function stopGeneration() {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    if (streamTimerRef.current !== null) {
      window.clearInterval(streamTimerRef.current);
      streamTimerRef.current = null;
      streamResolveRef.current?.();
      streamResolveRef.current = null;
      const partial = streamingRef.current;
      streamingRef.current = null;
      if (selectedChatId && partial?.content.trim()) {
        try {
          await api.updateMessage(selectedChatId, partial.id, partial.content);
          await refreshInspector(selectedChatId);
        } catch (reason) {
          setError(errorMessage(reason));
        }
      }
    }
    setSending(false);
  }

  async function regenerateMessage(messageId: string) {
    if (!selectedChatId || sending) return;
    const controller = new AbortController();
    abortControllerRef.current = controller;
    setSending(true);
    setError(null);
    try {
      const variant = await api.regenerateMessage(selectedChatId, messageId, controller.signal);
      abortControllerRef.current = null;
      setMessages((current) => current.map((item) => item.id === messageId ? { ...item, content: "" } : item));
      setMessageVariants(groupVariants(await api.messageVariants(selectedChatId)));
      await animateMessage(messageId, variant.content);
      await refreshInspector(selectedChatId);
    } catch (reason) {
      if (!isAbortError(reason)) setError(errorMessage(reason));
      else await loadChat(selectedChatId);
    } finally {
      abortControllerRef.current = null;
      setSending(false);
    }
  }

  async function selectVariant(messageId: string, direction: -1 | 1) {
    if (!selectedChatId || sending) return;
    const variants = messageVariants[messageId] ?? [];
    const currentIndex = variants.findIndex((item) => item.selected);
    const next = variants[currentIndex + direction];
    if (!next) return;
    try {
      const message = await api.selectMessageVariant(selectedChatId, messageId, next.id);
      setMessages((current) => current.map((item) => item.id === messageId ? message : item));
      setMessageVariants((current) => ({
        ...current,
        [messageId]: variants.map((item) => ({ ...item, selected: item.id === next.id })),
      }));
      await refreshInspector(selectedChatId);
    } catch (reason) { setError(errorMessage(reason)); }
  }

  async function removeMessage(messageId: string) {
    if (!selectedChatId || !window.confirm("删除这条消息以及之后的剧情？")) return;
    try {
      await api.deleteMessage(selectedChatId, messageId);
      await loadChat(selectedChatId);
    } catch (reason) { setError(errorMessage(reason)); }
  }

  async function toggleBookmark(messageId: string) {
    if (!selectedChatId) return;
    try {
      const result = await api.toggleBookmark(selectedChatId, messageId);
      setBookmarkedIds((current) => {
        const next = new Set(current);
        if (result.bookmarked) next.add(messageId); else next.delete(messageId);
        return next;
      });
    } catch (reason) { setError(errorMessage(reason)); }
  }

  async function createBranch(messageId: string) {
    if (!selectedChatId) return;
    try {
      const branch = await api.createBranch(selectedChatId, messageId);
      setChats((current) => [branch, ...current]);
      setSelectedChatId(branch.id);
    } catch (reason) { setError(errorMessage(reason)); }
  }

  async function createCheckpoint(messageId: string) {
    if (!selectedChatId) return;
    const name = window.prompt("检查点名称", `检查点 ${checkpoints.length + 1}`)?.trim();
    if (!name) return;
    try {
      const checkpoint = await api.createCheckpoint(selectedChatId, messageId, name);
      setCheckpoints((current) => [checkpoint, ...current]);
    } catch (reason) { setError(errorMessage(reason)); }
  }

  async function restoreCheckpoint(checkpointId: string) {
    if (!selectedChatId) return;
    try {
      const branch = await api.restoreCheckpoint(selectedChatId, checkpointId);
      setChats((current) => [branch, ...current]);
      setSelectedChatId(branch.id);
    } catch (reason) { setError(errorMessage(reason)); }
  }

  async function editMessage(messageId: string, content: string) {
    if (!selectedChatId) return;
    try {
      const updated = await api.updateMessage(selectedChatId, messageId, content);
      setMessages((current) => current.map((item) => item.id === messageId ? updated : item));
      await refreshInspector(selectedChatId);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }

  return (
    <div
      className={`app-shell theme-${uiPreferences.theme}${uiPreferences.compactMessages ? " compact-messages" : ""}${uiPreferences.reduceMotion ? " reduce-motion" : ""}`}
      style={{ "--font-scale": uiPreferences.fontScale } as CSSProperties}
    >
      <StorySidebar
        chats={chats}
        selectedChatId={selectedChatId}
        characterTemplates={characterTemplates}
        worldBookTemplates={worldBookTemplates}
        onSelect={(id) => { setSelectedChatId(id); setLibraryOpen(null); }}
        onCreate={createChat}
        onDelete={deleteChat}
      />

      <main className="conversation-pane">
        <header className="topbar">
          <div className="story-heading">
            <p className="eyebrow">当前故事</p>
            <h1>{selectedChat?.title ?? "选择或创建一个故事"}</h1>
          </div>
          <GlobalNav onOpen={setLibraryOpen} />
          <div className="topbar-actions">
            <details className="checkpoint-menu">
              <summary>检查点</summary>
              <div>
                {checkpoints.length === 0 ? <span>还没有检查点</span> : checkpoints.map((item) => (
                  <button key={item.id} onClick={() => void restoreCheckpoint(item.id)}>{item.name}</button>
                ))}
              </div>
            </details>
            <div className={`provider-badge ${runtime?.provider_mode === "demo" ? "demo" : "live"}`}>
              <span className="status-dot" />
              {runtime?.provider_mode === "demo"
                ? "演示模式"
                : runtime?.model ?? "模型已连接"}
            </div>
            <button className="settings-button" onClick={() => setSettingsOpen(true)} aria-label="打开设置">
              ⚙ <span>设置</span>
            </button>
            <button className={`settings-button ${inspectorOpen ? "active" : ""}`} onClick={() => setInspectorOpen((value) => !value)} aria-expanded={inspectorOpen}>
              ◫ <span>故事资料</span>
            </button>
          </div>
        </header>

        {error && <div className="error-banner">{error}</div>}

        <section
          className="message-list"
          ref={messageListRef}
          onScroll={(event) => {
            const element = event.currentTarget;
            const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 100;
            autoScrollRef.current = nearBottom;
            setShowJumpToBottom(!nearBottom);
          }}
        >
          {!selectedChatId ? (
            <EmptyState title="还没有故事" detail="从左侧新建一个故事。" />
          ) : loading && messages.length === 0 ? (
            <EmptyState title="正在载入…" detail="" />
          ) : messages.length === 0 ? (
            <EmptyState title="故事尚未开始" detail="在下方写下第一句话。" />
          ) : (
            messages.map((message) => <MessageBubble
              key={message.id}
              message={message}
              character={storyCharacters[0] ?? null}
              userAvatar={uiPreferences.userAvatar}
              variants={messageVariants[message.id] ?? []}
              bookmarked={bookmarkedIds.has(message.id)}
              busy={sending}
              onEdit={editMessage}
              onDelete={removeMessage}
              onBookmark={toggleBookmark}
              onRegenerate={regenerateMessage}
              onVariant={selectVariant}
              onBranch={createBranch}
              onCheckpoint={createCheckpoint}
            />)
          )}
          {sending && !messages.some((item) => item.id.startsWith("stream-")) && (
            <div className="message-row assistant">
              <Avatar value={storyCharacters[0]?.avatar ?? ""} fallback={(storyCharacters[0]?.name ?? "S").charAt(0)} />
              <div className="bubble thinking"><i /><i /><i /></div>
            </div>
          )}
          <div ref={bottomRef} />
        </section>

        {showJumpToBottom && <button className="jump-bottom" onClick={() => {
          autoScrollRef.current = true;
          setShowJumpToBottom(false);
          bottomRef.current?.scrollIntoView({ behavior: "smooth" });
        }}>回到底部 ↓</button>}

        <form className="composer" onSubmit={sendMessage}>
          <button type="button" className="composer-memory" onClick={() => setInspectorOpen(true)} disabled={!selectedChatId} aria-label="打开故事资料" title="故事资料">◫</button>
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
            rows={1}
          />
          <div className="composer-footer">
            <span>Enter 发送 · Shift + Enter 换行</span>
            {sending ? (
              <button type="button" className="primary-button stop-button" onClick={() => void stopGeneration()}>
                <span>停止</span><b>■</b>
              </button>
            ) : (
              <button className="primary-button" disabled={!draft.trim() || !selectedChatId}>
                <span>发送</span><b>↑</b>
              </button>
            )}
          </div>
        </form>
      </main>

      <div className={`drawer-backdrop ${inspectorOpen ? "open" : ""}`} onMouseDown={(event) => { if (event.target === event.currentTarget) setInspectorOpen(false); }}>
      <MemoryHub
        chatId={selectedChatId}
        activeTab={activeTab}
        onTab={setActiveTab}
        memories={memories}
        memoryGraph={memoryGraph}
        deltas={deltas}
        coverage={memoryCoverage}
        scenes={scenes}
        npcs={npcs}
        retrieved={retrieved}
        timeline={timeline}
        stateEntries={stateEntries}
        proposals={proposals}
        audits={audits}
        traces={traces}
        onRefresh={() => {
          if (selectedChatId) return refreshInspector(selectedChatId);
        }}
        onError={(reason) => setError(errorMessage(reason))}
        onClose={() => setInspectorOpen(false)}
      />
      </div>
      {libraryOpen && (
        <LibraryWorkspace
          page={libraryOpen}
          onClose={() => setLibraryOpen(null)}
          selectedChat={selectedChat}
          characterTemplates={characterTemplates}
          worldBookTemplates={worldBookTemplates}
          onCharacters={setCharacterTemplates}
          onStoryCharacters={setStoryCharacters}
          onWorldBooks={setWorldBookTemplates}
          onError={(reason) => setError(errorMessage(reason))}
          error={error}
        />
      )}
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

function GlobalNav({ onOpen }: { onOpen: (page: LibraryKind) => void }) {
  return (
    <nav className="global-nav" aria-label="主导航">
      <button onClick={() => onOpen("characters")}><i>♟</i><span>角色</span></button>
      <button onClick={() => onOpen("world")}><i>◇</i><span>世界书</span></button>
    </nav>
  );
}

function LibraryWorkspace(props: {
  page: LibraryKind;
  onClose: () => void;
  selectedChat: Chat | null;
  characterTemplates: CharacterTemplate[];
  worldBookTemplates: WorldBookTemplate[];
  onCharacters: (items: CharacterTemplate[]) => void;
  onStoryCharacters: (items: StoryCharacter[]) => void;
  onWorldBooks: (items: WorldBookTemplate[]) => void;
  onError: (reason: unknown) => void;
  error: string | null;
}) {
  return (
    <div className="library-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) props.onClose(); }}>
    <main className="library-workspace" role="dialog" aria-modal="true" aria-label={props.page === "characters" ? "角色" : "世界书"}>
      <header className="topbar library-topbar">
        <div><p className="eyebrow">故事设定</p><h1>{props.page === "characters" ? "角色" : "世界书"}</h1></div>
        <button className="icon-button" onClick={props.onClose} aria-label="关闭">×</button>
      </header>
      {props.error && <div className="error-banner">{props.error}</div>}
      {props.page === "characters" ? (
        <CharacterLibrary
          selectedChat={props.selectedChat}
          templates={props.characterTemplates}
          onTemplates={props.onCharacters}
          onStoryItems={props.onStoryCharacters}
          onError={props.onError}
        />
      ) : (
        <WorldLibrary
          selectedChat={props.selectedChat}
          templates={props.worldBookTemplates}
          onTemplates={props.onWorldBooks}
          onError={props.onError}
        />
      )}
    </main>
    </div>
  );
}

const EMPTY_CHARACTER = { name: "", identity: "", personality: "", speaking_style: "", scenario: "", avatar: "" };

function CharacterLibrary(props: {
  selectedChat: Chat | null;
  templates: CharacterTemplate[];
  onTemplates: (items: CharacterTemplate[]) => void;
  onStoryItems: (items: StoryCharacter[]) => void;
  onError: (reason: unknown) => void;
}) {
  const [storyItems, setStoryItems] = useState<StoryCharacter[]>([]);
  const [editing, setEditing] = useState<{ scope: "template" | "story"; id: string | null } | null>(null);
  const [draft, setDraft] = useState(EMPTY_CHARACTER);

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
    try { await api.attachCharacter(props.selectedChat.id, id); await refreshStory(); }
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

  return (
    <div className="library-content">
      <LibraryColumn title="角色库" note="这里的角色可以添加到多个故事。" action="＋ 新建角色" onAction={() => edit("template")}>
        {props.templates.length === 0 ? <p className="muted">还没有角色模板。</p> : props.templates.map((item) => (
          <LibraryCard key={item.id} title={item.name} detail={item.identity || item.personality || "暂无补充设定"} badge="模板" avatar={item.avatar}>
            <button onClick={() => attach(item.id)} disabled={!props.selectedChat}>添加到故事</button>
            <button onClick={() => edit("template", item)}>编辑</button>
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
      {editing && <CharacterEditor draft={draft} onDraft={setDraft} scope={editing.scope} onSubmit={save} onCancel={() => setEditing(null)} />}
    </div>
  );
}

function CharacterEditor(props: {
  draft: typeof EMPTY_CHARACTER;
  onDraft: (value: typeof EMPTY_CHARACTER) => void;
  scope: "template" | "story";
  onSubmit: (event: FormEvent) => void;
  onCancel: () => void;
}) {
  const set = (key: keyof typeof EMPTY_CHARACTER, value: string) => props.onDraft({ ...props.draft, [key]: value });
  return (
    <form className="library-editor" onSubmit={props.onSubmit}>
      <div className="action-heading"><h3>{props.scope === "template" ? "编辑角色" : "编辑当前故事中的角色"}</h3><button type="button" onClick={props.onCancel}>关闭</button></div>
      <AvatarPicker value={props.draft.avatar} fallback={props.draft.name.charAt(0) || "角"} onChange={(value) => set("avatar", value)} />
      <input value={props.draft.name} onChange={(e) => set("name", e.target.value)} placeholder="角色名" autoFocus />
      <textarea value={props.draft.identity} onChange={(e) => set("identity", e.target.value)} placeholder="身份与背景" rows={3} />
      <textarea value={props.draft.personality} onChange={(e) => set("personality", e.target.value)} placeholder="性格" rows={3} />
      <textarea value={props.draft.speaking_style} onChange={(e) => set("speaking_style", e.target.value)} placeholder="说话风格" rows={2} />
      <textarea value={props.draft.scenario} onChange={(e) => set("scenario", e.target.value)} placeholder="当前情境" rows={3} />
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
  const [editing, setEditing] = useState<{ scope: "template" | "story"; id: string | null } | null>(null);
  const [draft, setDraft] = useState<WorldEntryDraft>(EMPTY_WORLD_ENTRY);
  async function refreshStory() { setStoryItems(props.selectedChat ? await api.storyWorldBooks(props.selectedChat.id) : []); }
  useEffect(() => { void refreshStory().catch(props.onError); }, [props.selectedChat?.id]);

  function edit(scope: "template" | "story", item?: WorldBookTemplate | StoryWorldBook) {
    setEditing({ scope, id: item?.id ?? null });
    setDraft(item ? { title: item.title, keywords: item.keywords.join("，"), content: item.content, priority: item.priority, enabled: item.enabled } : EMPTY_WORLD_ENTRY);
  }
  const payload = () => ({
    title: draft.title.trim(), content: draft.content.trim(), priority: draft.priority, enabled: draft.enabled,
    keywords: draft.keywords.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean),
  });
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
    try { await api.attachWorldBook(props.selectedChat.id, id); await refreshStory(); }
    catch (reason) { props.onError(reason); }
  }
  async function remove(scope: "template" | "story", id: string) {
    try {
      if (scope === "template") { await api.deleteWorldBookTemplate(id); props.onTemplates(await api.worldBookTemplates()); }
      else if (props.selectedChat) { await api.deleteStoryWorldBook(props.selectedChat.id, id); await refreshStory(); }
    } catch (reason) { props.onError(reason); }
  }
  return (
    <div className="library-content">
      <LibraryColumn title="世界书库" note="这里保存可以重复使用的世界设定。" action="＋ 新建世界书" onAction={() => edit("template")}>
        {props.templates.length === 0 ? <p className="muted">还没有世界书模板。</p> : props.templates.map((item) => (
          <LibraryCard key={item.id} title={item.title} detail={item.content} badge={`模板 · 优先级 ${item.priority}`}>
            <button onClick={() => attach(item.id)} disabled={!props.selectedChat}>添加到故事</button><button onClick={() => edit("template", item)}>编辑</button><button className="delete-button" onClick={() => void remove("template", item.id)}>删除</button>
          </LibraryCard>
        ))}
      </LibraryColumn>
      <LibraryColumn title={`当前故事使用的世界书${props.selectedChat ? ` · ${props.selectedChat.title}` : ""}`} note="这里的修改只影响当前故事。">
        {!props.selectedChat ? <p className="muted">请先从左侧选择一个故事。</p> : storyItems.length === 0 ? <p className="muted">这个故事尚未绑定世界书。</p> : storyItems.map((item) => (
          <LibraryCard key={item.id} title={item.title} detail={item.content} badge={item.source_template_id ? "当前故事" : "已有设定"}>
            <button onClick={() => edit("story", item)}>编辑</button><button className="delete-button" onClick={() => void remove("story", item.id)}>移除</button>
          </LibraryCard>
        ))}
      </LibraryColumn>
      {editing && (
        <form className="library-editor" onSubmit={save}>
          <div className="action-heading"><h3>{editing.scope === "template" ? "编辑世界书" : "编辑当前故事的世界书"}</h3><button type="button" onClick={() => setEditing(null)}>关闭</button></div>
          <input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} placeholder="标题" autoFocus />
          <input value={draft.keywords} onChange={(e) => setDraft({ ...draft, keywords: e.target.value })} placeholder="触发词，用逗号分隔；留空表示常驻" />
          <textarea value={draft.content} onChange={(e) => setDraft({ ...draft, content: e.target.value })} placeholder="世界设定" rows={6} />
          <div className="world-form-row"><label><span>优先级</span><input type="number" min={0} max={100} value={draft.priority} onChange={(e) => setDraft({ ...draft, priority: Number(e.target.value) })} /></label><label className="inline-check"><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />启用</label></div>
          <button className="primary-button">保存</button>
        </form>
      )}
    </div>
  );
}

function LibraryColumn(props: { title: string; note: string; action?: string; onAction?: () => void; children: ReactNode }) {
  return <section className="library-column"><div className="library-column-heading"><div><h2>{props.title}</h2><p>{props.note}</p></div>{props.action && <button onClick={props.onAction}>{props.action}</button>}</div><div className="library-card-list">{props.children}</div></section>;
}

function LibraryCard(props: { title: string; detail: string; badge: string; avatar?: string; children: ReactNode }) {
  return <article className="library-card"><header>{props.avatar !== undefined && <Avatar value={props.avatar} fallback={props.title.charAt(0)} />}<div><strong>{props.title}</strong><span>{props.badge}</span></div></header><p>{props.detail}</p><footer>{props.children}</footer></article>;
}

function MessageBubble({ message, character, userAvatar, variants, bookmarked, busy, onEdit, onDelete, onBookmark, onRegenerate, onVariant, onBranch, onCheckpoint }: {
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
}) {
  const assistant = message.role === "assistant";
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState(message.content);
  useEffect(() => setContent(message.content), [message.content]);
  const selectedVariant = variants.findIndex((item) => item.selected);
  const pending = message.id.startsWith("pending-");
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!content.trim()) return;
    await onEdit(message.id, content.trim());
    setEditing(false);
  }
  return (
    <div className={`message-row ${assistant ? "assistant" : "user"}`}>
      <Avatar value={assistant ? character?.avatar ?? "" : userAvatar} fallback={assistant ? (character?.name ?? "S").charAt(0) : "你"} />
      <div className="message-column">
        <div className="message-meta">{assistant ? character?.name ?? "Saraswati" : "你"}<span>{formatTime(message.created_at)}{bookmarked && " · 已收藏"}</span></div>
        {editing ? <form className="message-editor" onSubmit={save}><textarea value={content} onChange={(event) => setContent(event.target.value)} rows={5} /><footer><button type="button" onClick={() => setEditing(false)}>取消</button><button>保存修改</button></footer></form> : <div className="bubble">{message.content}</div>}
        {!editing && !pending && <div className="message-toolbar">
          {assistant && variants.length > 1 && <span className="variant-switcher">
            <button disabled={busy || selectedVariant <= 0} onClick={() => void onVariant(message.id, -1)}>‹</button>
            {selectedVariant + 1}/{variants.length}
            <button disabled={busy || selectedVariant >= variants.length - 1} onClick={() => void onVariant(message.id, 1)}>›</button>
          </span>}
          <button disabled={busy} onClick={() => { setContent(message.content); setEditing(true); }}>编辑</button>
          <button onClick={() => void navigator.clipboard.writeText(message.content)}>复制</button>
          <button className={bookmarked ? "active" : ""} onClick={() => void onBookmark(message.id)}>{bookmarked ? "取消收藏" : "收藏"}</button>
          {assistant && <button disabled={busy} onClick={() => void onRegenerate(message.id)}>重生成</button>}
          <button onClick={() => void onCheckpoint(message.id)}>检查点</button>
          <button onClick={() => void onBranch(message.id)}>创建分支</button>
          <button className="danger" disabled={busy} onClick={() => void onDelete(message.id)}>删除</button>
        </div>}
      </div>
    </div>
  );
}

function Avatar({ value, fallback }: { value: string; fallback: string }) {
  return <div className={`avatar${value ? " has-image" : ""}`}>{value ? <img src={value} alt="" /> : fallback}</div>;
}

function AvatarPicker({ value, fallback, onChange }: { value: string; fallback: string; onChange: (value: string) => void }) {
  const [fileError, setFileError] = useState("");
  async function choose(file: File | undefined) {
    if (!file) return;
    if (!file.type.startsWith("image/")) { setFileError("请选择图片文件"); return; }
    if (file.size > 1_500_000) { setFileError("图片不能超过 1.5 MB"); return; }
    setFileError("");
    onChange(await fileToDataUrl(file));
  }
  return <div className="avatar-picker"><Avatar value={value} fallback={fallback} /><div><label>选择图片<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={(event) => void choose(event.target.files?.[0])} /></label>{value && <button type="button" onClick={() => onChange("")}>移除</button>}{fileError && <small>{fileError}</small>}</div></div>;
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function Inspector(props: {
  chatId: string | null;
  activeTab: LegacyInspectorTab;
  onTab: (tab: LegacyInspectorTab) => void;
  memories: Memory[];
  retrieved: RetrievedMemory[];
  stateEntries: StateEntry[];
  proposals: StateProposal[];
  audits: AuditIssue[];
  traces: AgentTrace[];
  onRefresh: () => Promise<void> | void;
  onError: (reason: unknown) => void;
}) {
  const tabs: { id: LegacyInspectorTab; label: string; count?: number }[] = [
    { id: "state", label: "状态", count: props.proposals.filter((item) => item.status === "pending").length },
    { id: "memory", label: "记忆", count: props.memories.length },
    { id: "audit", label: "审计", count: props.audits.filter((item) => item.status === "open").length },
    { id: "trace", label: "轨迹" },
  ];

  return (
    <aside className="inspector">
      <div className="inspector-title"><span>运行记录</span></div>
      <div className="tabs">
        {tabs.map((tab) => (
          <button key={tab.id} className={props.activeTab === tab.id ? "active" : ""} onClick={() => props.onTab(tab.id)}>
            {tab.label}{Boolean(tab.count) && <em>{tab.count}</em>}
          </button>
        ))}
      </div>
      <div className="inspector-content">
        {!props.chatId ? (
          <EmptyState title="暂无数据" detail="请先选择故事。" />
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
      <div className="action-heading"><PanelHeading title="世界书" note="有关键词的设定会在聊到相关内容时使用；未填写关键词的设定会一直生效" /><button onClick={startCreate}>＋ 新建设定</button></div>
      {showForm && (
        <form className="world-entry-form" onSubmit={save}>
          <input value={draft.title} onChange={(e) => setDraft((value) => ({ ...value, title: e.target.value }))} placeholder="词条标题" autoFocus />
          <input value={draft.keywords} onChange={(e) => setDraft((value) => ({ ...value, keywords: e.target.value }))} placeholder="触发关键词，用逗号分隔；留空表示常驻" />
          <textarea value={draft.content} onChange={(e) => setDraft((value) => ({ ...value, content: e.target.value }))} placeholder="世界设定" rows={6} />
          <div className="world-form-row"><label><span>优先级</span><input type="number" min={0} max={100} value={draft.priority} onChange={(e) => setDraft((value) => ({ ...value, priority: Number(e.target.value) }))} /></label><label className="inline-check"><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft((value) => ({ ...value, enabled: e.target.checked }))} /> 启用</label></div>
          <footer><button type="button" onClick={() => setShowForm(false)}>取消</button><button className="primary-button">{editingId ? "保存修改" : "创建词条"}</button></footer>
        </form>
      )}
      {entries.length === 0 && !showForm ? <p className="muted">暂无世界书词条。</p> : entries.map((entry) => (
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
      {pending.length === 0 ? <p className="muted">暂无待确认修改。</p> : pending.map((item) => (
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
      <PanelHeading title="运行记录" note="上下文、模型和工具调用" />
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
  return <div className="empty-state"><div>✦</div><h2>{title}</h2>{detail && <p>{detail}</p>}</div>;
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
  const [rerankApiKey, setRerankApiKey] = useState("");
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
        rerank_api_key: rerankApiKey.trim() || null,
      });
      const runtimeInfo = await api.runtime();
      setCurrent(saved);
      setForm(settingsToUpdate(saved));
      setApiKey("");
      setRerankApiKey("");
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
      rerank_candidates: 20,
      context_window_tokens: 32768,
    });
    setDraftPreferences(DEFAULT_UI_PREFERENCES);
    setNotice({ kind: "ok", text: "已恢复推荐值，点击“保存并应用”后生效。" });
  }

  const tabs: { id: SettingsTab; label: string }[] = [
    { id: "model", label: "模型 API" },
    { id: "generation", label: "生成参数" },
    { id: "agent", label: "对话与记忆" },
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
                <SettingsHeading title="对话与记忆" detail="" />
                <NumberSetting label="最大处理步数" note="模型与工具的往返上限" value={form.max_agent_steps} min={1} max={12} step={1} onChange={(value) => updateField("max_agent_steps", Math.round(value))} />
                <NumberSetting label="近期原文条数" note="直接放入上下文的最近消息数量" value={form.recent_message_limit} min={2} max={100} step={2} onChange={(value) => updateField("recent_message_limit", Math.round(value))} />
                <NumberSetting label="相关回忆数量" note="每轮最多带回多少条旧剧情" value={form.rag_limit} min={1} max={30} step={1} onChange={(value) => updateField("rag_limit", Math.round(value))} />
                <div className="subsection-title"><strong>自动记忆整理</strong><small>每轮摘要，并按阈值逐级压缩</small></div>
                <label className="check-row"><input type="checkbox" checked={form.auto_summary_enabled} onChange={(e) => updateField("auto_summary_enabled", e.target.checked)} /><span><strong>启用自动摘要</strong><small>每次角色回复后额外调用一次模型整理楼层摘要</small></span></label>
                <label className="settings-field"><span>默认摘要模式</span><small>详细模式信息更全，但消耗更多 Token</small><select value={form.summary_detail_mode} onChange={(e) => updateField("summary_detail_mode", e.target.value as "brief" | "detailed")}><option value="brief">精简</option><option value="detailed">详细</option></select></label>
                <div className="settings-grid"><NumberSetting label="每章楼层数" note="累计多少条楼层摘要后生成章节总结" value={form.chapter_summary_size} min={2} max={50} step={1} onChange={(value) => updateField("chapter_summary_size", Math.round(value))} compact /><NumberSetting label="每篇章节数" note="累计多少章后生成篇章概览" value={form.arc_summary_size} min={2} max={20} step={1} onChange={(value) => updateField("arc_summary_size", Math.round(value))} compact /></div>
                <div className="subsection-title"><strong>混合 RAG 权重</strong><small>系统会自动按总和归一化 · 当前总和 {weightTotal.toFixed(2)}</small></div>
                <div className="settings-grid">
                  <NumberSetting label="向量语义" note="意思是否相近" value={form.vector_weight} min={0} max={1} step={0.05} onChange={(value) => updateField("vector_weight", value)} compact />
                  <NumberSetting label="关键词" note="字面线索重合" value={form.keyword_weight} min={0} max={1} step={0.05} onChange={(value) => updateField("keyword_weight", value)} compact />
                  <NumberSetting label="记忆重要度" note="记录本身的重要程度" value={form.importance_weight} min={0} max={1} step={0.05} onChange={(value) => updateField("importance_weight", value)} compact />
                  <NumberSetting label="时间新鲜度" note="近期记忆略微优先" value={form.recency_weight} min={0} max={1} step={0.05} onChange={(value) => updateField("recency_weight", value)} compact />
                </div>
                {weightTotal <= 0 && <p className="field-error">至少有一项 RAG 权重必须大于 0。</p>}
                <div className="subsection-title"><strong>独立 Reranker</strong><small>兼容 Cohere/Jina 风格的 /rerank 接口；未配置时自动跳过</small></div>
                <label className="settings-field"><span>Rerank API 地址</span><small>可以填写服务根地址，也可以直接填写以 /rerank 结尾的地址</small><input value={form.rerank_base_url ?? ""} onChange={(e) => updateField("rerank_base_url", e.target.value || null)} placeholder="https://api.example.com/v1" /></label>
                <div className="settings-grid"><label className="settings-field"><span>Rerank 模型</span><input value={form.rerank_model ?? ""} onChange={(e) => updateField("rerank_model", e.target.value || null)} placeholder="reranker-model" /></label><label className="settings-field"><span>Rerank API Key</span><small>{current.rerank_api_key_configured ? `已保存：${current.rerank_api_key_hint}；留空保持不变` : "尚未配置"}</small><input type="password" value={rerankApiKey} onChange={(e) => { setRerankApiKey(e.target.value); if (e.target.value) updateField("clear_rerank_api_key", false); }} placeholder="可与对话模型使用不同密钥" /></label></div>
                {current.rerank_api_key_configured && <label className="check-row danger-check"><input type="checkbox" checked={form.clear_rerank_api_key} onChange={(e) => updateField("clear_rerank_api_key", e.target.checked)} /><span>保存时删除 Rerank API Key</span></label>}
                <NumberSetting label="精排候选数" note="混合初排后送给 reranker 的候选数量" value={form.rerank_candidates} min={2} max={100} step={1} onChange={(value) => updateField("rerank_candidates", Math.round(value))} />
                <NumberSetting label="上下文窗口" note="模型支持的总 Token 数；系统会为输出预留 max tokens" value={form.context_window_tokens} min={4096} max={2000000} step={1024} onChange={(value) => updateField("context_window_tokens", Math.round(value))} />
              </div>
            ) : (
              <div className="settings-section">
                <SettingsHeading title="界面" />
                <div className="settings-field"><span>用户头像</span><AvatarPicker value={draftPreferences.userAvatar} fallback="你" onChange={(value) => setDraftPreferences((before) => ({ ...before, userAvatar: value }))} /></div>
                <label className="settings-field"><span>配色主题</span><select value={draftPreferences.theme} onChange={(e) => setDraftPreferences((value) => ({ ...value, theme: e.target.value as ThemeName }))}><option value="ink">墨黑金色</option><option value="midnight">深夜蓝色</option></select></label>
                <NumberSetting label="文字缩放" value={draftPreferences.fontScale} min={0.85} max={1.25} step={0.05} onChange={(value) => setDraftPreferences((before) => ({ ...before, fontScale: value }))} />
                <label className="check-row"><input type="checkbox" checked={draftPreferences.compactMessages} onChange={(e) => setDraftPreferences((value) => ({ ...value, compactMessages: e.target.checked }))} /><span><strong>紧凑消息间距</strong></span></label>
                <label className="check-row"><input type="checkbox" checked={draftPreferences.reduceMotion} onChange={(e) => setDraftPreferences((value) => ({ ...value, reduceMotion: e.target.checked }))} /><span><strong>减少动画</strong></span></label>
                <details className="privacy-note"><summary>数据与隐私</summary><p>聊天数据：<code>data/saraswati_v1.db</code></p><p>模型设置：<code>data/settings.json</code></p><p>API Key 保存在本机，请勿分享设置文件。</p></details>
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

function SettingsHeading({ title, detail }: { title: string; detail?: string }) {
  return <div className="settings-heading"><h3>{title}</h3>{detail && <p>{detail}</p>}</div>;
}

function NumberSetting({ label, note, value, min, max, step, onChange, compact = false }: {
  label: string;
  note?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  compact?: boolean;
}) {
  return (
    <label className={`number-setting${compact ? " compact" : ""}`}>
      <span><strong>{label}</strong>{note && <small>{note}</small>}</span>
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
    auto_summary_enabled: settings.auto_summary_enabled,
    summary_detail_mode: settings.summary_detail_mode,
    chapter_summary_size: settings.chapter_summary_size,
    arc_summary_size: settings.arc_summary_size,
    rerank_base_url: settings.rerank_base_url,
    rerank_api_key: null,
    clear_rerank_api_key: false,
    rerank_model: settings.rerank_model,
    rerank_candidates: settings.rerank_candidates,
    context_window_tokens: settings.context_window_tokens,
  };
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

function groupVariants(items: MessageVariant[]): Record<string, MessageVariant[]> {
  return items.reduce<Record<string, MessageVariant[]>>((groups, item) => {
    (groups[item.message_id] ??= []).push(item);
    return groups;
  }, {});
}

function isAbortError(reason: unknown) {
  return reason instanceof DOMException && reason.name === "AbortError";
}

function errorMessage(reason: unknown) {
  return reason instanceof Error ? reason.message : "发生了未知错误";
}
