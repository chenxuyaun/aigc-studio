import { useCallback, useEffect, useRef, useState, type ComponentType, type FormEvent, type ReactNode } from "react";

import {
  Activity,
  Bot,
  BookOpen,
  Clapperboard,
  FolderOpen,
  Headphones,
  LayoutDashboard,
  Library,
  ListChecks,
  LogOut,
  Monitor,
  Moon,
  MoreHorizontal,
  ScrollText,
  Search,
  Server,
  Sun,
  Users,
  MessageCircle,
} from "lucide-react";
import { NavLink, useNavigate } from "react-router-dom";

import { useHost } from "@/microfrontend/hostContext";
import { cn } from "@/lib/cn";
import { apiClient } from "@/lib/apiClient";
import { ToastHost } from "@/components/ui/Toast";
import { useAuthStore } from "@/stores/auth";
import { useThemeStore } from "@/stores/theme";
import type { SearchResultItem } from "@aigc/shared-types";

interface NavItem {
  to: string;
  label: string;
  short: string;
  icon: ComponentType<{ className?: string }>;
  mobile: boolean;
  adminOnly?: boolean;
}

/** 导航分组：侧栏按场景分组展示（移动端底部导航仍用扁平 short 项）。 */
const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "创作",
    items: [
      { to: "/", label: "工作台", short: "首页", icon: LayoutDashboard, mobile: true },
      { to: "/works", label: "我的创作", short: "我的", icon: Clapperboard, mobile: true },
    ],
  },
  {
    label: "资源",
    items: [
      { to: "/prompts", label: "提示词库", short: "提示词", icon: Library, mobile: true },
      { to: "/knowledge", label: "知识库", short: "知识库", icon: BookOpen, mobile: true },
      { to: "/assets", label: "素材库", short: "素材", icon: FolderOpen, mobile: true },
      { to: "/asmr", label: "ASMR 库", short: "ASMR", icon: Headphones, mobile: true },
      { to: "/agents", label: "Agent 库", short: "Agent", icon: Bot, mobile: false },
    ],
  },
  {
    label: "角色",
    items: [
      { to: "/roleplay", label: "角色扮演", short: "角色", icon: MessageCircle, mobile: true },
    ],
  },
  {
    label: "系统",
    items: [
      { to: "/tasks", label: "任务中心", short: "任务", icon: ListChecks, mobile: true },
      {
        to: "/settings/providers",
        label: "模型配置",
        short: "模型",
        icon: Server,
        mobile: false,
        adminOnly: true,
      },
      {
        to: "/settings/users",
        label: "用户管理",
        short: "用户",
        icon: Users,
        mobile: false,
        adminOnly: true,
      },
      {
        to: "/settings/logs",
        label: "运行日志",
        short: "日志",
        icon: ScrollText,
        mobile: false,
        adminOnly: true,
      },
      {
        to: "/settings/upstream",
        label: "上游状态",
        short: "上游",
        icon: Activity,
        mobile: false,
        adminOnly: true,
      },
    ],
  },
];

// 扁平导航（移动端底部/悬浮导航用）
const NAV: NavItem[] = NAV_GROUPS.flatMap((g) => g.items);

const SCOPE_LABELS: Record<string, string> = {
  knowledge: "知识库",
  story: "章节",
  prompts: "提示词",
  agents: "Agent",
  assets: "素材",
  asmr: "ASMR",
};

function resultTarget(item: SearchResultItem): string {
  switch (item.scope) {
    case "story": {
      const projectId = String(item.meta?.project_id ?? "");
      const chapterId = item.scope === "story" && item.meta?.chapter_no ? item.id : "";
      return projectId
        ? `/story/${projectId}${chapterId ? `?chapter=${chapterId}` : ""}`
        : "/story";
    }
    case "knowledge":
      return "/knowledge";
    case "prompts":
      return `/prompts?q=${encodeURIComponent(item.title)}`;
    case "agents":
      return `/agents?search=${encodeURIComponent(item.title)}`;
    case "asmr":
      return `/asmr?q=${encodeURIComponent(item.title)}`;
    default:
      return "/assets";
  }
}

export function AppShell({ children }: { children: ReactNode }) {
  const host = useHost();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const themeMode = useThemeStore((s) => s.mode);
  const cycleTheme = useThemeStore((s) => s.cycle);
  const compact = host.compactMode ?? false;
  const ThemeIcon = themeMode === "dark" ? Moon : themeMode === "light" ? Sun : Monitor;
  const themeLabel = themeMode === "dark" ? "深色" : themeMode === "light" ? "浅色" : "跟随系统";
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResultItem[] | null>(null);
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const debounceRef = useRef<number | null>(null);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [moreOpen, setMoreOpen] = useState(false);
  const visibleNav = NAV.filter((n) => !n.adminOnly || user?.role === "admin");
  const mobileNav = visibleNav.filter((n) => n.mobile);
  // 底部导航：前 5 项 + 「更多」抽屉（含其余移动项 + 桌面项 + 管理项）
  const primaryNav = mobileNav.slice(0, 5);
  const restNav = [
    ...mobileNav.slice(5),
    ...visibleNav.filter((n) => !n.mobile),
  ];

  // 防抖搜索：输入停止 300ms 后查询
  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    const q = searchQ.trim();
    if (!q) {
      setSearchResults(null);
      setSearchOpen(false);
      setSearchBusy(false);
      return;
    }
    setSearchBusy(true);
    debounceRef.current = window.setTimeout(async () => {
      try {
        const r = await apiClient.get<{ items: SearchResultItem[] }>(
          `/search?q=${encodeURIComponent(q)}&limit=8`,
        );
        setSearchResults(r.items);
        setSearchOpen(true);
      } catch {
        setSearchResults([]);
      } finally {
        setSearchBusy(false);
      }
    }, 300);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [searchQ]);

  // 点击外部关闭下拉
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setSearchOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const goSearchPage = useCallback(
    (q: string) => {
      setSearchOpen(false);
      navigate(q ? `/search?q=${encodeURIComponent(q)}` : "/search");
    },
    [navigate],
  );

  // PWA 新版本提示
  const [newVersion, setNewVersion] = useState(false);
  useEffect(() => {
    const onNewVersion = () => setNewVersion(true);
    window.addEventListener("aigc:new-version", onNewVersion);
    return () => window.removeEventListener("aigc:new-version", onNewVersion);
  }, []);

  const openResult = useCallback(
    (item: SearchResultItem) => {
      setSearchOpen(false);
      navigate(resultTarget(item));
    },
    [navigate],
  );

  const grouped = (searchResults ?? []).reduce<Record<string, SearchResultItem[]>>(
    (acc, item) => {
      (acc[item.scope] ??= []).push(item);
      return acc;
    },
    {},
  );

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-background md:flex-row">
      {/* 桌面侧栏 */}
      {!compact && (
        <aside className="hidden h-dvh w-[228px] shrink-0 flex-col border-r border-border bg-surface px-3.5 py-4 md:flex">
          <div className="flex items-center gap-2.5 px-2 pb-4">
            <img
              src="/logo.png"
              alt="SAIOS"
              className="h-8 w-8 rounded-[10px] object-cover"
              draggable={false}
            />
            <span className="font-bold leading-tight tracking-tight">
              SAIOS
              <span className="block text-[10px] font-normal text-muted-foreground">
                AIGC Studio
              </span>
            </span>
          </div>
          <nav className="flex-1 space-y-1 overflow-y-auto" aria-label="主导航">
            {NAV_GROUPS.map((group) => {
              const items = group.items.filter((n) => !n.adminOnly || user?.role === "admin");
              if (items.length === 0) return null;
              return (
                <div key={group.label} className="mb-3">
                  <p className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                    {group.label}
                  </p>
                  {items.map((item) => (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      end={item.to === "/"}
                      className={({ isActive }) =>
                        cn(
                          "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors",
                          isActive
                            ? "bg-primary/12 font-semibold text-primary-text"
                            : "font-medium text-muted-foreground hover:bg-secondary hover:text-foreground",
                        )
                      }
                    >
                      <item.icon className="h-[18px] w-[18px]" aria-hidden />
                      {item.label}
                    </NavLink>
                  ))}
                </div>
              );
            })}
          </nav>
          <button
            onClick={logout}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <LogOut className="h-[18px] w-[18px]" aria-hidden />
            退出登录
          </button>
        </aside>
      )}

      <div className="flex h-dvh min-w-0 flex-1 flex-col overflow-hidden">
        {!compact && (
          <header className="z-20 flex h-15 shrink-0 items-center gap-3 border-b border-border bg-background/80 px-4 py-3 backdrop-blur md:px-6">
            <div ref={boxRef} className="relative flex-1 md:max-w-sm">
              <form
                className="relative flex h-9 items-center"
                onSubmit={(e: FormEvent) => {
                  e.preventDefault();
                  goSearchPage(searchQ.trim());
                }}
              >
                <Search
                  className="pointer-events-none absolute left-3 h-4 w-4 text-muted-foreground"
                  aria-hidden
                />
                <input
                  value={searchQ}
                  onChange={(e) => setSearchQ(e.target.value)}
                  onFocus={() => {
                    if (searchResults?.length) setSearchOpen(true);
                  }}
                  placeholder="搜索全部（知识库/章节/提示词…）"
                  aria-label="搜索全部"
                  className="h-9 w-full rounded-full border border-border-strong bg-surface py-0 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground transition-colors hover:border-primary focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </form>
              {searchOpen && searchResults && searchResults.length > 0 && (
                <div className="absolute left-0 right-0 top-11 z-50 max-h-[70vh] overflow-y-auto rounded-2xl border border-border bg-surface-raised p-2 shadow-2xl">
                  {Object.entries(grouped).map(([scope, items]) => (
                    <div key={scope} className="mb-1">
                      <p className="px-2.5 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {SCOPE_LABELS[scope] ?? scope}
                      </p>
                      {items.slice(0, 5).map((item) => (
                        <button
                          key={`${scope}-${item.id}`}
                          onClick={() => openResult(item)}
                          className="flex w-full flex-col gap-0.5 rounded-xl px-2.5 py-2 text-left hover:bg-secondary"
                        >
                          <span className="truncate text-sm font-medium text-foreground">
                            {item.title}
                          </span>
                          <span className="line-clamp-1 text-xs text-muted-foreground">
                            {item.snippet}
                          </span>
                        </button>
                      ))}
                    </div>
                  ))}
                  <button
                    onClick={() => goSearchPage(searchQ.trim())}
                    className="mt-1 w-full rounded-xl border-t border-border px-2.5 py-2 text-xs font-medium text-primary-text"
                  >
                    查看全部结果 →
                  </button>
                </div>
              )}
              {searchOpen && searchResults && searchResults.length === 0 && !searchBusy && (
                <div className="absolute left-0 right-0 top-11 z-50 rounded-2xl border border-border bg-surface-raised px-3 py-3 text-sm text-muted-foreground shadow-2xl">
                  未找到匹配内容
                </div>
              )}
            </div>
            <div className="ml-auto flex items-center gap-2">
              <button
                onClick={cycleTheme}
                aria-label={`主题：${themeLabel}（点击切换）`}
                title={`主题：${themeLabel}`}
                className="grid h-9 w-9 place-items-center rounded-full border border-border-strong text-muted-foreground hover:border-primary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <ThemeIcon className="h-4.5 w-4.5" aria-hidden />
              </button>
              <span
                className="grid h-9 w-9 place-items-center rounded-full bg-gradient-to-br from-primary to-primary-hover text-sm font-bold text-primary-foreground"
                title={user?.username}
              >
                {user?.username?.[0]?.toUpperCase() ?? "U"}
              </span>
            </div>
          </header>
        )}

        <main className="flex-1 overflow-y-auto overflow-x-hidden pb-20 md:pb-0">{children}</main>
        {newVersion && (
          <div className="fixed bottom-20 left-1/2 z-[60] flex -translate-x-1/2 items-center gap-3 rounded-full border border-border-strong bg-surface-raised px-4 py-2.5 shadow-2xl md:bottom-6">
            <span className="text-sm text-foreground">新版本已就绪</span>
            <button
              onClick={() => window.location.reload()}
              className="rounded-full bg-primary px-3 py-1 text-xs font-semibold text-primary-foreground hover:bg-primary-hover"
            >
              立即刷新
            </button>
            <button
              onClick={() => setNewVersion(false)}
              aria-label="关闭提示"
              className="text-muted-foreground hover:text-foreground"
            >
              ✕
            </button>
          </div>
        )}
        <ToastHost />

        {/* 移动端底部导航：前 5 项 + 「更多」抽屉 */}
        {!compact && (
          <nav
            className="pb-safe fixed inset-x-0 bottom-0 z-30 flex border-t border-border bg-surface md:hidden"
            aria-label="底部导航"
          >
            {primaryNav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  cn(
                    "flex flex-1 flex-col items-center gap-1 py-2 text-xs",
                    isActive ? "font-medium text-primary-text" : "text-muted-foreground",
                  )
                }
              >
                <item.icon className="h-5 w-5" aria-hidden />
                {item.short}
              </NavLink>
            ))}
            <button
              onClick={() => setMoreOpen(true)}
              aria-label="更多"
              className={cn(
                "flex flex-1 flex-col items-center gap-1 py-2 text-xs",
                moreOpen ? "font-medium text-primary-text" : "text-muted-foreground",
              )}
            >
              <MoreHorizontal className="h-5 w-5" aria-hidden />
              更多
            </button>
          </nav>
        )}

        {/* 移动端「更多」抽屉 */}
        {!compact && moreOpen && (
          <div className="fixed inset-0 z-40 md:hidden" role="presentation">
            <div
              className="absolute inset-0 bg-black/50"
              onClick={() => setMoreOpen(false)}
            />
            <div className="pb-safe absolute inset-x-0 bottom-0 rounded-t-2xl border-t border-border bg-surface-raised p-4">
              <p className="mb-3 text-sm font-semibold text-foreground">更多功能</p>
              <div className="grid grid-cols-3 gap-2">
                {restNav.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    onClick={() => setMoreOpen(false)}
                    className={({ isActive }) =>
                      cn(
                        "flex flex-col items-center gap-1.5 rounded-xl border border-border bg-surface px-2 py-3 text-xs",
                        isActive
                          ? "border-primary/40 bg-primary/10 font-medium text-primary-text"
                          : "text-muted-foreground",
                      )
                    }
                  >
                    <item.icon className="h-5 w-5" aria-hidden />
                    {item.label}
                  </NavLink>
                ))}
              </div>
              <button
                onClick={logout}
                className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl border border-border bg-surface px-3 py-2.5 text-sm font-medium text-muted-foreground"
              >
                <LogOut className="h-4 w-4" aria-hidden />
                退出登录
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
