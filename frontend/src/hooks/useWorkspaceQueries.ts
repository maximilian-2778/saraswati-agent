import { queryOptions, useQuery } from "@tanstack/react-query";
import { api } from "../api";
import type {
  AgentTrace, AuditIssue, Chat, CharacterTemplate, Memory, MemoryCoverage,
  Message, MessageBookmark, MessageVariant, NarrativeDelta, NarrativeNode, Npc,
  PersonaTemplate, RuntimeInfo, SceneNode, StateEntry, StateProposal,
  StoryCharacter, StoryCheckpoint, StoryPersona, TimelineAnchor, WorldBookTemplate,
} from "../types";

export interface WorkspaceBootstrap {
  runtime: RuntimeInfo;
  chats: Chat[];
  characters: CharacterTemplate[];
  worldBooks: WorldBookTemplate[];
  personas: PersonaTemplate[];
}

export interface ChatSnapshot {
  messages: Message[];
  variants: MessageVariant[];
  bookmarks: MessageBookmark[];
  checkpoints: StoryCheckpoint[];
  characters: StoryCharacter[];
  persona: StoryPersona | null;
  memories: Memory[];
  memoryGraph: NarrativeNode[];
  memoryCoverage: MemoryCoverage;
  deltas: NarrativeDelta[];
  scenes: SceneNode[];
  npcs: Npc[];
  timeline: TimelineAnchor[];
  state: StateEntry[];
  proposals: StateProposal[];
  audits: AuditIssue[];
  traces: AgentTrace[];
}

export const bootstrapQueryOptions = queryOptions({
  queryKey: ["workspace", "bootstrap"],
  queryFn: async (): Promise<WorkspaceBootstrap> => {
    const [runtime, chats, characters, worldBooks, personas] = await Promise.all([
      api.runtime(), api.chats(), api.characterTemplates(), api.worldBookTemplates(), api.personaTemplates(),
    ]);
    return { runtime, chats, characters, worldBooks, personas };
  },
});

export function chatSnapshotQueryOptions(chatId: string) {
  return queryOptions({
    queryKey: ["workspace", "chat", chatId],
    queryFn: async (): Promise<ChatSnapshot> => {
      const [messages, variants, bookmarks, checkpoints, characters, persona,
        memories, memoryGraph, memoryCoverage, deltas, scenes, npcs, timeline,
        state, proposals, audits, traces] = await Promise.all([
        api.messages(chatId), api.messageVariants(chatId), api.bookmarks(chatId),
        api.checkpoints(chatId), api.storyCharacters(chatId), api.storyPersona(chatId),
        api.memories(chatId), api.memoryGraph(chatId), api.memoryCoverage(chatId),
        api.narrativeDeltas(chatId), api.scenes(chatId), api.npcs(chatId),
        api.timeline(chatId), api.state(chatId), api.proposals(chatId),
        api.audits(chatId), api.traces(chatId),
      ]);
      return { messages, variants, bookmarks, checkpoints, characters, persona,
        memories, memoryGraph, memoryCoverage, deltas, scenes, npcs, timeline,
        state, proposals, audits, traces };
    },
  });
}

export function useWorkspaceBootstrap() {
  return useQuery(bootstrapQueryOptions);
}

export function useChatSnapshot(chatId: string | null) {
  return useQuery({
    ...chatSnapshotQueryOptions(chatId ?? ""),
    enabled: Boolean(chatId),
    staleTime: 0,
  });
}
