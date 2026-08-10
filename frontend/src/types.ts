export type MessageRole = "user" | "assistant" | "system";
export type MemoryKind = "episodic" | "semantic" | "summary" | "implicit";
export type ProposalStatus = "pending" | "approved" | "rejected" | "reverted";
export type AuditStatus = "open" | "resolved" | "dismissed";

export interface RuntimeInfo {
  provider_mode: string;
  model: string | null;
  embedding_model: string | null;
  max_agent_steps: number;
}

export interface SkillExtension {
  id: string;
  name: string;
  description: string;
  version: string;
  author: string;
  enabled: boolean;
  plugin_id: string;
  source: string;
  read_only: boolean;
  tags: string[];
  resources: string[];
  digest: string;
  warnings: string[];
  location: string;
  license: string;
  compatibility: string;
  platforms: string[];
  required_environment_variables: string[];
  required_commands: string[];
  missing_requirements: string[];
  readiness: "ready" | "missing_requirements" | "incompatible";
  installed_at: string;
  source_url: string;
  view_count: number;
  use_count: number;
  last_used_at: string;
}

export interface PluginExtension {
  id: string;
  name: string;
  description: string;
  version: string;
  url: string;
  enabled: boolean;
  transport: "streamable_http" | "sse" | "stdio";
  capabilities: string[];
  allowed_tools: string[];
  status: "idle" | "connected" | "error";
  error: string | null;
  tools: string[];
  command: string;
  args: string[];
  environment_variables: string[];
  trusted: boolean;
  timeout_seconds: number;
  auth_configured: boolean;
  header_names: string[];
  manifest_format: "saraswati" | "codex" | "legacy";
  source: string;
  author: string;
  license: string;
  homepage: string;
  repository: string;
  keywords: string[];
  skills: string[];
  resources: string[];
  interface: Record<string, unknown>;
  mcp_servers: McpServerExtension[];
  plugin_type: "skill" | "tool" | "hybrid" | "resource";
  missing_requirements: string[];
  installed_at: string;
  source_url: string;
  location: string;
}

export interface McpServerExtension {
  id: string;
  transport: "streamable_http" | "sse" | "stdio";
  url: string;
  command: string;
  args: string[];
  cwd: string;
  environment_variables: string[];
  allowed_tools: string[];
  excluded_tools: string[];
  timeout_seconds: number;
  header_names: string[];
}

export interface ExtensionCatalog {
  skills: SkillExtension[];
  plugins: PluginExtension[];
  mcp_sdk_available: boolean;
  root: string;
}

export interface ChatSkillSelection {
  chat_id: string;
  mode: "all" | "selected";
  skill_ids: string[];
}

export interface PluginCreate {
  id: string;
  name: string;
  description: string;
  version: string;
  url: string;
  transport: "streamable_http" | "sse" | "stdio";
  capabilities: ["tools"];
  allowed_tools: string[];
  command: string;
  args: string[];
  environment_variables: string[];
  trusted: boolean;
  timeout_seconds: number;
  auth_token: string;
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
  context_window_tokens: number;
  input_price_per_million: number;
  output_price_per_million: number;
  active_preset_id: string | null;
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
  context_window_tokens: number;
  input_price_per_million: number;
  output_price_per_million: number;
}

export interface NarrativeDelta {
  id: string;
  chat_id: string;
  user_message_id: string;
  assistant_message_id: string;
  payload: {
    summary?: string;
    time_change?: string;
    facts?: string[];
    open_threads?: string[];
    numbers?: { name: string; value: string; unit: string }[];
    graph_changes?: unknown[];
  };
  valid: boolean;
  created_at: string;
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
  avatar: string;
  updated_at: string | null;
}

export interface CharacterTemplate {
  id: string;
  name: string;
  identity: string;
  personality: string;
  speaking_style: string;
  scenario: string;
  avatar: string;
  appearance: string;
  first_message: string;
  alternate_greetings: string[];
  example_dialogue: string;
  tags: string[];
  creator_notes: string;
  system_prompt: string;
  favorite: boolean;
  world_book_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface PresetPrompt {
  identifier: string;
  name: string;
  role: "system" | "assistant" | "user";
  content: string;
  enabled: boolean;
  marker: boolean;
  position: "relative" | "in_chat";
  depth: number;
}

export interface PromptPreset {
  id: string;
  name: string;
  description: string;
  temperature: number;
  top_p: number;
  max_output_tokens: number;
  presence_penalty: number;
  frequency_penalty: number;
  context_window_tokens: number;
  prompts: PresetPrompt[];
  extra_settings: Record<string, unknown>;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PersonaTemplate {
  id: string;
  name: string;
  avatar: string;
  identity: string;
  personality: string;
  appearance: string;
  speaking_style: string;
  world_book_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface StoryPersona extends PersonaTemplate {
  chat_id: string;
  source_template_id: string | null;
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
  secondary_keywords: string[];
  content: string;
  priority: number;
  enabled: boolean;
  constant: boolean;
  case_sensitive: boolean;
  scan_depth: number;
  insertion_position: "before_history" | "after_history" | "system";
  group_name: string;
  recursive: boolean;
  token_budget: number;
  scope: "global" | "character" | "persona" | "story";
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

export interface MessageVariant {
  id: string;
  chat_id: string;
  message_id: string;
  position: number;
  content: string;
  selected: boolean;
  created_at: string;
}

export interface MessageBookmark {
  message_id: string;
  bookmarked: boolean;
}

export interface StoryCheckpoint {
  id: string;
  chat_id: string;
  message_id: string;
  name: string;
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

export type WorldFactionStatus = "rising" | "stable" | "strained" | "declining" | "dissolved";
export type WorldFactionRelation = "allied" | "friendly" | "neutral" | "cold" | "hostile";

export interface WorldFaction {
  id: string;
  name: string;
  description: string;
  status: WorldFactionStatus;
  relation: WorldFactionRelation;
  influence: number;
  latest_action: string;
}

export interface WorldEvent {
  id: string;
  name: string;
  type: "conflict" | "progress";
  stage: "seed" | "developing" | "approaching" | "resolved" | "failed" | "dissipated";
  level: number;
  summary: string;
  participants: string[];
  location: string;
  next_pressure: string;
  active: boolean;
}

export interface WorldRumor {
  id: string;
  topic: string;
  type: "announcement" | "report" | "rumor" | "sentiment";
  level: number;
  content: string;
  scope: string;
  source: string;
  active: boolean;
}

export interface WorldTrend {
  id: string;
  name: string;
  description: string;
  direction: "rising" | "stable" | "falling";
}

export interface WorldEngineState {
  round: number;
  digest: string;
  factions: WorldFaction[];
  events: WorldEvent[];
  rumors: WorldRumor[];
  trends: WorldTrend[];
}

export interface WorldEngineSnapshot {
  state: WorldEngineState;
  auto_evolve: boolean;
  records_count: number;
  stale_count: number;
  updated_at: string | null;
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
