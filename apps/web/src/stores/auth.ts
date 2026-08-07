import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { User } from "@aigc/shared-types";

// 安全策略（审计 S6 修复）：
// - access token 仅存内存，不落盘
// - refresh token 存 sessionStorage（标签页关闭即失效，且每次刷新轮换），
//   页面刷新后用于静默换新 access，登录态不中断
// - localStorage 只持久化 user 信息（无任何 token）
const REFRESH_KEY = "aigc-refresh-token";

function readStoredRefresh(): string | null {
  try {
    return sessionStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

function storeRefresh(refresh: string | null): void {
  try {
    if (refresh) sessionStorage.setItem(REFRESH_KEY, refresh);
    else sessionStorage.removeItem(REFRESH_KEY);
  } catch {
    /* 隐私模式等场景忽略 */
  }
}

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  setAuth: (user: User, accessToken: string, refreshToken: string) => void;
  setTokens: (accessToken: string, refreshToken: string) => void;
  logout: () => void;
  isAuthenticated: () => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      accessToken: null,
      refreshToken: readStoredRefresh(),
      setAuth: (user, accessToken, refreshToken) => {
        storeRefresh(refreshToken);
        set({ user, accessToken, refreshToken });
      },
      setTokens: (accessToken, refreshToken) => {
        storeRefresh(refreshToken);
        set({ accessToken, refreshToken });
      },
      logout: () => {
        storeRefresh(null);
        // 清空媒体访问缓存：预签名 URL 不能跨账号残留
        import("@/hooks/usePrivateMediaUrl").then((m) => m.clearMediaAccessCache());
        set({ user: null, accessToken: null, refreshToken: null });
      },
      isAuthenticated: () => Boolean(get().accessToken || get().refreshToken),
    }),
    {
      name: "aigc-auth",
      // 只持久化 user：token 一律不落 localStorage
      partialize: (state) => ({ user: state.user }),
    },
  ),
);
