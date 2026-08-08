import { useState } from "react";

export type ThemeName = "ink" | "midnight";

export interface UiPreferences {
  theme: ThemeName;
  fontScale: number;
  compactMessages: boolean;
  reduceMotion: boolean;
}

export const DEFAULT_UI_PREFERENCES: UiPreferences = {
  theme: "ink",
  fontScale: 1,
  compactMessages: false,
  reduceMotion: false,
};

export function useUiPreferences() {
  const [preferences, setPreferences] = useState<UiPreferences>(loadUiPreferences);
  function save(value: UiPreferences) {
    localStorage.setItem("saraswati-ui-settings", JSON.stringify(value));
    setPreferences(value);
  }
  return { preferences, setPreferences: save };
}

function loadUiPreferences(): UiPreferences {
  try {
    const stored = JSON.parse(localStorage.getItem("saraswati-ui-settings") ?? "null");
    return stored ? { ...DEFAULT_UI_PREFERENCES, ...stored } : DEFAULT_UI_PREFERENCES;
  } catch {
    return DEFAULT_UI_PREFERENCES;
  }
}
