import type { StoryWorldBook, WorldBookEntry, WorldBookTemplate } from "../types";

export interface WorldEntryDraft {
  title: string;
  keywords: string;
  content: string;
  priority: number;
  enabled: boolean;
  secondaryKeywords: string;
  constant: boolean;
  caseSensitive: boolean;
  scanDepth: number;
  insertionPosition: "before_history" | "after_history" | "system";
  groupName: string;
  recursive: boolean;
  selectiveLogic: "and_any" | "and_all" | "not_any" | "not_all";
  probability: number;
  matchWholeWords: boolean;
  preventRecursion: boolean;
  depth: number;
  sticky: number;
  cooldown: number;
  delay: number;
  tokenBudget: number;
  scope: "global" | "character" | "persona" | "story";
  compatibilityData: Record<string, unknown>;
}

export const EMPTY_WORLD_ENTRY: WorldEntryDraft = {
  title: "",
  keywords: "",
  content: "",
  priority: 50,
  enabled: true,
  secondaryKeywords: "",
  constant: false,
  caseSensitive: false,
  scanDepth: 4,
  insertionPosition: "before_history",
  groupName: "",
  recursive: false,
  selectiveLogic: "and_any",
  probability: 100,
  matchWholeWords: false,
  preventRecursion: false,
  depth: 4,
  sticky: 0,
  cooldown: 0,
  delay: 0,
  tokenBudget: 2048,
  scope: "global",
  compatibilityData: {},
};

export function worldEntryToDraft(
  item: WorldBookTemplate | StoryWorldBook | WorldBookEntry,
): WorldEntryDraft {
  return {
    title: item.title,
    keywords: item.keywords.join("，"),
    content: item.content,
    priority: item.priority,
    enabled: item.enabled,
    secondaryKeywords: item.secondary_keywords.join("，"),
    constant: item.constant,
    caseSensitive: item.case_sensitive,
    scanDepth: item.scan_depth,
    insertionPosition: item.insertion_position,
    groupName: item.group_name,
    recursive: item.recursive,
    selectiveLogic: item.selective_logic,
    probability: item.probability,
    matchWholeWords: item.match_whole_words,
    preventRecursion: item.prevent_recursion,
    depth: item.depth,
    sticky: item.sticky,
    cooldown: item.cooldown,
    delay: item.delay,
    tokenBudget: item.token_budget,
    scope: item.scope,
    compatibilityData: item.compatibility_data,
  };
}
