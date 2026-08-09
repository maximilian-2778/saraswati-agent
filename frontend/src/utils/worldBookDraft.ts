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
  tokenBudget: number;
  scope: "global" | "character" | "persona" | "story";
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
  tokenBudget: 2048,
  scope: "global",
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
    tokenBudget: item.token_budget,
    scope: item.scope,
  };
}
