import type {
  AgentTrace,
  AgentTurn,
  AppSettings,
  AuditIssue,
  Chat,
  CharacterTemplate,
  CharacterProfile,
  Memory,
  MemoryCoverage,
  NarrativeNode,
  NarrativeDelta,
  Npc,
  RetrievedMemory,
  RuntimeInfo,
  SceneNode,
  SettingsTestResult,
  SettingsUpdate,
  StateEntry,
  StateProposal,
  TimelineAnchor,
  StoryCharacter,
  StoryWorldBook,
  Message,
  WorldBookEntry,
  WorldBookTemplate,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(data?.detail ?? `请求失败：HTTP ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  runtime: () => request<RuntimeInfo>("/runtime"),
  settings: () => request<AppSettings>("/settings"),
  updateSettings: (payload: SettingsUpdate) =>
    request<AppSettings>("/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  testSettings: () =>
    request<SettingsTestResult>("/settings/test", { method: "POST" }),
  chats: () => request<Chat[]>("/chats"),
  createChat: (title: string, characterTemplateIds: string[] = [], worldBookTemplateIds: string[] = []) =>
    request<Chat>("/chats", {
      method: "POST",
      body: JSON.stringify({
        title,
        system_prompt: "",
        character_template_ids: characterTemplateIds,
        world_book_template_ids: worldBookTemplateIds,
      }),
    }),
  characterTemplates: () => request<CharacterTemplate[]>("/character-templates"),
  createCharacterTemplate: (payload: object) =>
    request<CharacterTemplate>("/character-templates", { method: "POST", body: JSON.stringify(payload) }),
  updateCharacterTemplate: (id: string, payload: object) =>
    request<CharacterTemplate>(`/character-templates/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteCharacterTemplate: (id: string) =>
    request<void>(`/character-templates/${id}`, { method: "DELETE" }),
  worldBookTemplates: () => request<WorldBookTemplate[]>("/world-book-templates"),
  createWorldBookTemplate: (payload: object) =>
    request<WorldBookTemplate>("/world-book-templates", { method: "POST", body: JSON.stringify(payload) }),
  updateWorldBookTemplate: (id: string, payload: object) =>
    request<WorldBookTemplate>(`/world-book-templates/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteWorldBookTemplate: (id: string) =>
    request<void>(`/world-book-templates/${id}`, { method: "DELETE" }),
  storyCharacters: (chatId: string) => request<StoryCharacter[]>(`/chats/${chatId}/characters`),
  attachCharacter: (chatId: string, templateId: string) =>
    request<StoryCharacter>(`/chats/${chatId}/characters/from-template/${templateId}`, { method: "POST" }),
  updateStoryCharacter: (chatId: string, id: string, payload: object) =>
    request<StoryCharacter>(`/chats/${chatId}/characters/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteStoryCharacter: (chatId: string, id: string) =>
    request<void>(`/chats/${chatId}/characters/${id}`, { method: "DELETE" }),
  storyWorldBooks: (chatId: string) => request<StoryWorldBook[]>(`/chats/${chatId}/world-books`),
  attachWorldBook: (chatId: string, templateId: string) =>
    request<StoryWorldBook>(`/chats/${chatId}/world-books/from-template/${templateId}`, { method: "POST" }),
  updateStoryWorldBook: (chatId: string, id: string, payload: object) =>
    request<StoryWorldBook>(`/chats/${chatId}/world-books/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteStoryWorldBook: (chatId: string, id: string) =>
    request<void>(`/chats/${chatId}/world-books/${id}`, { method: "DELETE" }),
  character: (chatId: string) =>
    request<CharacterProfile>(`/chats/${chatId}/character`),
  updateCharacter: (chatId: string, payload: object) =>
    request<CharacterProfile>(`/chats/${chatId}/character`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  worldBook: (chatId: string) =>
    request<WorldBookEntry[]>(`/chats/${chatId}/world-book`),
  createWorldEntry: (chatId: string, payload: object) =>
    request<WorldBookEntry>(`/chats/${chatId}/world-book`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateWorldEntry: (chatId: string, entryId: string, payload: object) =>
    request<WorldBookEntry>(`/chats/${chatId}/world-book/${entryId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  deleteWorldEntry: (chatId: string, entryId: string) =>
    request<void>(`/chats/${chatId}/world-book/${entryId}`, { method: "DELETE" }),
  messages: (chatId: string) => request<Message[]>(`/chats/${chatId}/messages`),
  updateMessage: (chatId: string, messageId: string, content: string) =>
    request<Message>(`/chats/${chatId}/messages/${messageId}`, { method: "PUT", body: JSON.stringify({ content }) }),
  sendMessage: (chatId: string, content: string) =>
    request<AgentTurn>(`/chats/${chatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  memories: (chatId: string) => request<Memory[]>(`/chats/${chatId}/memories`),
  memoryGraph: (chatId: string) => request<NarrativeNode[]>(`/chats/${chatId}/memory-graph`),
  memoryCoverage: (chatId: string) => request<MemoryCoverage>(`/chats/${chatId}/memory-coverage`),
  backfillMemory: (chatId: string) => request<MemoryCoverage>(`/chats/${chatId}/memory-coverage/backfill`, { method: "POST" }),
  scenes: (chatId: string) => request<SceneNode[]>(`/chats/${chatId}/scenes`),
  createScene: (chatId: string, payload: object) => request<SceneNode>(`/chats/${chatId}/scenes`, { method: "POST", body: JSON.stringify(payload) }),
  updateScene: (chatId: string, id: string, payload: object) => request<SceneNode>(`/chats/${chatId}/scenes/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteScene: (chatId: string, id: string) => request<void>(`/chats/${chatId}/scenes/${id}`, { method: "DELETE" }),
  npcs: (chatId: string) => request<Npc[]>(`/chats/${chatId}/npcs`),
  createNpc: (chatId: string, payload: object) => request<Npc>(`/chats/${chatId}/npcs`, { method: "POST", body: JSON.stringify(payload) }),
  updateNpc: (chatId: string, id: string, payload: object) => request<Npc>(`/chats/${chatId}/npcs/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteNpc: (chatId: string, id: string) => request<void>(`/chats/${chatId}/npcs/${id}`, { method: "DELETE" }),
  searchMemories: (chatId: string, query: string, limit = 8) =>
    request<RetrievedMemory[]>(`/chats/${chatId}/memories/search`, {
      method: "POST", body: JSON.stringify({ query, limit }),
    }),
  createMemory: (chatId: string, payload: object) =>
    request<Memory>(`/chats/${chatId}/memories`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  summarize: (chatId: string) =>
    request<Memory>(`/chats/${chatId}/memories/summarize`, {
      method: "POST",
      body: JSON.stringify({ max_messages: 30, detail_mode: "brief" }),
    }),
  summarizeWithDetail: (chatId: string, detailMode: "brief" | "detailed") =>
    request<Memory>(`/chats/${chatId}/memories/summarize`, {
      method: "POST",
      body: JSON.stringify({ max_messages: 30, detail_mode: detailMode }),
    }),
  updateMemory: (chatId: string, memoryId: string, content: string, importance: number) =>
    request<Memory>(`/chats/${chatId}/memories/${memoryId}`, {
      method: "PUT", body: JSON.stringify({ content, importance }),
    }),
  deleteMemory: (chatId: string, memoryId: string) =>
    request<void>(`/chats/${chatId}/memories/${memoryId}`, { method: "DELETE" }),
  mergeMemories: (chatId: string, memoryIds: string[], detailMode: "brief" | "detailed") =>
    request<Memory>(`/chats/${chatId}/memories/merge`, {
      method: "POST", body: JSON.stringify({ memory_ids: memoryIds, detail_mode: detailMode }),
    }),
  timeline: (chatId: string) => request<TimelineAnchor[]>(`/chats/${chatId}/timeline`),
  createTimelineAnchor: (chatId: string, payload: object) =>
    request<TimelineAnchor>(`/chats/${chatId}/timeline`, { method: "POST", body: JSON.stringify(payload) }),
  updateTimelineAnchor: (chatId: string, anchorId: string, payload: object) =>
    request<TimelineAnchor>(`/chats/${chatId}/timeline/${anchorId}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteTimelineAnchor: (chatId: string, anchorId: string) =>
    request<void>(`/chats/${chatId}/timeline/${anchorId}`, { method: "DELETE" }),
  state: (chatId: string) => request<StateEntry[]>(`/chats/${chatId}/state`),
  proposals: (chatId: string) =>
    request<StateProposal[]>(`/chats/${chatId}/state/proposals`),
  createProposal: (chatId: string, payload: object) =>
    request<StateProposal>(`/chats/${chatId}/state/proposals`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  resolveProposal: (chatId: string, proposalId: string, action: "approve" | "reject") =>
    request<StateProposal>(`/chats/${chatId}/state/proposals/${proposalId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),
  audits: (chatId: string) => request<AuditIssue[]>(`/chats/${chatId}/audits`),
  resolveAudit: (chatId: string, auditId: string, action: "resolve" | "dismiss") =>
    request<AuditIssue>(`/chats/${chatId}/audits/${auditId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ action }),
    }),
  traces: (chatId: string) => request<AgentTrace[]>(`/chats/${chatId}/traces`),
  narrativeDeltas: (chatId: string) => request<NarrativeDelta[]>(`/chats/${chatId}/narrative-deltas`),
};
