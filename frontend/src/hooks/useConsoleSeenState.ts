import { useEffect, useState } from "react";

export type ConsoleNoticeTab = "world" | "events" | "memory" | "diagnostics";
export type ConsoleSeenState = Record<ConsoleNoticeTab, string>;
export type ConsoleNoticeItems = Record<ConsoleNoticeTab, string[]>;

const STORAGE_KEY = "saraswati-console-seen";
const EMPTY_SEEN_STATE: ConsoleSeenState = {
  world: "",
  events: "",
  memory: "",
  diagnostics: "",
};

export function useConsoleSeenState(
  chatId: string | null,
  activeTab: string,
  items: ConsoleNoticeItems,
) {
  const [seen, setSeen] = useState<ConsoleSeenState>(() => loadSeenState(chatId));

  useEffect(() => {
    setSeen(loadSeenState(chatId));
  }, [chatId]);

  const noticeCounts: Record<ConsoleNoticeTab, number> = {
    world: unseenCount(items.world, seen.world),
    events: unseenCount(items.events, seen.events),
    memory: unseenCount(items.memory, seen.memory),
    diagnostics: unseenCount(items.diagnostics, seen.diagnostics),
  };

  useEffect(() => {
    if (!chatId || !isNoticeTab(activeTab)) return;
    const latest = latestCursor(items[activeTab]);
    if (!latest || latest <= seen[activeTab]) return;
    const next = { ...seen, [activeTab]: latest };
    saveSeenState(chatId, next);
    setSeen(next);
  }, [activeTab, chatId, items, seen]);

  if (isNoticeTab(activeTab)) noticeCounts[activeTab] = 0;
  return noticeCounts;
}

function unseenCount(items: string[], cursor: string) {
  return items.filter((item) => item > cursor).length;
}

function latestCursor(items: string[]) {
  return items.reduce((latest, item) => item > latest ? item : latest, "");
}

function isNoticeTab(tab: string): tab is ConsoleNoticeTab {
  return tab === "world" || tab === "events" || tab === "memory" || tab === "diagnostics";
}

function loadSeenState(chatId: string | null): ConsoleSeenState {
  if (!chatId) return EMPTY_SEEN_STATE;
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    return { ...EMPTY_SEEN_STATE, ...(stored[chatId] ?? {}) };
  } catch {
    return EMPTY_SEEN_STATE;
  }
}

function saveSeenState(chatId: string, value: ConsoleSeenState) {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...stored, [chatId]: value }));
  } catch {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ [chatId]: value }));
  }
}
