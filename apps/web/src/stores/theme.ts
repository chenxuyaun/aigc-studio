import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeMode = "light" | "dark" | "system";
/** v2 P3 皮肤引擎：品牌主色四选一（全局生效，Studio 与全站一致）。 */
export type SkinName = "cyan" | "purple" | "emerald" | "mono";

export const SKINS: { key: SkinName; label: string; dot: string }[] = [
  { key: "cyan", label: "宣纸青瓷（v11 默认）", dot: "#2f6359" },
  { key: "purple", label: "朱砂紫檀", dot: "#8b5cf6" },
  { key: "emerald", label: "黑曜翡翠", dot: "#10b981" },
  { key: "mono", label: "钛银极简", dot: "#94a3b8" },
];

interface ThemeState {
  mode: ThemeMode;
  skin: SkinName;
  setMode: (m: ThemeMode) => void;
  setSkin: (s: SkinName) => void;
  cycle: () => void;
}

const ORDER: ThemeMode[] = ["light", "dark", "system"];

// 默认浅色——「干净明亮工作台」是品牌调性；用户可切换并持久化。
export const useThemeStore = create<ThemeState>()(
  persist(
    (set, get) => ({
      mode: "dark",
      skin: "cyan",
      setMode: (mode) => set({ mode }),
      setSkin: (skin) => set({ skin }),
      cycle: () => {
        const idx = ORDER.indexOf(get().mode);
        const nextMode = ORDER[(idx + 1) % ORDER.length] ?? "dark";
        set({ mode: nextMode });
      },
    }),
    {
      name: "aigc-theme-v2",
      // 旧存储无 skin 字段时合并默认值（persist 部分持久化）
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as object),
        skin: ((persisted as { skin?: SkinName }).skin ?? "cyan") as SkinName,
      }),
    },
  ),
);
