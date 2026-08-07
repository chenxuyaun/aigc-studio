import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeMode = "light" | "dark" | "system";

interface ThemeState {
  mode: ThemeMode;
  setMode: (m: ThemeMode) => void;
  cycle: () => void;
}

const ORDER: ThemeMode[] = ["light", "dark", "system"];

// 默认浅色——「干净明亮工作台」是品牌调性；用户可切换并持久化。
export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      mode: "light",
      setMode: (mode) => set({ mode }),
      cycle: () => {
        const idx = ORDER.indexOf(get().mode);
        const nextMode = ORDER[(idx + 1) % ORDER.length] ?? "dark";
        set({ mode: nextMode });
      },
    }),
    { name: "aigc-theme-v2" },
  ),
);
