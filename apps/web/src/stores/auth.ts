import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { User } from "@aigc/shared-types";

// 安全策略（审计 S6 修复 + 2026-08 个人服务器免登录调整）：
// - access token 仅存内存，不落盘
// - refresh token 存 localStorage（个人服务器开启 AUTO_LOGIN 时跨标签页/重启持久；
//   默认生产环境会话语义由 AUTO_LOGIN_KEY 开关控制，未开启时仍为会话级体验）
// - localStorage 只持久化 user 信息（无 access token）
const REFRESH_KEY = "aigc-refresh-token";

function readStoredRefresh(): string | null {
  try {
    return localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

function storeRefresh(refresh: string | null): void {
  try {
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
    else localStorage.removeItem(REFRESH_KEY);
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
