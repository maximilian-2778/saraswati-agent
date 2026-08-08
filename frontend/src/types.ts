export type MessageRole = "user" | "assistant" | "system";
export type MemoryKind = "episodic" | "semantic" | "summary" | "implicit";
export type ProposalStatus = "pending" | "approved" | "rejected";
export type AuditStatus = "open" | "resolved" | "dismissed";

export interface RuntimeInfo {
  provider_mode: string;
  model: string | null;
  embedding_model: string | null;
  max_agent_steps: number;
}

export interface AppSettings {
  provider_mode: string;
  llm_base_url: string | null;
  api_key_configured: boolean;
  api_key_hint: string | null;
  llm_model: string | null;
  embedding_model: string | null;
  temperature: number;
  top_p: number;
  max_output_tokens: number;
  presence_penalty: number;
  frequency_penalty: number;
  request_timeout: number;
  max_agent_steps: number;
  recent_message_limit: number;
  rag_limit: number;
  vector_weight: number;
  keyword_weight: number;
  importance_weight: number;
  recency_weight: number;
  auto_summary_enabled: boolean;
  summary_detail_mode: "brief" | "detailed";
  chapter_summary_size: number;
  arc_summary_size: number;
  rerank_base_url: string | null;
  rerank_api_key_configured: boolean;
  rerank_api_key_hint: string | null;
  rerank_model: string | null;
  rerank_candidates: number;
}

export interface SettingsUpdate {
  llm_base_url: string | null;
  api_key: string | null;
  clear_api_key: boolean;
  llm_model: string | null;
  embedding_model: string | null;
  temperature: number;
  top_p: number;
  max_output_tokens: number;
  presence_penalty: number;
  frequency_penalty: number;
  request_timeout: number;
  max_agent_steps: number;
  recent_message_limit: number;
  rag_limit: number;
  vector_weight: number;
  keyword_weight: number;
  importance_weight: number;
  recency_weight: number;
  auto_summary_enabled: boolean;
  summary_detail_mode: "brief" | "detailed";
  chapter_summary_size: number;
  arc_summary_size: number;
  rerank_base_url: string | null;
  rerank_api_key: string | null;
  clear_rerank_api_key: boolean;
  rerank_model: string | null;
  rerank_candidates: number;
}

export interface SettingsTestResult {
  ok: boolean;
  provider_mode: string;
  model: string | null;
  message: string;
}

export interface Chat {
  id: string;
  title: string;
  system_prompt: string;
  created_at: string;
  updated_at: string;
}

export interface CharacterProfile {
  id: string | null;
  chat_id: string;
  name: string;
  identity: string;
  personality: string;
  speaking_style: string;
  scenario: string;
  updated_at: string | null;
}

export interface CharacterTemplate {
  id: string;
  name: string;
  identity: string;
  personality: string;
  speaking_style: string;
  scenario: string;
  created_at: string;
  updated_at: string;
}

export interface StoryCharacter extends CharacterTemplate {
  chat_id: string;
  source_template_id: string | null;
}

export interface WorldBookEntry {
  id: string;
  chat_id: string;
  title: string;
  keywords: string[];
  content: string;
  priority: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export type WorldBookTemplate = Omit<WorldBookEntry, "chat_id">;

export interface StoryWorldBook extends WorldBookEntry {
  source_template_id: string | null;
}

export interface Message {
  id: string;
  chat_id: string;
  role: MessageRole;
  content: string;
  created_at: string;
}

export interface Memory {
  id: string;
  chat_id: string;
  kind: MemoryKind;
  content: string;
  importance: number;
  source_message_id: string | null;
  access_count: number;
  last_accessed_at: string | null;
  created_at: string;
}

export interface NarrativeNode {
  id: string;
  node_type: "leaf" | "summary";
  level: number;
  content: string;
  child_ids: string[];
  source_message_id: string | null;
  time_start: string | null;
  time_end: string | null;
  valid: boolean;
  active: boolean;
  created_at: string;
}

export interface MemoryCoverage {
  total_ai_floors: number;
  summarized_floors: number;
  valid_floors: number;
  coverage_ratio: number;
  missing_message_ids: string[];
  invalid_message_ids: string[];
  selected_node_ids: string[];
}

export interface SceneNode {
  id: string;
  chat_id: string;
  name: string;
  parent_id: string | null;
  description: string;
  is_current: boolean;
  path: string[];
  source_message_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface NpcRelation { target: string; relation: string; }

export interface Npc {
  id: string;
  chat_id: string;
  name: string;
  description: string;
  relation_to_user: string;
  relations: NpcRelation[];
  importance: "core" | "supporting" | "minor";
  presence: "present" | "nearby" | "away" | "unknown";
  location_scene_id: string | null;
  outfit: string;
  condition: string;
  source_message_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TimelineAnchor {
  id: string;
  chat_id: string;
  story_time: string;
  description: string;
  source_message_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RetrievedMemory {
  memory: Memory;
  score: number;
  retrieval_reason: string;
}

export interface StateEntry {
  id: string;
  chat_id: string;
  entity: string;
  key: string;
  value: unknown;
  source_message_id: string | null;
  version: number;
  updated_at: string;
}

export interface StateProposal {
  id: string;
  chat_id: string;
  entity: string;
  key: string;
  old_value: unknown;
  new_value: unknown;
  reason: string;
  source_message_id: string | null;
  status: ProposalStatus;
  created_at: string;
  resolved_at: string | null;
}

export interface AuditIssue {
  id: string;
  chat_id: string;
  message_id: string;
  category: string;
  severity: string;
  description: string;
  expected_value: unknown;
  actual_value: unknown;
  evidence: string;
  status: AuditStatus;
  created_at: string;
}

export interface AgentTrace {
  id: string;
  chat_id: string;
  turn_id: string;
  step: number;
  event_type: string;
  payload: unknown;
  created_at: string;
}

export interface AgentTurn {
  turn_id: string;
  provider_mode: string;
  user_message: Message;
  assistant_message: Message;
  retrieved_memories: RetrievedMemory[];
  state_proposals: StateProposal[];
  audit_issues: AuditIssue[];
  trace: AgentTrace[];
}
