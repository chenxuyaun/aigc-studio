import { useCallback, useEffect, useRef, useState, type ComponentType, type FormEvent, type ReactNode } from "react";

import {
  Activity,
  Bot,
  BookOpen,
  Clapperboard,
  Camera,
  Cpu,
  Film,
  FolderOpen,
  Headphones,
  Image,
  Layers,
  Library,
  Lightbulb,
  ListChecks,
  LogOut,
  MessageCircle,
  Mic,
  Monitor,
  Moon,
  MoreHorizontal,
  Music,
  Palette,
  PenLine,
  PenTool,
  ScrollText,
  Search,
  Server,
  Sun,
  UserPlus,
  Users,
  Video,
  Wand2,
  Workflow,
  Sparkles,
  BarChart3,
} from "lucide-react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

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
 * 导航分组（saiOS v2 IA）：对齐设计稿七大类——对话 / 创作引擎 / 资产中心 /
 * 角色故事 / 自动化 / 资源库 / 系统。v2 终态路由（/studio 等）在 P1-P2 落地，
 * P0 阶段先把全部 27 个悬空页露出，确保任何路由 ≤2 次点击可达。
 */
const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "对话",
    items: [
      { to: "/", label: "AI 调度大厅", short: "调度", icon: Sparkles, mobile: true },
    ],
  },
  {
    label: "创作引擎",
    items: [
      { to: "/studio", label: "统一 Studio", short: "Studio", icon: Layers, mobile: true },
      { to: "/inspiration", label: "灵感画廊", short: "灵感", icon: Lightbulb, mobile: false },
      { to: "/create/image", label: "图像生成", short: "图像", icon: Image, mobile: false },
      { to: "/create/comic", label: "漫画分镜", short: "漫画", icon: PenTool, mobile: false },
      { to: "/create/text", label: "文本写作", short: "写作", icon: PenLine, mobile: false },
      { to: "/create/audio", label: "语音合成", short: "语音", icon: Mic, mobile: false },
      { to: "/create/music", label: "音乐创作", short: "音乐", icon: Music, mobile: false },
      { to: "/create/video", label: "视频生成", short: "视频", icon: Video, mobile: false },
      { to: "/create/character-card", label: "角色捏卡", short: "捏卡", icon: UserPlus, mobile: false },
      { to: "/create/studio", label: "AI 导演", short: "导演", icon: Film, mobile: false },
      { to: "/create/prompt", label: "提示词工坊", short: "造词", icon: Wand2, mobile: false },
      { to: "/create/prompt-optimize", label: "提示词优化", short: "优词", icon: Wand2, mobile: false },
    ],
  },
  {
    label: "资产中心",
    items: [
      { to: "/works", label: "我的作品", short: "作品", icon: Clapperboard, mobile: true },
      { to: "/tasks", label: "任务中心", short: "任务", icon: ListChecks, mobile: true },
      { to: "/assets", label: "素材库", short: "素材", icon: FolderOpen, mobile: false },
      { to: "/photography", label: "写真摄影", short: "摄影", icon: Camera, mobile: false },
    ],
  },
  {
    label: "角色 & 故事",
    items: [
      { to: "/persona", label: "角色中心", short: "角色中心", icon: Users, mobile: false },
      { to: "/roleplay", label: "角色扮演", short: "角色", icon: MessageCircle, mobile: true },
      { to: "/story", label: "故事工作室", short: "故事", icon: BookOpen, mobile: false },
    ],
  },
  {
    label: "自动化",
    items: [
      { to: "/workflows", label: "工作流编排", short: "工作流", icon: Workflow, mobile: false },
      { to: "/skills", label: "技能库", short: "技能", icon: Cpu, mobile: false },
    ],
  },
  {
    label: "资源库",
    items: [
      { to: "/prompts", label: "提示词库", short: "提示词", icon: Library, mobile: false },
      { to: "/knowledge", label: "知识库", short: "知识库", icon: BookOpen, mobile: false },
      { to: "/asmr", label: "ASMR 库", short: "ASMR", icon: Headphones, mobile: false },
      { to: "/agents", label: "Agent 库", short: "Agent", icon: Bot, mobile: false },
      { to: "/search", label: "全域搜索", short: "搜索", icon: Search, mobile: false },
    ],
  },
  {
    label: "系统",
    items: [
      { to: "/dashboard", label: "数据看板", short: "看板", icon: BarChart3, mobile: false },
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
  const location = useLocation();
  // 收敛：默认折叠「资源/角色/系统」组，只展开「创作」主入口（点组标题展开，功能不删只收纳）
  const [collapsedGroups, setCollapsedGroups] = useState<string[]>(() =>
    NAV_GROUPS.filter((g) => g.label !== "创作").map((g) => g.label),
  );
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
              const isCollapsed = collapsedGroups.includes(group.label);
              // 组内有当前激活项时强制展开（保证用户不会迷路）
              const activeInGroup = items.some((it) => it.to === location.pathname);
              const showItems = !isCollapsed || activeInGroup;
              return (
                <div key={group.label} className="mb-3">
                  <button
                    type="button"
                    onClick={() =>
                      setCollapsedGroups((prev) =>
                        prev.includes(group.label)
                          ? prev.filter((g) => g !== group.label)
                          : [...prev, group.label],
                      )
                    }
                    className="mb-1 flex w-full items-center justify-between px-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60 hover:text-foreground"
                  >
                    <span>{group.label}</span>
                    <span className="text-[9px]">{showItems ? "▾" : "▸"}</span>
                  </button>
                  {showItems &&
                    items.map((item) => (
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
          <header className="relative z-40 flex h-15 shrink-0 items-center gap-3 border-b border-border bg-background/80 px-4 py-3 backdrop-blur md:px-6">
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
