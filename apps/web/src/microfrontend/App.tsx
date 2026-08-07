import { useEffect, useMemo } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import type { AigcStudioHostProps } from "@aigc/shared-types";

import { configureApiClient, RateLimitError } from "@/lib/apiClient";
import { useAuthStore } from "@/stores/auth";
import { useThemeStore } from "@/stores/theme";

import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { AppRoutes } from "./Routes";
import { HostProvider } from "./hostContext";

// 模块级默认配置：在任何组件渲染前生效，避免子查询早于配置执行导致 401。
configureApiClient({
  getToken: () => useAuthStore.getState().accessToken,
  getRefreshToken: () => useAuthStore.getState().refreshToken,
  setTokens: (access, refresh) => useAuthStore.getState().setTokens(access, refresh),
  onUnauthorized: () => useAuthStore.getState().logout(),
});

/**
 * AIGC Studio 根组件，Standalone 与 Remote 双模式共用。
 *
 * - 样式限定在 [data-aigc-studio-root] 作用域内，不污染宿主 body/html。
 * - Router 尊重 Host 传入的 basename。
 * - 每个实例独立 QueryClient，避免 Remote 卸载后缓存串扰。
 */
export default function App(props: AigcStudioHostProps = {}) {
  const queryClient = useMemo(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 2,
            staleTime: 30_000,
            // 429 限流：尊重 Retry-After，其余错误指数退避
            retryDelay: (attempt, error) => {
              if (error instanceof RateLimitError && error.retryAfter > 0) {
                return Math.min(error.retryAfter * 1000, 60_000);
              }
              return Math.min(1000 * 2 ** attempt, 30_000);
            },
          },
        },
      }),
    [],
  );

  // Remote 模式：用宿主下发的 token / API 地址 / 未授权回调覆盖默认配置。
  // 在 render 期间（而非 useEffect）同步配置：配置是幂等的模块级赋值，
  // 可确保任何子组件 useQuery 发起首个请求前 getToken 已拿到宿主 token，避免 401 竞态。
  const { accessToken, apiBaseUrl, onUnauthorized } = props;
  configureApiClient({
    getToken: () => accessToken ?? useAuthStore.getState().accessToken,
    getRefreshToken: () => useAuthStore.getState().refreshToken,
    setTokens: (access, refresh) => useAuthStore.getState().setTokens(access, refresh),
    onUnauthorized: () => {
      useAuthStore.getState().logout();
      onUnauthorized?.();
    },
    ...(apiBaseUrl ? { baseUrl: apiBaseUrl } : {}),
  });

  // 宿主 token 同步进 auth store：路由守卫 isAuthenticated() 与用户展示依赖 store。
  useEffect(() => {
    if (!accessToken) return;
    const state = useAuthStore.getState();
    if (state.accessToken !== accessToken) {
      state.setTokens(accessToken, state.refreshToken ?? "");
    }
  }, [accessToken]);

  // 页面刷新后的静默刷新：user 从 localStorage 恢复、refresh token 在 sessionStorage，
  // access token 不在内存 → 用 refresh 换新 access，避免强制重新登录。
  useEffect(() => {
    const state = useAuthStore.getState();
    if (accessToken || !state.user || !state.refreshToken) return;
    let cancelled = false;
    void (async () => {
      try {
        const { tryRefreshToken } = await import("@/lib/apiClient");
        const fresh = await tryRefreshToken();
        if (!cancelled && !fresh) {
          state.logout();
        }
      } catch {
        if (!cancelled) state.logout();
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  const storeTheme = useThemeStore((s) => s.mode);
  const theme = props.theme ?? storeTheme;

  return (
    <div data-aigc-studio-root data-theme={theme}>
      <HostProvider value={props}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter {...(props.basename ? { basename: props.basename } : {})}>
            <ErrorBoundary>
              <AppRoutes />
            </ErrorBoundary>
          </BrowserRouter>
        </QueryClientProvider>
      </HostProvider>
    </div>
  );
}
