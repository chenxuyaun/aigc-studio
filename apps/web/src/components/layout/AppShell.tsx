import { useCallback, useEffect, useRef, useState, type ComponentType, type FormEvent, type ReactNode } from "react";

import {
  Layers,
  Library,
  LogOut,
  MessageCircle,
  Monitor,
  Moon,
  MoreHorizontal,
  Palette,
  ScrollText,
  Search,
  Server,
  Sun,
  Users,
  Sparkles,
  BarChart3,
} from "lucide-react";
import { NavLink, useNavigate } from "react-router-dom";

import { useHost } from "@/microfrontend/hostContext";
import { cn } from "@/lib/cn";
import { apiClient } from "@/lib/apiClient";
import { ToastHost } from "@/components/ui/Toast";
import { useAuthStore } from "@/stores/auth";
import { useThemeStore, SKINS } from "@/stores/theme";
import type { SearchResultItem } from "@aigc/shared-types";

interface NavItem {
  to: string;
  label: string;
  short: string;
  icon: ComponentType<{ className?: string }>;
  mobile: boolean;
  adminOnly?: boolean;
}

/**
 * v11 四场所导航（设计稿 saios_v11_0.html）：派活中枢 / 创作工坊 / 资产藏馆 / 角色宇宙。
 * 顶栏居中胶囊四键；系统组（adminOnly）收进右上「更多」抽屉。
 * 能力=对话芯片与 Studio 引擎 tab；产物=/library 类型 tab；场所才配拥有导航项。
 */
const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "场所",
    items: [
      { to: "/", label: "派活中枢", short: "派活", icon: Sparkles, mobile: true },
      { to: "/studio", label: "创作工坊", short: "工坊", icon: Layers, mobile: true },
      { to: "/library/works", label: "资产藏馆", short: "藏馆", icon: Library, mobile: true },
      { to: "/roleplay", label: "角色宇宙", short: "角色", icon: MessageCircle, mobile: true },
    ],
  },
  {
    label: "系统",
    items: [
      { to: "/dashboard", label: "系统看板", short: "看板", icon: BarChart3, mobile: false, adminOnly: true },
      {
        to: "/settings/providers",
        label: "模型中心",
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
    ],
  },
];

// 扁平导航（移动端底部/悬浮导航用）：底栏 = 主导航 4 项 + 更多抽屉
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
      return "/library/knowledge";
    case "prompts":
      return `/library/prompts?q=${encodeURIComponent(item.title)}`;
    case "agents":
      return `/library/agents?search=${encodeURIComponent(item.title)}`;
    case "asmr":
      return `/library/asmr?q=${encodeURIComponent(item.title)}`;
    default:
      return "/library/assets";
  }
}

export function AppShell({ children }: { children: ReactNode }) {
  const host = useHost();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const themeMode = useThemeStore((s) => s.mode);
  const cycleTheme = useThemeStore((s) => s.cycle);
  const skin = useThemeStore((s) => s.skin);
  const setSkin = useThemeStore((s) => s.setSkin);
  const [skinOpen, setSkinOpen] = useState(false);
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
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const visibleNav = NAV.filter((n) => !n.adminOnly || user?.role === "admin");
  const mobileNav = visibleNav.filter((n) => n.mobile);
  // 底部导航：前 4 项 + 「更多」抽屉（含其余移动项 + 桌面项 + 管理项）
  const primaryNav = mobileNav.slice(0, 4);
  const restNav = [
    ...mobileNav.slice(4),
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
    <div className="flex h-dvh flex-col overflow-hidden bg-background">
      <div className="flex h-dvh min-w-0 flex-1 flex-col overflow-hidden">
        {!compact && (
          <header className="relative z-40 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background/80 px-3 backdrop-blur md:px-5">
            {/* v11 品牌标 */}
            <button
              type="button"
              aria-label="返回派活中枢"
              className="flex shrink-0 cursor-pointer select-none items-center gap-2"
              onClick={() => navigate("/")}
            >
              <span className="grid h-7 w-7 place-items-center rounded-xl bg-foreground font-serif text-xs font-medium text-background">
                s
              </span>
              <span className="hidden items-baseline gap-1.5 md:flex">
                <span className="font-serif text-sm font-medium tracking-wide">saiOS</span>
                <span className="rounded border border-primary/25 bg-primary/10 px-1 py-px font-mono text-[10px] text-primary-text">
                  v11.0
                </span>
              </span>
            </button>

            {/* 顶栏胶囊四键（设计稿中心分段导航，md+ 显示） */}
            <nav
              className="mx-auto hidden items-center gap-1 rounded-full border border-border bg-black/[0.03] p-1 dark:bg-white/[0.04] md:flex"
              aria-label="场所"
            >
              {primaryNav.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs font-medium transition-colors",
                      isActive
                        ? "bg-surface text-foreground shadow-xs"
                        : "text-muted-foreground hover:text-foreground",
                    )
                  }
                >
                  <item.icon className="h-3.5 w-3.5" aria-hidden />
                  {item.label}
                </NavLink>
              ))}
            </nav>

            {/* 右侧动作：搜索（浮层）＋皮肤＋主题＋更多下拉＋头像 */}
            <div className="ml-auto flex items-center gap-2">
              <div ref={boxRef} className="relative">
                <button
                  onClick={() => setSearchOpen((v) => !v)}
                  aria-label="搜索全部"
                  title="搜索全部"
                  className="grid h-9 w-9 place-items-center rounded-full border border-border-strong text-muted-foreground hover:border-primary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Search className="h-4.5 w-4.5" aria-hidden />
                </button>
                {searchOpen && (
                  <div className="absolute right-0 top-11 z-50 w-[min(92vw,26rem)] rounded-2xl border border-border bg-surface-raised p-2 shadow-2xl">
                    <form
                      className="flex h-9 items-center"
                      onSubmit={(e: FormEvent) => {
                        e.preventDefault();
                        goSearchPage(searchQ.trim());
                      }}
                    >
                      <input
                        value={searchQ}
                        onChange={(e) => setSearchQ(e.target.value)}
                        onFocus={() => {
                          if (searchResults?.length) setSearchOpen(true);
                        }}
                        placeholder="搜索全部（知识库/章节/提示词…）"
                        aria-label="搜索全部"
                        autoFocus
                        className="h-9 w-full rounded-xl border border-border-strong bg-surface py-0 pl-3 pr-3 text-sm text-foreground placeholder:text-muted-foreground transition-colors hover:border-primary focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring"
                      />
                    </form>
                    {searchResults && searchResults.length > 0 && (
                      <div className="max-h-[60vh] overflow-y-auto pt-1">
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
                    {searchResults && searchResults.length === 0 && !searchBusy && searchQ.trim() !== "" && (
                      <div className="px-3 py-3 text-sm text-muted-foreground">未找到匹配内容</div>
                    )}
                  </div>
                )}
              </div>
              {/* 系统「更多」下拉（md+，含 admin 专属项，restNav 已按角色过滤） */}
              <div className="relative hidden md:block">
                <button
                  onClick={() => setMoreMenuOpen((v) => !v)}
                  aria-label="更多"
                  title="更多"
                  className="grid h-9 w-9 place-items-center rounded-full border border-border-strong text-muted-foreground hover:border-primary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <MoreHorizontal className="h-4.5 w-4.5" aria-hidden />
                </button>
                {moreMenuOpen && (
                  <div className="absolute right-0 top-11 z-50 w-52 rounded-2xl border border-border bg-surface-raised p-1.5 shadow-2xl">
                    <p className="px-3 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                      系统
                    </p>
                    {restNav.map((item) => (
                      <NavLink
                        key={item.to}
                        to={item.to}
                        onClick={() => setMoreMenuOpen(false)}
                        className={({ isActive }) =>
                          cn(
                            "flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm text-muted-foreground hover:bg-muted",
                            isActive ? "text-primary-text" : "",
                          )
                        }
                      >
                        <item.icon className="h-4 w-4" aria-hidden />
                        {item.label}
                      </NavLink>
                    ))}
                    <button
                      onClick={logout}
                      className="mt-1 flex w-full items-center gap-2.5 rounded-xl border-t border-border px-3 py-2.5 text-sm font-medium text-muted-foreground hover:bg-muted"
                    >
                      <LogOut className="h-4 w-4" aria-hidden />
                      退出登录
                    </button>
                  </div>
                )}
              </div>
              {/* v2 P3 皮肤引擎：四皮肤全局切换（品牌主色即时生效） */}
              <div className="relative">
                <button
                  onClick={() => setSkinOpen((v) => !v)}
                  aria-label={`皮肤：${SKINS.find((s) => s.key === skin)?.label ?? ""}`}
                  title={`皮肤：${SKINS.find((s) => s.key === skin)?.label ?? ""}`}
                  className="grid h-9 w-9 place-items-center rounded-full border border-border-strong text-muted-foreground hover:border-primary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <Palette className="h-4.5 w-4.5" aria-hidden />
                </button>
                {skinOpen && (
                  <div className="absolute right-0 top-11 z-50 w-44 rounded-2xl border border-border bg-surface-raised p-1.5 shadow-2xl">
                    {SKINS.map((s) => (
                      <button
                        key={s.key}
                        onClick={() => {
                          setSkin(s.key);
                          setSkinOpen(false);
                        }}
                        className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left text-sm text-muted-foreground hover:bg-muted ${skin === s.key ? "text-primary-text" : ""}`}
                      >
                        <span className="h-3.5 w-3.5 rounded-full border border-black/10" style={{ background: s.dot }} />
                        {s.label}
                        {skin === s.key && <span className="ml-auto font-bold">✓</span>}
                      </button>
                    ))}
                  </div>
                )}
              </div>
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

        <main className="relative flex min-h-0 flex-1 flex-col overflow-y-auto overflow-x-hidden pb-20 md:pb-0">
          {children}
        </main>
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
