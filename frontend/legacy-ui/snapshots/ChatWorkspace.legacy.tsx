/*
 * Archived snapshot before legacy inspector extraction.
 * This file is outside frontend/src and is not part of the production build.
 */

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { MemoryHub } from "../MemoryHub";
import type { MemoryHubTab } from "../MemoryHub";
import { useUiPreferences } from "../hooks/useUiPreferences";
import { StorySidebar } from "../components/StorySidebar";
import { Avatar } from "../components/Avatar";
import { MessageBubble } from "../components/MessageBubble";
import { SettingsModal } from "../components/SettingsModal";
import { ClassicalIcon } from "../components/ClassicalIcon";
import { GlobalNav, LibraryWorkspace } from "../components/LibraryWorkspace";
import type { LibraryKind } from "../components/LibraryWorkspace";
import { EMPTY_WORLD_ENTRY, worldEntryToDraft } from "../utils/worldBookDraft";
import type { WorldEntryDraft } from "../utils/worldBookDraft";
import goyaSleepOfReason from "../assets/empty-states/goya-sleep-of-reason.jpg";
import durerMelencolia from "../assets/empty-states/durer-melencolia.jpg";
import durerSaintJerome from "../assets/empty-states/durer-saint-jerome.jpg";
import composerRuleTopLeft from "../assets/ornaments/composer-rule-top-left.png";
import composerRuleTopCenter from "../assets/ornaments/composer-rule-top-center.png";
import composerRuleTopRight from "../assets/ornaments/composer-rule-top-right.png";
import composerRuleBottomLeft from "../assets/ornaments/composer-rule-bottom-left.png";
import composerRuleBottomCenter from "../assets/ornaments/composer-rule-bottom-center.png";
import composerRuleBottomRight from "../assets/ornaments/composer-rule-bottom-right.png";
import {
  bootstrapQueryOptions,
  chatSnapshotQueryOptions,
  useChatSnapshot,
  useWorkspaceBootstrap,
} from "../hooks/useWorkspaceQueries";
import type { ChatSnapshot } from "../hooks/useWorkspaceQueries";
import type {
  AgentTrace,
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
  PersonaTemplate,
  RetrievedMemory,
  RuntimeInfo,
  SceneNode,
  StateEntry,
  StateProposal,
  StoryCharacter,
  StoryPersona,
  StoryCheckpoint,
  TimelineAnchor,
  WorldBookEntry,
  WorldBookTemplate,
  WorldEngineSnapshot,
} from "../types";

type InspectorTab = MemoryHubTab;
type LegacyInspectorTab = "state" | "memory" | "audit" | "trace";
type ApiConnectionState = "unconfigured" | "checking" | "connected" | "error";

export default function App() {
  const queryClient = useQueryClient();
  const bootstrapQuery = useWorkspaceBootstrap();
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null);
  const [apiConnection, setApiConnection] = useState<ApiConnectionState>("checking");
  const [apiConnectionDetail, setApiConnectionDetail] = useState("正在读取模型配置");
  const [apiCheckRevision, setApiCheckRevision] = useState(0);
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
  const [worldEngine, setWorldEngine] = useState<WorldEngineSnapshot | null>(null);
  const [scenes, setScenes] = useState<SceneNode[]>([]);
  const [npcs, setNpcs] = useState<Npc[]>([]);
  const [retrieved, setRetrieved] = useState<RetrievedMemory[]>([]);
  const [stateEntries, setStateEntries] = useState<StateEntry[]>([]);
  const [proposals, setProposals] = useState<StateProposal[]>([]);
  const [audits, setAudits] = useState<AuditIssue[]>([]);
  const [traces, setTraces] = useState<AgentTrace[]>([]);
  const [timeline, setTimeline] = useState<TimelineAnchor[]>([]);
  const [activeTab, setActiveTab] = useState<InspectorTab>("overview");
  const [libraryOpen, setLibraryOpen] = useState<LibraryKind | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [characterTemplates, setCharacterTemplates] = useState<CharacterTemplate[]>([]);
  const [storyCharacters, setStoryCharacters] = useState<StoryCharacter[]>([]);
  const [worldBookTemplates, setWorldBookTemplates] = useState<WorldBookTemplate[]>([]);
  const [personaTemplates, setPersonaTemplates] = useState<PersonaTemplate[]>([]);
  const [storyPersona, setStoryPersona] = useState<StoryPersona | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [sendPhase, setSendPhase] = useState<"idle" | "generating" | "postprocessing">("idle");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorFading, setErrorFading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { preferences: uiPreferences, setPreferences: setUiPreferences } = useUiPreferences();
  const bottomRef = useRef<HTMLDivElement>(null);
  const messageListRef = useRef<HTMLElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamTimerRef = useRef<number | null>(null);
  const streamResolveRef = useRef<(() => void) | null>(null);
  const streamingRef = useRef<{ id: string; content: string } | null>(null);
  const connectionHintTimerRef = useRef<number | null>(null);
  const connectionHintFadeTimerRef = useRef<number | null>(null);
  const autoScrollRef = useRef(true);
  const [showJumpToBottom, setShowJumpToBottom] = useState(false);
  const chatQuery = useChatSnapshot(selectedChatId);

  const selectedChat = useMemo(
    () => chats.find((chat) => chat.id === selectedChatId) ?? null,
    [chats, selectedChatId],
  );

  useEffect(() => {
    if (!bootstrapQuery.data) return;
    const data = bootstrapQuery.data;
    setRuntime(data.runtime);
    setChats(data.chats);
    setCharacterTemplates(data.characters);
    setWorldBookTemplates(data.worldBooks);
    setPersonaTemplates(data.personas);
    setSelectedChatId((current) => current ?? data.chats[0]?.id ?? null);
    setLoading(false);
  }, [bootstrapQuery.data]);

  useEffect(() => {
    let active = true;
    if (!runtime) return;
    if (runtime.provider_mode === "unconfigured") {
      setApiConnection("unconfigured");
      setApiConnectionDetail("尚未配置模型 API");
      return;
    }
    setApiConnection("checking");
    setApiConnectionDetail(`正在检测 ${runtime.model ?? "模型服务"}`);
    void api.testSettings()
      .then((result) => {
        if (!active) return;
        setApiConnection("connected");
        setApiConnectionDetail(result.message);
        setError((current) => current?.startsWith("尚未连接模型 API") ? null : current);
        setErrorFading(false);
      })
      .catch((reason) => {
        if (!active) return;
        setApiConnection("error");
        setApiConnectionDetail(errorMessage(reason));
      });
    return () => { active = false; };
  }, [runtime?.provider_mode, runtime?.model, apiCheckRevision]);

  useEffect(() => () => {
    if (connectionHintTimerRef.current !== null) window.clearTimeout(connectionHintTimerRef.current);
    if (connectionHintFadeTimerRef.current !== null) window.clearTimeout(connectionHintFadeTimerRef.current);
  }, []);

  useEffect(() => {
    if (!selectedChatId) return;
    setLoading(true);
    setMessages([]);
    setRetrieved([]);
  }, [selectedChatId]);

  useEffect(() => {
    if (chatQuery.data) applyChatSnapshot(chatQuery.data);
  }, [chatQuery.data]);

  useEffect(() => {
    const reason = bootstrapQuery.error ?? chatQuery.error;
    if (!reason) return;
    setError(errorMessage(reason));
    setLoading(false);
  }, [bootstrapQuery.error, chatQuery.error]);

  useEffect(() => {
    if (!uiPreferences.debugMode && activeTab === "context") setActiveTab("overview");
  }, [uiPreferences.debugMode, activeTab]);

  useEffect(() => {
    if (autoScrollRef.current) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => {
    function onShortcut(event: KeyboardEvent) {
      if (event.key === "Escape" && sending && sendPhase !== "postprocessing") {
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
  }, [messages, messageVariants, selectedChatId, sending, sendPhase]);

  async function loadChat(chatId: string) {
    try {
      setLoading(true);
      const snapshot = await queryClient.fetchQuery({
        ...chatSnapshotQueryOptions(chatId),
        staleTime: 0,
      });
      applyChatSnapshot(snapshot);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  }

  function applyChatSnapshot(snapshot: ChatSnapshot) {
    setMessages(snapshot.messages);
    setMessageVariants(groupVariants(snapshot.variants));
    setBookmarkedIds(new Set(snapshot.bookmarks.filter((item) => item.bookmarked).map((item) => item.message_id)));
    setCheckpoints(snapshot.checkpoints);
    setStoryCharacters(snapshot.characters);
    setStoryPersona(snapshot.persona);
    setMemories(snapshot.memories);
    setMemoryGraph(snapshot.memoryGraph);
    setMemoryCoverage(snapshot.memoryCoverage);
    setDeltas(snapshot.deltas);
    setWorldEngine(snapshot.worldEngine);
    setScenes(snapshot.scenes);
    setNpcs(snapshot.npcs);
    setTimeline(snapshot.timeline);
    setStateEntries(snapshot.state);
    setProposals(snapshot.proposals);
    setAudits(snapshot.audits);
    setTraces(snapshot.traces);
    setRetrieved([]);
    setError(null);
    setLoading(false);
  }

  async function refreshInspector(chatId: string) {
    const [memoryList, graph, coverage, deltaList, worldSnapshot, sceneList, npcList, timelineList, stateList, proposalList, auditList, traceList] = await Promise.all([
      api.memories(chatId),
      api.memoryGraph(chatId),
      api.memoryCoverage(chatId),
      api.narrativeDeltas(chatId),
      api.worldEngine(chatId),
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
    setWorldEngine(worldSnapshot);
    setScenes(sceneList);
    setNpcs(npcList);
    setTimeline(timelineList);
    setStateEntries(stateList);
    setProposals(proposalList);
    setAudits(auditList);
    setTraces(traceList);
  }

  async function createChat(title: string, characterIds: string[], worldBookIds: string[], personaId: string | null) {
    try {
      const chat = await api.createChat(title, characterIds, worldBookIds, personaId);
      setChats((current) => [chat, ...current]);
      queryClient.setQueryData(bootstrapQueryOptions.queryKey, (current: typeof bootstrapQuery.data) =>
        current ? { ...current, chats: [chat, ...current.chats] } : current,
      );
      setSelectedChatId(chat.id);
      setActiveTab("overview");
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
      queryClient.removeQueries({ queryKey: ["workspace", "chat", chatId] });
      queryClient.setQueryData(bootstrapQueryOptions.queryKey, (current: typeof bootstrapQuery.data) =>
        current ? { ...current, chats: current.chats.filter((chat) => chat.id !== chatId) } : current,
      );
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
    if (apiConnection !== "connected") {
      const message = apiConnection === "unconfigured"
        ? "尚未连接模型 API，请先在设置中完成配置。"
        : "模型 API 当前不可用，请检查连接状态后重试。";
      setErrorFading(false);
      setError(message);
      if (connectionHintTimerRef.current !== null) window.clearTimeout(connectionHintTimerRef.current);
      if (connectionHintFadeTimerRef.current !== null) window.clearTimeout(connectionHintFadeTimerRef.current);
      connectionHintFadeTimerRef.current = window.setTimeout(() => {
        setErrorFading(true);
        connectionHintFadeTimerRef.current = null;
      }, 3300);
      connectionHintTimerRef.current = window.setTimeout(() => {
        setError((current) => current === message ? null : current);
        setErrorFading(false);
        connectionHintTimerRef.current = null;
      }, 4000);
      return;
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    const optimisticId = `pending-${Date.now()}`;
    const streamingId = `stream-${Date.now()}`;
    let streamedContent = "";
    setSending(true);
    setSendPhase("generating");
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
        onPhase: (phase) => {
          if (phase === "generation_reset") {
            streamedContent = "";
            streamingRef.current = null;
            setMessages((current) => current.filter((item) => item.id !== streamingId));
            setSendPhase("generating");
            return;
          }
          setSendPhase("postprocessing");
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
      if (turn.state_proposals.length) setActiveTab("diagnostics");
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
      setSendPhase("idle");
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
    setSendPhase("idle");
  }

  async function regenerateMessage(messageId: string) {
    if (!selectedChatId || sending) return;
    const controller = new AbortController();
    abortControllerRef.current = controller;
    setSending(true);
    setSendPhase("generating");
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
      setSendPhase("idle");
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
        personaTemplates={personaTemplates}
        onSelect={(id) => { setSelectedChatId(id); setLibraryOpen(null); }}
        onCreate={createChat}
        onDelete={deleteChat}
      />

      <main className="conversation-pane">
        <header className="topbar">
          <div className="story-heading">
            <p className="eyebrow">当前故事</p>
            <div className="story-title-row">
              <h1>{selectedChat?.title ?? "选择或创建一个故事"}</h1>
              <button type="button" className={`api-connection ${apiConnection}`} title={apiConnectionDetail} onClick={() => setSettingsOpen(true)}>
                <span className="status-dot" />
                <span>{apiConnectionLabel(apiConnection)}</span>
              </button>
            </div>
          </div>
          <GlobalNav onOpen={setLibraryOpen} />
          <div className="topbar-actions">
            <details className="checkpoint-menu bookmark-menu">
              <summary><ClassicalIcon name="bookmark" />收藏 {bookmarkedIds.size || ""}</summary>
              <div>
                {bookmarkedIds.size === 0 ? <span>还没有收藏</span> : messages.filter((item) => bookmarkedIds.has(item.id)).map((item) => (
                  <button key={item.id} onClick={() => document.getElementById(`message-${item.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" })}>
                    <b>{item.role === "assistant" ? storyCharacters[0]?.name ?? "角色" : storyPersona?.name ?? "你"}</b>
                    <span>{item.content.slice(0, 42)}{item.content.length > 42 ? "…" : ""}</span>
                  </button>
                ))}
              </div>
            </details>
            <details className="checkpoint-menu">
              <summary><ClassicalIcon name="checkpoint" />检查点</summary>
              <div>
                {checkpoints.length === 0 ? <span>还没有检查点</span> : checkpoints.map((item) => (
                  <button key={item.id} onClick={() => void restoreCheckpoint(item.id)}>{item.name}</button>
                ))}
              </div>
            </details>
            <button className="settings-button" onClick={() => setSettingsOpen(true)} aria-label="打开设置">
              <ClassicalIcon name="settings" /><span>设置</span>
            </button>
            <button className={`settings-button ${inspectorOpen ? "active" : ""}`} onClick={() => setInspectorOpen((value) => !value)} aria-expanded={inspectorOpen}>
              <ClassicalIcon name="folio" /><span>控制台</span>
            </button>
          </div>
        </header>

        {error && <div className={`error-banner ${errorFading ? "is-leaving" : ""}`}><span>{error}</span><button type="button" onClick={() => { setError(null); setErrorFading(false); }} aria-label="关闭提示">×</button></div>}

        <section
          key={selectedChatId ?? "no-story"}
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
            <EmptyState title="" detail="" />
          ) : (
            messages.map((message) => <MessageBubble
              key={message.id}
              message={message}
              character={storyCharacters[0] ?? null}
              userAvatar={storyPersona?.avatar || uiPreferences.userAvatar}
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
          {sending && sendPhase === "generating" && !messages.some((item) => item.id.startsWith("stream-")) && (
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
          <div className="composer-rule composer-rule-top" aria-hidden="true">
            <img src={composerRuleTopLeft} alt="" />
            <i />
            <img className="composer-rule-center" src={composerRuleTopCenter} alt="" />
            <i />
            <img src={composerRuleTopRight} alt="" />
          </div>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder={selectedChatId ? (!loading && messages.length === 0 ? "写下故事的开篇" : "继续你的故事…") : "请先创建存档"}
            disabled={!selectedChatId || sending}
            rows={1}
          />
          <div className="composer-footer">
            <span>{sendPhase === "postprocessing" ? "正在整理本轮记忆…" : "Enter 发送 · Shift + Enter 换行"}</span>
            {sending && sendPhase === "postprocessing" ? (
              <button type="button" className="primary-button processing-button" disabled title="正在整理本轮记忆">
                <span>整理中</span><b>…</b>
              </button>
            ) : sending ? (
              <button type="button" className="primary-button stop-button" onClick={() => void stopGeneration()}>
                <span>停止</span><b>■</b>
              </button>
            ) : (
              <button className="primary-button" disabled={!draft.trim() || !selectedChatId}>
                <span>发送</span><ClassicalIcon name="nib" />
              </button>
            )}
          </div>
          <div className="composer-rule composer-rule-bottom" aria-hidden="true">
            <img src={composerRuleBottomLeft} alt="" />
            <i />
            <img className="composer-rule-bottom-center" src={composerRuleBottomCenter} alt="" />
            <i />
            <img src={composerRuleBottomRight} alt="" />
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
        worldEngine={worldEngine}
        coverage={memoryCoverage}
        scenes={scenes}
        npcs={npcs}
        retrieved={retrieved}
        timeline={timeline}
        stateEntries={stateEntries}
        proposals={proposals}
        audits={audits}
        traces={traces}
        debugMode={uiPreferences.debugMode}
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
          personaTemplates={personaTemplates}
          storyPersona={storyPersona}
          onCharacters={setCharacterTemplates}
          onStoryCharacters={setStoryCharacters}
          onWorldBooks={setWorldBookTemplates}
          onPersonas={setPersonaTemplates}
          onStoryPersona={setStoryPersona}
          onPresetActivated={async () => setRuntime(await api.runtime())}
          onError={(reason) => setError(errorMessage(reason))}
          error={error}
        />
      )}
      {settingsOpen && (
        <SettingsModal
          preferences={uiPreferences}
          onPreferences={setUiPreferences}
          onRuntime={(value) => {
            setRuntime(value);
            setApiCheckRevision((current) => current + 1);
          }}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  );
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
    setDraft(worldEntryToDraft(entry));
    setShowForm(true);
  }

  function payload(value: WorldEntryDraft) {
    return {
      title: value.title.trim(),
      keywords: value.keywords.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean),
      content: value.content.trim(),
      priority: value.priority,
      enabled: value.enabled,
      secondary_keywords: value.secondaryKeywords.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean),
      constant: value.constant, case_sensitive: value.caseSensitive,
      scan_depth: value.scanDepth, insertion_position: value.insertionPosition,
      group_name: value.groupName, recursive: value.recursive,
      token_budget: value.tokenBudget, scope: value.scope,
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

  async function undo(id: string) {
    try {
      await api.undoStateChange(props.chatId, id);
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
      {props.proposals.filter((item) => item.status === "approved").slice(0, 10).map((item) => (
        <article className="proposal-card" key={`history-${item.id}`}>
          <header><strong>{item.entity}.{item.key}</strong><span>已自动采用</span></header>
          <div className="value-change"><code>{displayValue(item.old_value)}</code><b>→</b><code>{displayValue(item.new_value)}</code></div>
          <footer><button onClick={() => undo(item.id)}>撤销</button></footer>
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
  const [artwork] = useState(() => EMPTY_ARTWORKS[Math.floor(Math.random() * EMPTY_ARTWORKS.length)]);
  const [quote] = useState(() => PHILOSOPHICAL_QUOTES[Math.floor(Math.random() * PHILOSOPHICAL_QUOTES.length)]);
  return <div className="empty-state">
    <figure className="empty-artwork">
      <div className="empty-artwork-crop" style={{ aspectRatio: artwork.ratio }}>
        <img
          className="empty-artwork-sheet"
          src={artwork.src}
          alt=""
          style={{ transform: `scale(${artwork.crop})` }}
        />
      </div>
      <figcaption><span>{artwork.title}</span><small>{artwork.artist}</small></figcaption>
    </figure>
    {(title || detail) && <div className="empty-copy">{title && <h2>{title}</h2>}{detail && <p>{detail}</p>}</div>}
    <blockquote className="empty-quote">
      <p>“{quote.text}”</p>
      <cite>— {quote.author}<span> · {quote.source}</span></cite>
    </blockquote>
  </div>;
}

function apiConnectionLabel(state: ApiConnectionState) {
  return {
    unconfigured: "API 未连接",
    checking: "正在检测",
    connected: "API 已连接",
    error: "连接异常",
  }[state];
}

const EMPTY_ARTWORKS = [
  { src: goyaSleepOfReason, title: "理性沉睡，心魔生焉", artist: "弗朗西斯科·戈雅 · 1799", crop: 1.04, ratio: "926 / 1400" },
  { src: durerMelencolia, title: "忧郁 I", artist: "阿尔布雷希特·丢勒 · 1514", crop: 1.14, ratio: "1108 / 1400" },
  { src: durerSaintJerome, title: "书斋中的圣哲罗姆", artist: "阿尔布雷希特·丢勒 · 1514", crop: 1.05, ratio: "1075 / 1400" },
] as const;

const PHILOSOPHICAL_QUOTES = [
  { text: "天地不仁，以万物为刍狗。", author: "老子", source: "《道德经》" },
  { text: "圣人不死，大盗不止。", author: "庄子", source: "《胠箧》" },
  { text: "窃钩者诛，窃国者为诸侯。", author: "庄子", source: "《胠箧》" },
  { text: "方生方死，方死方生。", author: "庄子", source: "《齐物论》" },
  { text: "天地与我并生，而万物与我为一。", author: "庄子", source: "《齐物论》" },
  { text: "相濡以沫，不如相忘于江湖。", author: "庄子", source: "《大宗师》" },
  { text: "人生天地之间，若白驹之过隙，忽然而已。", author: "庄子", source: "《知北游》" },
  { text: "吾生也有涯，而知也无涯；以有涯随无涯，殆已。", author: "庄子", source: "《养生主》" },
  { text: "存在就是被感知。", author: "乔治·贝克莱", source: "《人类知识原理》" },
  { text: "人是万物的尺度。", author: "普罗泰戈拉", source: "残篇" },
  { text: "战争是万物之父，也是万物之王。", author: "赫拉克利特", source: "残篇 B53" },
  { text: "上升的路与下降的路，是同一条路。", author: "赫拉克利特", source: "残篇 B60" },
  { text: "人天生自由，却无往不在枷锁之中。", author: "让-雅克·卢梭", source: "《社会契约论》" },
  { text: "人的生命孤独、贫困、污秽、野蛮而短促。", author: "托马斯·霍布斯", source: "《利维坦》" },
  { text: "理性是、并且只应当是激情的奴隶。", author: "大卫·休谟", source: "《人性论》" },
  { text: "困扰人的并非事物，而是人对事物的判断。", author: "爱比克泰德", source: "《手册》" },
  { text: "人类全部的不幸，都源于不能安静地独处一室。", author: "布莱兹·帕斯卡", source: "《思想录》" },
  { text: "未经审视的人生不值得过。", author: "苏格拉底", source: "柏拉图《申辩篇》" },
  { text: "死亡与我们无关：我们存在时，死亡尚未来临。", author: "伊壁鸠鲁", source: "《致美诺寇书》" },
  { text: "世界是我的表象。", author: "阿图尔·叔本华", source: "《作为意志和表象的世界》" },
  { text: "人生像钟摆，在痛苦与无聊之间来回摆动。", author: "阿图尔·叔本华", source: "《作为意志和表象的世界》" },
  { text: "上帝死了！上帝仍然死着！是我们杀死了他。", author: "弗里德里希·尼采", source: "《快乐的科学》" },
  { text: "与怪物战斗的人，应当小心自己不要成为怪物。", author: "弗里德里希·尼采", source: "《善恶的彼岸》" },
  { text: "当你长久凝视深渊，深渊也在凝视你。", author: "弗里德里希·尼采", source: "《善恶的彼岸》" },
  { text: "自杀的念头是一种强大的安慰。", author: "弗里德里希·尼采", source: "《善恶的彼岸》" },
  { text: "没有音乐，生命将是一个错误。", author: "弗里德里希·尼采", source: "《偶像的黄昏》" },
  { text: "人是一根系在动物与超人之间、横跨深渊的绳索。", author: "弗里德里希·尼采", source: "《查拉图斯特拉如是说》" },
  { text: "人被判定为自由。", author: "让-保罗·萨特", source: "《存在主义是一种人道主义》" },
  { text: "他人就是地狱。", author: "让-保罗·萨特", source: "《禁闭》" },
  { text: "真正严肃的哲学问题只有一个：自杀。", author: "阿尔贝·加缪", source: "《西西弗神话》" },
  { text: "必须想象西西弗是幸福的。", author: "阿尔贝·加缪", source: "《西西弗神话》" },
  { text: "焦虑是自由的眩晕。", author: "索伦·克尔凯郭尔", source: "《焦虑的概念》" },
  { text: "人生只能向后理解，却必须向前生活。", author: "索伦·克尔凯郭尔", source: "《日记》" },
  { text: "财产就是盗窃。", author: "皮埃尔-约瑟夫·蒲鲁东", source: "《什么是所有权？》" },
  { text: "一切坚固的东西都烟消云散了。", author: "卡尔·马克思、弗里德里希·恩格斯", source: "《共产党宣言》" },
] as const;


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
