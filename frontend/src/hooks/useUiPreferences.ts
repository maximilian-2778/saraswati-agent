import { useEffect, useState } from "react";

export type ThemeName = "ink" | "paper";

export interface UiPreferences {
  theme: ThemeName;
  fontScale: number;
  compactMessages: boolean;
  reduceMotion: boolean;
  debugMode: boolean;
  userAvatar: string;
}

export const DEFAULT_UI_PREFERENCES: UiPreferences = {
  theme: "paper",
  fontScale: 1,
  compactMessages: false,
  reduceMotion: false,
  debugMode: false,
  userAvatar: "",
};

export function useUiPreferences() {
  const [preferences, setPreferences] = useState<UiPreferences>(loadUiPreferences);
  useEffect(() => {
    // HelpTip 等浮层通过 Portal 渲染到应用容器之外，需要从根节点读取主题。
    document.documentElement.dataset.saraswatiTheme = preferences.theme;
  }, [preferences.theme]);
  function save(value: UiPreferences) {
    localStorage.setItem("saraswati-ui-settings", JSON.stringify(value));
    setPreferences(value);
  }
  return { preferences, setPreferences: save };
}

function loadUiPreferences(): UiPreferences {
  try {
    const stored = JSON.parse(localStorage.getItem("saraswati-ui-settings") ?? "null");
    if (!stored) return DEFAULT_UI_PREFERENCES;
    // 旧版本的 midnight 也是暗色主题。升级后将它迁移到新增加的纸页亮色主题，
    // 避免界面继续出现两个几乎相同的暗色选项。
    const theme: ThemeName = stored.theme === "paper" || stored.theme === "midnight" ? "paper" : "ink";
    return { ...DEFAULT_UI_PREFERENCES, ...stored, theme };
  } catch {
    return DEFAULT_UI_PREFERENCES;
  }
}
