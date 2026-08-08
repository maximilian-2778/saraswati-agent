import type {
  AgentTrace,
  AgentTurn,
  AppSettings,
  AuditIssue,
  Chat,
  CharacterProfile,
  Memory,
  RuntimeInfo,
  SettingsTestResult,
  SettingsUpdate,
  StateEntry,
  StateProposal,
  Message,
  WorldBookEntry,
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
  createChat: (title: string) =>
    request<Chat>("/chats", {
      method: "POST",
      body: JSON.stringify({ title, system_prompt: "" }),
    }),
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
