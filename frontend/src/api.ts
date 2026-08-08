import type {
  AgentTrace,
  AgentTurn,
  AppSettings,
  AuditIssue,
  Chat,
  CharacterTemplate,
  CharacterProfile,
  Memory,
  RuntimeInfo,
  SettingsTestResult,
  SettingsUpdate,
  StateEntry,
  StateProposal,
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
  sendMessage: (chatId: string, content: string) =>
    request<AgentTurn>(`/chats/${chatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  memories: (chatId: string) => request<Memory[]>(`/chats/${chatId}/memories`),
  createMemory: (chatId: string, payload: object) =>
    request<Memory>(`/chats/${chatId}/memories`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  summarize: (chatId: string) =>
    request<Memory>(`/chats/${chatId}/memories/summarize`, {
      method: "POST",
      body: JSON.stringify({ max_messages: 30 }),
    }),
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
};
