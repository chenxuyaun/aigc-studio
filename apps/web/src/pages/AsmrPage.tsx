import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Clock, Eye, Search as SearchIcon, Star } from "lucide-react";

import { Dialog } from "@/components/ui/Dialog";
import { PageHeader } from "@/components/layout/PageHeader";
import { useToast } from "@/components/ui/Toast";
import { apiBaseUrl, apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";
import type { AsmrWork } from "@aigc/shared-types";

const ADULT_KEY = "asmr_adult_unlocked";
const TITLE_CLICKS_TO_UNLOCK = 7;
const CLICK_WINDOW_MS = 800;

interface ListResponse {
  items: AsmrWork[];
  total: number;
  page: number;
  pages: number;
}

interface Stats {
  total: number;
  nsfw_count: number;
  general_count: number;
  by_source: Record<string, number>;
  last_sync_at: string | null;
}

interface DiskItem {
  id: string;
  path: string;
  name: string;
  size_bytes: number;
  is_dir: boolean;
  modified: string | null;
}

const NSFW_FILTERS = [
  { v: "all", label: "全部" },
  { v: "general", label: "全年龄" },
  { v: "adult", label: "成人" },
] as const;

const LANG_FILTERS = [
  { v: "all", label: "全部语言" },
  { v: "zh", label: "中文版" },
  { v: "jp", label: "日文" },
  { v: "en", label: "英文" },
] as const;

const LANG_LABELS: Record<string, string> = {
  JPN: "日",
  CHI_HANS: "中",
  CHI: "中",
  ZHS: "中",
  ZHT: "中",
  ENG: "英",
};

const SORTS = [
  { v: "date", label: "最新" },
  { v: "rate", label: "评分" },
  { v: "dl_count", label: "下载数" },
  { v: "price", label: "价格" },
] as const;

function formatDuration(sec: number): string {
  if (!sec) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h${m}m` : `${m}m`;
}

function formatPrice(yen: number): string {
  return yen > 0 ? `¥${yen.toLocaleString()}` : "";
}

export function AsmrPage() {
  const [params] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [nsfw, setNsfw] = useState<string>("all");
  const [lang, setLang] = useState<string>("all");
  const [sort, setSort] = useState<string>("date");
  const [tag, setTag] = useState("");
  const [items, setItems] = useState<AsmrWork[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [busy, setBusy] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);
  const [detail, setDetail] = useState<AsmrWork | null>(null);
  const [similar, setSimilar] = useState<AsmrWork[]>([]);
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [favorites, setFavorites] = useState<Set<string>>(new Set());
  const [view, setView] = useState<"works" | "disk">("works");
  // diskQ 由顶部搜索框 q 复用
  const [diskItems, setDiskItems] = useState<DiskItem[]>([]);
  const [diskTotal, setDiskTotal] = useState(0);
  const [diskBusy, setDiskBusy] = useState(false);
  const [adultUnlocked, setAdultUnlocked] = useState(
    () => localStorage.getItem(ADULT_KEY) === "1",
  );
  const titleClicks = useRef<{ count: number; last: number }>({ count: 0, last: 0 });
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  // useToast 返回值每次渲染都是新对象：解构出稳定引用后再用（避免依赖对象触发无限请求）
  const { success: toastSuccess, info: toastInfo, error: toastError } = useToast();

  // 未解锁：强制全年龄视图（成人内容完全不可见）
  const effectiveNsfw = adultUnlocked ? nsfw : "general";

  const load = useCallback(async (p: number) => {
    setBusy(true);
    try {
      const params = new URLSearchParams({
        page: String(p),
        page_size: "24",
        nsfw: effectiveNsfw,
        lang,
        sort,
      });
      if (search) params.set("q", search);
      if (tag) params.set("tag", tag);
      const r = await apiClient.get<ListResponse>(`/asmr/works?${params.toString()}`);
      setItems((prev) => (p === 1 ? r.items : [...prev, ...r.items]));
      setTotal(r.total);
      setPages(r.pages);
    } catch {
      // 翻页失败保留已加载内容，仅首页失败清空
      if (p === 1) setItems([]);
      toastError("作品加载失败，请稍后重试");
    } finally {
      setBusy(false);
    }
  }, [search, effectiveNsfw, lang, sort, tag, toastError]);

  // 无限滚动：哨兵进入视口自动加载下一页
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && page < pages && !busy) {
          const next = page + 1;
          setPage(next);
          void load(next);
        }
      },
      { rootMargin: "400px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [page, pages, busy, load]);

  const loadFavorites = useCallback(async (p: number) => {
    setBusy(true);
    try {
      const r = await apiClient.get<ListResponse>(`/asmr/favorites?page=${p}&page_size=24`);
      setItems((prev) => (p === 1 ? r.items : [...prev, ...r.items]));
      setTotal(r.total);
      setPages(r.pages);
    } catch {
      if (p === 1) setItems([]);
      toastError("收藏列表加载失败");
    } finally {
      setBusy(false);
    }
  }, [toastError]);

  // 收藏状态：进入时拉取（收藏列表 id 集合，分页取前 200）
  useEffect(() => {
    apiClient
      .get<ListResponse>("/asmr/favorites?page=1&page_size=200")
      .then((r) => setFavorites(new Set(r.items.map((i) => i.id))))
      .catch(() => setFavorites(new Set()));
  }, []);

  useEffect(() => {
    setPage(1);
    if (favoritesOnly) void loadFavorites(1);
    else void load(1);
  }, [favoritesOnly, load, loadFavorites]);

  const toggleFavorite = useCallback(
    async (workId: string) => {
      const isFav = favorites.has(workId);
      try {
        if (isFav) {
          await apiClient.del(`/asmr/works/${workId}/favorite`);
          setFavorites((prev) => {
            const next = new Set(prev);
            next.delete(workId);
            return next;
          });
          if (favoritesOnly) {
            setItems((prev) => prev.filter((i) => i.id !== workId));
          }
        } else {
          await apiClient.post(`/asmr/works/${workId}/favorite`);
          setFavorites((prev) => new Set(prev).add(workId));
        }
      } catch {
        toastError(isFav ? "取消收藏失败" : "收藏失败，请稍后重试");
      }
    },
    [favorites, favoritesOnly, toastError],
  );

  useEffect(() => {
    apiClient
      .get<Stats>("/asmr/stats")
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  const unlockAdult = useCallback(() => {
    setAdultUnlocked(true);
    localStorage.setItem(ADULT_KEY, "1");
    toastSuccess("已显示全部内容");
  }, [toastSuccess]);

  const lockAdult = useCallback(() => {
    setAdultUnlocked(false);
    localStorage.setItem(ADULT_KEY, "0");
    toastInfo("已隐藏成人内容");
  }, [toastInfo]);

  // 网盘资源库搜索
  const searchDisk = useCallback(async () => {
    setDiskBusy(true);
    try {
      const r = await apiClient.get<{ items: DiskItem[]; total: number }>(
        `/asmr/disk?q=${encodeURIComponent(q.trim())}`,
      );
      setDiskItems(r.items);
      setDiskTotal(r.total);
    } catch {
      setDiskItems([]);
      toastError("网盘资源搜索失败");
    } finally {
      setDiskBusy(false);
    }
  }, [q, toastError]);

  // 隐藏解锁手势：快速连点标题 7 次
  const onTitleClick = useCallback(() => {
    const now = Date.now();
    const c = titleClicks.current;
    if (now - c.last > CLICK_WINDOW_MS) c.count = 0;
    c.count += 1;
    c.last = now;
    if (c.count >= TITLE_CLICKS_TO_UNLOCK) {
      c.count = 0;
      unlockAdult();
    }
  }, [unlockAdult]);

  const tagCloud = useMemo(() => {
    const counter = new Map<string, number>();
    for (const item of items) {
      for (const t of item.tags ?? []) {
        const name = t.zh || t.name;
        counter.set(name, (counter.get(name) ?? 0) + 1);
      }
    }
    return [...counter.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
  }, [items]);

  const openDetail = async (id: string) => {
    try {
      const r = await apiClient.get<{ work: AsmrWork }>(`/asmr/works/${id}`);
      setDetail(r.work);
      // 相似推荐（详情打开时并行拉取）
      apiClient
        .get<{ items: AsmrWork[] }>(`/asmr/works/${id}/similar`)
        .then((sr) => setSimilar(sr.items))
        .catch(() => setSimilar([]));
    } catch {
      setDetail(null);
      setSimilar([]);
      toastError("详情加载失败");
    }
  };

  return (
    <div>
      <PageHeader
        title="ASMR 库"
        onTitleClick={onTitleClick}
        description={
          !adultUnlocked
            ? stats
              ? `聚合 ${stats.general_count.toLocaleString()} 部全年龄作品 · 本地保存，源站关闭也可用`
              : "多来源 ASMR 作品元数据聚合"
            : stats
              ? `聚合 ${stats.total.toLocaleString()} 部作品（全年龄 ${stats.general_count} · 成人 ${stats.nsfw_count}）· 本地保存，源站关闭也可用`
              : "多来源 ASMR 作品元数据聚合"
        }
        actions={
          adultUnlocked ? (
            <button
              onClick={lockAdult}
              title="隐藏成人内容"
              className="flex h-9 items-center gap-1.5 rounded-full border border-border-strong px-3 text-xs text-muted-foreground hover:border-primary hover:text-foreground"
            >
              <Eye className="h-3.5 w-3.5" aria-hidden />
              隐藏成人内容
            </button>
          ) : undefined
        }
      >
        <form
          className="flex w-full max-w-xl items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (view === "disk") void searchDisk();
            else setSearch(q.trim());
          }}
        >
          <div className="relative flex-1">
            <SearchIcon
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={view === "disk" ? "搜索网盘资源（声优 / 作品名）…" : "搜索标题 / 社团 / 声优…"}
              className="h-10 w-full rounded-full border border-border-strong bg-surface py-0 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <button
            type="submit"
            className="h-10 rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary-hover"
          >
            搜索
          </button>
        </form>
      </PageHeader>

      <div className="space-y-3 p-4 md:p-6">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded-full border border-border bg-surface p-1">
            {(["works", "disk"] as const).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={cn(
                  "rounded-full px-3 py-1 text-xs",
                  view === v
                    ? "bg-primary font-medium text-primary-foreground"
                    : "text-muted-foreground",
                )}
              >
                {v === "works" ? "作品库" : "网盘资源"}
              </button>
            ))}
          </div>
          {view === "works" && (
            <>
              <div className="flex items-center gap-1 rounded-full border border-border bg-surface p-1">
                {NSFW_FILTERS.filter((f) => adultUnlocked || f.v !== "adult").map((f) => (
                  <button
                    key={f.v}
                    onClick={() => setNsfw(f.v)}
                    className={cn(
                      "rounded-full px-3 py-1 text-xs",
                      effectiveNsfw === f.v
                        ? "bg-primary font-medium text-primary-foreground"
                        : "text-muted-foreground",
                    )}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-1 rounded-full border border-border bg-surface p-1">
                {LANG_FILTERS.map((f) => (
                  <button
                    key={f.v}
                    onClick={() => setLang(f.v)}
                    className={cn(
                      "rounded-full px-3 py-1 text-xs",
                      lang === f.v
                        ? "bg-primary font-medium text-primary-foreground"
                        : "text-muted-foreground",
                    )}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <button
                onClick={() => setFavoritesOnly((v) => !v)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs",
                  favoritesOnly
                    ? "border-primary/40 bg-primary/10 font-medium text-primary"
                    : "border-border bg-surface text-muted-foreground",
                )}
              >
                ♥ 仅收藏{favoritesOnly ? `（${total}）` : ""}
              </button>
            </>
          )}
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value)}
            className="h-8 rounded-full border border-border bg-surface px-3 text-xs text-foreground"
          >
            {SORTS.map((s) => (
              <option key={s.v} value={s.v}>{s.label}</option>
            ))}
          </select>
          {tag && (
            <button
              onClick={() => setTag("")}
              className="rounded-full bg-primary/10 px-3 py-1 text-xs font-medium text-primary"
            >
              {tag} ✕
            </button>
          )}
          <span className="ml-auto text-xs text-muted-foreground">
            {total.toLocaleString()} 部
          </span>
        </div>

        {tagCloud.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            {tagCloud.map(([name, count]) => (
              <button
                key={name}
                onClick={() => setTag(tag === name ? "" : name)}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-xs",
                  tag === name
                    ? "border-primary/40 bg-primary/10 font-medium text-primary"
                    : "border-border bg-surface text-muted-foreground",
                )}
              >
                {name} {count}
              </button>
            ))}
          </div>
        )}

        {view === "disk" ? (
          <>
            {diskBusy && <p className="text-sm text-muted-foreground">搜索中…</p>}
            {!diskBusy && diskItems.length === 0 && (
              <p className="pt-10 text-center text-sm text-muted-foreground">
                输入声优 / 作品名搜索网盘资源（asmrgay 目录索引）
              </p>
            )}
            {diskItems.length > 0 && (
              <>
                <p className="text-xs text-muted-foreground">共 {diskTotal} 个资源条目</p>
                <div className="space-y-1.5">
                  {diskItems.map((d) => (
                    <div
                      key={d.id}
                      className="flex items-center gap-3 rounded-xl border border-border bg-surface px-3 py-2"
                    >
                      <span className="shrink-0 text-muted-foreground">
                        {d.is_dir ? "📁" : "📄"}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm text-foreground">{d.name}</p>
                        <p className="truncate text-[11px] text-muted-foreground">{d.path}</p>
                      </div>
                      {!d.is_dir && d.size_bytes > 0 && (
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {(d.size_bytes / 1024 / 1024).toFixed(0)}MB
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        ) : (
          <>
            {busy && items.length === 0 && <p className="text-sm text-muted-foreground">加载中…</p>}
            {!busy && items.length === 0 && (
              <p className="pt-10 text-center text-sm text-muted-foreground">
                暂无作品。管理员可在模型配置页旁的「ASMR 同步」触发首次全量采集。
              </p>
            )}

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {items.map((w) => (
            <button
              key={w.id}
              onClick={() => void openDetail(w.id)}
              className="group relative overflow-hidden rounded-2xl border border-border bg-surface text-left transition-colors hover:border-border-strong"
            >
              <div className="relative aspect-square w-full overflow-hidden bg-secondary/40">
                {w.thumbnail_url ? (
                  <img
                    src={`${apiBaseUrl()}/asmr/cover/${w.id}`}
                    alt={w.title}
                    loading="lazy"
                    className="h-full w-full object-cover transition-transform group-hover:scale-105"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = "none";
                    }}
                  />
                ) : (
                  <div className="grid h-full w-full place-items-center text-xs text-muted-foreground">
                    无封面
                  </div>
                )}
                {w.nsfw && (
                  <span className="absolute right-1.5 top-1.5 rounded bg-danger/85 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                    R18
                  </span>
                )}
                {w.has_chinese && (
                  <span
                    className="absolute left-1.5 top-1.5 rounded bg-primary/90 px-1.5 py-0.5 text-[10px] font-semibold text-primary-foreground"
                    title="含中文版"
                  >
                    中
                  </span>
                )}
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.stopPropagation();
                    void toggleFavorite(w.id);
                  }}
                  onKeyDown={(e) => {
                    // 键盘可达：Enter/Space 触发收藏（按钮内嵌交互元素，不能再用 <button>）
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      e.stopPropagation();
                      void toggleFavorite(w.id);
                    }
                  }}
                  aria-label={favorites.has(w.id) ? "取消收藏" : "收藏"}
                  className={`absolute bottom-1.5 right-1.5 grid h-7 w-7 cursor-pointer place-items-center rounded-full text-sm shadow ${
                    favorites.has(w.id)
                      ? "bg-danger/90 text-white"
                      : "bg-black/45 text-white/90 hover:bg-black/65"
                  }`}
                >
                  {favorites.has(w.id) ? "♥" : "♡"}
                </span>
              </div>
              <div className="space-y-1 p-2.5">
                <p className="line-clamp-2 text-xs font-medium leading-snug text-foreground">
                  {w.title}
                </p>
                <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                  {(w.langs ?? []).length > 0 && (
                    <span className="flex flex-wrap gap-0.5">
                      {(w.langs ?? [])
                        .map((l) => LANG_LABELS[l] ?? l.slice(0, 1))
                        .slice(0, 3)
                        .map((l, i) => (
                          <span
                            key={`${l}-${i}`}
                            className="rounded bg-secondary px-1 py-px text-[9px]"
                          >
                            {l}
                          </span>
                        ))}
                    </span>
                  )}
                  {w.rate_average > 0 && (
                    <span className="flex items-center gap-0.5 text-amber-500">
                      <Star className="h-3 w-3" aria-hidden /> {w.rate_average.toFixed(2)}
                    </span>
                  )}
                  {w.duration_seconds > 0 && (
                    <span className="flex items-center gap-0.5">
                      <Clock className="h-3 w-3" aria-hidden /> {formatDuration(w.duration_seconds)}
                    </span>
                  )}
                  <span className="ml-auto">{formatPrice(w.price)}</span>
                </div>
              </div>
            </button>
          ))}
        </div>

        {page < pages && (
          <div ref={sentinelRef} className="flex justify-center pt-2">
            <span className="text-xs text-muted-foreground">
              {busy ? "加载中…" : "滚动加载更多 ↓"}
            </span>
          </div>
        )}
          </>
        )}
      </div>

      <Dialog open={detail !== null} onClose={() => setDetail(null)} title={detail?.title ?? ""}>
        {detail && (
          <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto">
            <div className="flex gap-3">
              {detail.cover_url ? (
                <img
                  src={`${apiBaseUrl()}/asmr/cover/${detail.id}`}
                  alt={detail.title}
                  className="h-36 w-36 shrink-0 rounded-xl object-cover"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = "none";
                  }}
                />
              ) : null}
              <div className="min-w-0 flex-1 space-y-1.5 text-sm">
                <p className="text-xs text-muted-foreground">
                  <span className="font-mono">{detail.source_work_id}</span>
                  {detail.nsfw ? " · R18" : " · 全年龄"}
                </p>
                {detail.circle_name && (
                  <p className="text-xs text-muted-foreground">社团：{detail.circle_name}</p>
                )}
                {detail.rate_average > 0 && (
                  <p className="flex items-center gap-1 text-xs text-amber-500">
                    <Star className="h-3.5 w-3.5" aria-hidden />
                    {detail.rate_average.toFixed(2)} · {detail.dl_count.toLocaleString()} 下载
                  </p>
                )}
                <p className="text-xs text-muted-foreground">
                  {formatDuration(detail.duration_seconds)} · {formatPrice(detail.price)}
                  {detail.release_date ? ` · ${detail.release_date.slice(0, 10)}` : ""}
                </p>
                {(detail.langs ?? []).length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    语言：{(detail.langs ?? []).join(" / ")}
                    {detail.has_chinese ? " · 含中文版" : ""}
                  </p>
                )}
              </div>
            </div>
            {(detail.vas ?? []).length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">声优</p>
                <div className="flex flex-wrap gap-1.5">
                  {(detail.vas ?? []).map((v) => (
                    <span key={v} className="rounded-full bg-secondary px-2.5 py-0.5 text-xs">
                      {v}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {(detail.tags ?? []).length > 0 && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">标签</p>
                <div className="flex flex-wrap gap-1.5">
                  {(detail.tags ?? []).map((t) => (
                    <span key={t.name} className="rounded-full border border-border bg-surface px-2.5 py-0.5 text-xs">
                      {t.zh || t.name}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {detail.source_url && (
              <a
                href={detail.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-primary underline"
              >
                查看源站作品页 ↗
              </a>
            )}
            <button
              onClick={() => void toggleFavorite(detail.id)}
              className={`mt-1 self-start rounded-full px-4 py-1.5 text-xs font-medium ${
                favorites.has(detail.id)
                  ? "bg-danger/10 text-danger"
                  : "border border-border-strong text-foreground hover:border-primary"
              }`}
            >
              {favorites.has(detail.id) ? "♥ 已收藏（点击取消）" : "♡ 收藏"}
            </button>
            {similar.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium text-muted-foreground">相似作品</p>
                <div className="grid grid-cols-3 gap-2">
                  {similar.map((s) => (
                    <button
                      key={s.id}
                      onClick={() => void openDetail(s.id)}
                      className="overflow-hidden rounded-xl border border-border bg-surface text-left hover:border-border-strong"
                    >
                      <div className="aspect-square w-full bg-secondary/40">
                        {s.thumbnail_url ? (
                          <img
                            src={`${apiBaseUrl()}/asmr/cover/${s.id}`}
                            alt={s.title}
                            loading="lazy"
                            className="h-full w-full object-cover"
                            onError={(e) => {
                              (e.target as HTMLImageElement).style.display = "none";
                            }}
                          />
                        ) : null}
                      </div>
                      <p className="line-clamp-2 p-1.5 text-[10px] leading-snug text-foreground">
                        {s.title}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Dialog>
    </div>
  );
}
