import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  BookOpen,
  Clock3,
  Film,
  ImageIcon,
  Layers,
  MessageCircle,
  Music,
  RefreshCw,
  Sparkles,
  Users,
  Wand2,
  XCircle,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { Dialog } from "@/components/ui/Dialog";
import { apiClient } from "@/lib/apiClient";
import { copyShareUrl } from "@/lib/share";
import type { ChatSession } from "@/pages/roleplay/types";
import { copyText } from "@/lib/clipboard";

/* ------------------------------------------------------------------ */
/* 类型                                                                */
/* ------------------------------------------------------------------ */

/** /generations/recent 返回的作品预览项（后端 recent.py _to_preview） */
interface WorkPreview {
  id: string;
  task_type: string;
  model?: string | null;
  status: string;
  created_at?: string | null;
  progress?: number | null;
  asset_url?: string | null;
  cover_url?: string | null;
  prompt?: string | null;
  title?: string | null;
  panel_count?: number | null;
}

interface StoryProjectItem {
  id: string;
  title: string;
  genre: string;
  status: string;
  updated_at: string;
}

interface CharacterItem {
  asset_id: string;
  name?: string;
  filename: string;
}

interface MusicWorkItem {
  id: string;
  title: string;
  theme: string;
  style: string;
  lyrics: string;
  chords: string;
  arrangement: string;
  style_en: string;
  source: string;
  tags: string;
  created_at: string;
}

const TYPE_LABELS: Record<string, string> = {
  image: "图片",
  comic: "漫画",
  audio: "语音",
  music: "音乐",
  video: "视频",
};

const TYPE_ICONS: Record<string, typeof ImageIcon> = {
  image: ImageIcon,
  comic: Layers,
  audio: MessageCircle,
  music: Music,
  video: Film,
};

const STATUS_CHIPS = [
  { v: "all", label: "全部" },
  { v: "succeeded", label: "✅ 成品" },
  { v: "active", label: "⏳ 进行中" },
  { v: "failed", label: "❌ 失败" },
] as const;

const ACTIVE_STATUSES = new Set(["queued", "processing"]);
const PAGE_STEP = 24;

function fmtTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/* ================================================================== */
/* 作品库页：Tab1 创作产物聚合墙（治产出裂成四处） + Tab2 音乐作品       */
/* ================================================================== */

export function WorksPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState<"gallery" | "music">("gallery");

  return (
    <div>
      <PageHeader
        title="作品库"
        description="所有生成产物汇聚一处：成品、进行中、失败一目了然，可回 Studio 再创作"
      />
      <div className="flex gap-1 border-b border-border px-4 md:px-6">
        {(
          [
            { k: "gallery", label: "🎨 创作产物" },
            { k: "music", label: "🎵 音乐作品（圆桌定稿）" },
          ] as const
        ).map((t) => (
          <button
            key={t.k}
            onClick={() => setTab(t.k)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm transition-colors ${
              tab === t.k
                ? "border-primary font-semibold text-primary-text"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "gallery" ? <GalleryTab navigate={navigate} /> : <MusicTab />}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Tab 1 · 创作产物聚合墙                                               */
/* ------------------------------------------------------------------ */

function GalleryTab({ navigate }: { navigate: ReturnType<typeof useNavigate> }) {
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] =
    useState<(typeof STATUS_CHIPS)[number]["v"]>("all");
  const [items, setItems] = useState<WorkPreview[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [limit, setLimit] = useState(PAGE_STEP);
  const [detail, setDetail] = useState<WorkPreview | null>(null);
  const [busyId, setBusyId] = useState("");
  const [sharingId, setSharingId] = useState("");
  const [shareTip, setShareTip] = useState("");

  /** 批12：一键把成品发布到社区分享墙（图片帖，带 prompt 作为介绍） */
  async function shareToCommunity(w: WorkPreview) {
    const url = (w.asset_url || w.cover_url) as string;
    setSharingId(w.id);
    try {
      await apiClient.post("/community/posts", {
        title: (w.title?.trim() || w.prompt?.slice(0, 60) || "我的 AI 作品").slice(0, 120),
        content: w.prompt?.slice(0, 2000) ?? "",
        kind: "image",
        image_url: url,
      });
      setShareTip("✓ 已发布到分享墙");
      setTimeout(() => setShareTip(""), 2500);
    } catch {
      setShareTip("分享失败，请稍后再试");
      setTimeout(() => setShareTip(""), 2500);
    } finally {
      setSharingId("");
    }
  }

  const load = useCallback(
    async (lim = limit) => {
      try {
        setError("");
        const params = new URLSearchParams({
          limit: String(lim),
          status: statusFilter,
        });
        if (typeFilter) params.set("task_type", typeFilter);
        const res = await apiClient.get<{ success: boolean; items: WorkPreview[] }>(
          `/generations/recent?${params.toString()}`,
        );
        setItems(res.items);
      } catch (e) {
        setError(e instanceof Error ? e.message : "加载失败");
      } finally {
        setLoading(false);
      }
    },
    [limit, statusFilter, typeFilter],
  );

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  // 有进行中任务时自动轮询（5s），全部终态即停
  const hasActive = useMemo(
    () => items.some((w) => ACTIVE_STATUSES.has(w.status)),
    [items],
  );
  const pollRef = useRef<number | null>(null);
  useEffect(() => {
    if (!hasActive) return;
    pollRef.current = window.setInterval(() => void load(), 5000);
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
  }, [hasActive, load]);

  async function cancelTask(id: string) {
    setBusyId(id);
    try {
      await apiClient.post(`/tasks/${id}/cancel`);
      await load();
    } catch {
      /* 忽略 */
    } finally {
      setBusyId("");
    }
  }

  async function retryTask(id: string) {
    setBusyId(id);
    try {
      await apiClient.post(`/tasks/${id}/retry`);
      setStatusFilter("active");
    } catch {
      /* 忽略 */
    } finally {
      setBusyId("");
    }
  }

  async function removeTask(id: string) {
    setBusyId(id);
    try {
      await apiClient.del(`/tasks/${id}`);
      setItems((prev) => prev.filter((w) => w.id !== id));
    } catch {
      /* 忽略 */
    } finally {
      setBusyId("");
    }
  }

  const typeChips = [
    { v: "", label: "全部" },
    ...Object.entries(TYPE_LABELS).map(([v, label]) => ({ v, label })),
  ];

  return (
    <div className="p-4 md:p-6">
      {shareTip && (
        <div className="mb-2">
          <span
            className={`text-xs ${shareTip.startsWith("✓") ? "text-emerald-500" : "text-destructive"}`}
          >
            {shareTip}
          </span>
        </div>
      )}
      {/* 筛选行 */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5">
          {typeChips.map((c) => (
            <button
              key={c.v || "all"}
              onClick={() => setTypeFilter(c.v)}
              className={`rounded-full px-3 py-1 text-xs transition-colors ${
                typeFilter === c.v
                  ? "bg-primary text-primary-text"
                  : "bg-muted text-muted-foreground hover:bg-primary/15"
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
        <span className="mx-1 h-4 w-px bg-border" aria-hidden />
        <div className="flex flex-wrap gap-1.5">
          {STATUS_CHIPS.map((c) => (
            <button
              key={c.v}
              onClick={() => setStatusFilter(c.v)}
              className={`rounded-full px-3 py-1 text-xs transition-colors ${
                statusFilter === c.v
                  ? "border border-primary bg-primary/15 text-primary-text"
                  : "border border-border text-muted-foreground hover:border-primary"
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
        <button
          onClick={() => void load()}
          className="ml-auto flex items-center gap-1 rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:border-primary"
          title="刷新"
        >
          <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} aria-hidden />
          刷新
        </button>
      </div>

      {hasActive && (
        <p className="mb-3 flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-primary-text">
          <Clock3 className="h-3.5 w-3.5 animate-pulse" aria-hidden />
          有任务进行中，每 5 秒自动刷新…
        </p>
      )}
      {error && (
        <p className="mb-3 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </p>
      )}

      {loading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div
              key={i}
              className="h-52 animate-pulse rounded-[var(--radius-card)] border border-border bg-muted/30"
            />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="py-16 text-center">
          <Sparkles className="mx-auto mb-3 h-8 w-8 text-muted-foreground/50" aria-hidden />
          <p className="text-sm text-muted-foreground">
            这里还没有作品。去{" "}
            <button onClick={() => navigate("/studio")} className="text-primary-text underline">
              创作 Studio
            </button>{" "}
            派一单，成品会自动汇聚到这里
          </p>
        </div>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {items.map((w) => (
              <WorkCard
                key={w.id}
                work={w}
                busy={busyId === w.id}
                sharing={sharingId === w.id}
                onCancel={() => void cancelTask(w.id)}
                onRetry={() => void retryTask(w.id)}
                onDelete={() => void removeTask(w.id)}
                onOpen={() => setDetail(w)}
                onShare={() => void shareToCommunity(w)}
              />
            ))}
          </div>
          {items.length >= limit && (
            <div className="mt-4 text-center">
              <button
                onClick={() => setLimit((l) => l + PAGE_STEP)}
                className="rounded-full border border-border px-4 py-1.5 text-xs text-muted-foreground hover:border-primary hover:text-primary-text"
              >
                加载更多（已显示 {items.length} 条）
              </button>
            </div>
          )}
        </>
      )}

      {/* 详情弹窗 */}
      <Dialog
        open={detail !== null}
        onClose={() => setDetail(null)}
        title={
          detail
            ? `${TYPE_LABELS[detail.task_type] ?? detail.task_type} · ${detail.title?.trim() || detail.prompt?.slice(0, 24) || detail.id.slice(0, 8)}`
            : ""
        }
      >
        {detail && <WorkDetail work={detail} onRehydrate={() => navigate(`/studio?rehydrate=${detail.id}`)} />}
      </Dialog>
    </div>
  );
}

/* 单卡 */
function WorkCard({
  work,
  busy,
  sharing,
  onOpen,
  onCancel,
  onRetry,
  onDelete,
  onShare,
}: {
  work: WorkPreview;
  busy: boolean;
  sharing: boolean;
  onOpen: () => void;
  onCancel: () => void;
  onRetry: () => void;
  onDelete: () => void;
  onShare: () => void;
}) {
  const Icon = TYPE_ICONS[work.task_type] ?? ImageIcon;
  const active = ACTIVE_STATUSES.has(work.status);

  return (
    <div
      className={`group relative overflow-hidden rounded-[var(--radius-card)] border bg-surface transition-shadow hover:shadow-md ${
        work.status === "failed" ? "border-destructive/40" : "border-border"
      }`}
    >
      {/* 视觉区 */}
      <button
        onClick={onOpen}
        className="block h-44 w-full cursor-pointer overflow-hidden bg-muted/30 text-left"
        title="查看详情"
      >
        {active ? (
          <div className="flex h-full flex-col items-center justify-center gap-2">
            <Icon className="h-7 w-7 animate-pulse text-primary-text/70" aria-hidden />
            <span className="text-xs text-muted-foreground">
              {work.status === "queued" ? "排队中…" : "生成中…"}
            </span>
            {typeof work.progress === "number" && (
              <div className="h-1.5 w-28 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${Math.min(100, Math.max(4, work.progress))}%` }}
                />
              </div>
            )}
          </div>
        ) : work.task_type === "image" || work.task_type === "comic" ? (
          (work.asset_url || work.cover_url) && work.status === "succeeded" ? (
            <img
              src={(work.asset_url || work.cover_url) as string}
              alt={work.title ?? ""}
              loading="lazy"
              className="h-full w-full object-cover transition-transform group-hover:scale-[1.03]"
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-1.5">
              <Icon className="h-7 w-7 text-muted-foreground/60" aria-hidden />
              <span className="text-[11px] text-muted-foreground">媒体已过期</span>
            </div>
          )
        ) : work.task_type === "video" && work.asset_url && work.status === "succeeded" ? (
          <video src={work.asset_url} className="h-full w-full object-cover" muted preload="metadata" />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-1.5">
            <Icon
              className={`h-7 w-7 ${
                work.status === "failed" ? "text-destructive/60" : "text-primary-text/70"
              }`}
              aria-hidden
            />
            <span className="text-xs text-muted-foreground">
              {TYPE_LABELS[work.task_type] ?? work.task_type}作品
            </span>
          </div>
        )}
      </button>

      {/* 信息条 */}
      <div className="flex items-center gap-1.5 px-2.5 py-2">
        <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary-text">
          {TYPE_LABELS[work.task_type] ?? work.task_type}
        </span>
        {work.panel_count != null && work.panel_count > 0 && (
          <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
            {work.panel_count} 格
          </span>
        )}
        <span
          className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${
            work.status === "succeeded"
              ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              : work.status === "failed"
                ? "bg-destructive/10 text-destructive"
                : "bg-amber-500/10 text-amber-600 dark:text-amber-400"
          }`}
        >
          {work.status === "succeeded"
            ? "成功"
            : work.status === "failed"
              ? "失败"
              : active
                ? "进行中"
                : work.status}
        </span>
        <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
          {fmtTime(work.created_at)}
        </span>
      </div>

      {/* 操作条 */}
      <div className="flex items-center gap-2 border-t border-border px-2.5 py-1.5">
        {work.status === "succeeded" && (
          <button
            onClick={onOpen}
            className="text-[11px] text-primary-text hover:underline"
            title="查看大图与完整 Prompt"
          >
            详情
          </button>
        )}
        {["image", "comic", "video", "audio", "music"].includes(work.task_type) &&
          work.status === "succeeded" && (
            <button
              onClick={onOpen}
              className="hidden text-[11px] text-primary-text group-hover:inline hover:underline"
              title="带参数回 Studio 再创作"
            >
              ✨ 再创作
            </button>
          )}
        {work.status === "succeeded" && (work.asset_url || work.cover_url) && (
          <button
            disabled={sharing}
            onClick={() => void onShare()}
            className="hidden text-[11px] text-primary-text group-hover:inline hover:underline disabled:opacity-50"
            title="发布到社区分享墙"
          >
            {sharing ? "分享中…" : "🌍 分享"}
          </button>
        )}
        {active && (
          <button
            disabled={busy}
            onClick={onCancel}
            className="flex items-center gap-0.5 text-[11px] text-muted-foreground hover:text-destructive disabled:opacity-50"
          >
            <XCircle className="h-3 w-3" aria-hidden /> 取消
          </button>
        )}
        {(work.status === "failed" || work.status === "cancelled" || work.status === "expired") && (
          <>
            <button
              disabled={busy}
              onClick={onRetry}
              className="flex items-center gap-0.5 text-[11px] text-primary-text hover:underline disabled:opacity-50"
            >
              <RefreshCw className={`h-3 w-3 ${busy ? "animate-spin" : ""}`} aria-hidden /> 重试
            </button>
            <button
              disabled={busy}
              onClick={onDelete}
              className="ml-auto text-[11px] text-muted-foreground hover:text-destructive disabled:opacity-50"
            >
              删除
            </button>
          </>
        )}
        {work.status === "succeeded" && (
          <span className="ml-auto text-[10px] text-muted-foreground opacity-0 group-hover:opacity-100">
            {work.model?.slice(0, 18)}
          </span>
        )}
      </div>
    </div>
  );
}

/* 详情弹窗内容 */
function WorkDetail({ work, onRehydrate }: { work: WorkPreview; onRehydrate: () => void }) {
  return (
    <div className="flex max-h-[72vh] flex-col gap-3 overflow-y-auto text-sm">
      {/* 大图 / 播放器 */}
      {work.status === "succeeded" &&
        (work.task_type === "image" || work.task_type === "comic") &&
        (work.asset_url || work.cover_url) && (
          <img
            src={(work.asset_url || work.cover_url) as string}
            alt={work.title ?? ""}
            className="max-h-[46vh] w-full rounded-lg object-contain"
          />
        )}
      {work.status === "succeeded" && work.task_type === "video" && work.asset_url && (
        <video src={work.asset_url} controls className="max-h-[46vh] w-full rounded-lg" />
      )}
      {work.status === "succeeded" &&
        (work.task_type === "audio" || work.task_type === "music") && (
          <div className="flex flex-col items-center gap-3 rounded-lg bg-muted/30 p-5">
            <Music className="h-8 w-8 text-primary-text/70" aria-hidden />
            {work.asset_url ? (
              <audio src={work.asset_url} controls className="w-full" />
            ) : (
              <span className="text-xs text-muted-foreground">音频链接已过期</span>
            )}
          </div>
        )}
      {!ACTIVE_STATUSES.has(work.status) && work.status !== "succeeded" && (
        <p className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive">
          该任务{work.status === "failed" ? "生成失败" : `状态为 ${work.status}`}，可在作品库卡片上重试或删除
        </p>
      )}
      {/* 元信息 */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="rounded bg-primary/10 px-2 py-0.5 text-primary-text">
          {TYPE_LABELS[work.task_type] ?? work.task_type}
        </span>
        {work.model && <span className="rounded bg-muted px-2 py-0.5">{work.model}</span>}
        {typeof work.progress === "number" && (
          <span className="rounded bg-muted px-2 py-0.5">{Math.round(work.progress)}%</span>
        )}
        {work.created_at && <span>{new Date(work.created_at).toLocaleString("zh-CN")}</span>}
        <span className="font-mono text-[10px] opacity-60">{work.id.slice(0, 8)}</span>
      </div>
      {/* Prompt 全文 */}
      {work.prompt && (
        <div>
          <p className="mb-1 text-xs font-semibold text-foreground">Prompt</p>
          <pre className="whitespace-pre-wrap rounded-lg bg-muted/40 p-3 text-xs leading-relaxed">
            {work.prompt}
          </pre>
        </div>
      )}
      {/* 动作 */}
      <div className="mt-auto flex flex-wrap gap-2 border-t border-border pt-3">
        {work.status === "succeeded" &&
          ["image", "comic", "video", "audio", "music"].includes(work.task_type) && (
            <button
              onClick={onRehydrate}
              className="flex items-center gap-1 rounded-full bg-primary px-3 py-1.5 text-xs text-primary-text hover:opacity-90"
            >
              <Wand2 className="h-3.5 w-3.5" aria-hidden /> ✨ 在 Studio 再创作
            </button>
          )}
        <button
          onClick={() => {
            if (work.prompt) void copyText(work.prompt);
          }}
          className="rounded-full border border-border px-3 py-1.5 text-xs hover:border-primary"
        >
          📋 复制 Prompt
        </button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Tab 2 · 音乐作品（圆桌/写歌定稿，原功能保留）                          */
/* ------------------------------------------------------------------ */

function MusicTab() {
  const navigate = useNavigate();
  const [rooms, setRooms] = useState<ChatSession[]>([]);
  const [works, setWorks] = useState<StoryProjectItem[]>([]);
  const [chars, setChars] = useState<CharacterItem[]>([]);
  const [musicWorks, setMusicWorks] = useState<MusicWorkItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [workQuery, setWorkQuery] = useState("");
  const [activeTag, setActiveTag] = useState("");
  const [publishFor, setPublishFor] = useState("");
  const [detailWork, setDetailWork] = useState<MusicWorkItem | null>(null);

  const loadMusicWorks = useCallback(async (q = "", tag = "") => {
    try {
      const res = await apiClient.get<{ items: MusicWorkItem[] }>(
        `/generations/music/works?q=${encodeURIComponent(q)}&tag=${encodeURIComponent(tag)}`,
      );
      setMusicWorks(res.items);
    } catch {
      /* 忽略 */
    }
  }, []);

  const allTags = Array.from(
    new Set(
      musicWorks
        .flatMap((w) => (w.tags || "").split(",").map((t) => t.trim()))
        .filter(Boolean),
    ),
  ).slice(0, 12);

  const toggleTag = (tag: string) => {
    const next = activeTag === tag ? "" : tag;
    setActiveTag(next);
    void loadMusicWorks(workQuery, next);
  };

  useEffect(() => {
    void (async () => {
      try {
        const [r1, r2, r3, r4] = await Promise.all([
          apiClient.get<{ items: ChatSession[] }>("/roleplay/chats"),
          apiClient.get<{ items: StoryProjectItem[] }>("/story/projects"),
          apiClient.get<{ items: CharacterItem[] }>("/roleplay/characters"),
          apiClient.get<{ items: MusicWorkItem[] }>("/generations/music/works"),
        ]);
        setRooms(r1.items.filter((c) => c.is_room));
        setWorks(r2.items);
        setChars(r3.items);
        setMusicWorks(r4.items);
      } catch {
        /* 加载失败保持空态 */
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const playWorks = works.filter((w) => w.genre === "群演剧本");
  const compareWorks = musicWorks.filter((w) => compareIds.includes(w.id));
  const workVersions = new Map<string, number>();
  for (const w of musicWorks) {
    const key = w.theme || w.title;
    workVersions.set(key, (workVersions.get(key) ?? 0) + 1);
  }
  const workVersionOf = (w: MusicWorkItem): number => {
    const key = w.theme || w.title;
    return workVersions.get(key) ?? 1;
  };

  async function deleteMusicWork(id: string) {
    try {
      await apiClient.del(`/generations/music/works/${id}`);
      setMusicWorks((prev) => prev.filter((w) => w.id !== id));
      setCompareIds((prev) => prev.filter((x) => x !== id));
    } catch {
      /* 忽略 */
    }
  }

  async function publishToChat(workId: string, chatId: string) {
    try {
      const res = await apiClient.post<{ ok: boolean; title: string }>(
        `/generations/music/works/${workId}/to-chat`,
        { chat_id: chatId },
      );
      alert(`《${res.title}》已发布到群聊`);
      setPublishFor("");
    } catch (e) {
      alert(e instanceof Error ? e.message : "发布失败");
    }
  }

  return (
    <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-2">
      {/* 音乐作品 */}
      <section className="rounded-[var(--radius-card)] border border-border bg-surface p-4 lg:col-span-2">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Music className="h-4 w-4 text-primary-text" aria-hidden />
            音乐作品（{musicWorks.length}）——圆桌/写歌定稿自动存入
          </h2>
          <input
            value={workQuery}
            onChange={(e) => {
              setWorkQuery(e.target.value);
              void loadMusicWorks(e.target.value, activeTag);
            }}
            placeholder="搜索歌名/主题/风格…"
            className="ml-auto h-8 w-48 rounded-lg border border-input bg-surface px-3 text-xs outline-none focus:border-primary"
            aria-label="搜索音乐作品"
          />
        </div>
        {allTags.length > 0 && (
          <div className="mb-3 flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-muted-foreground">🏷 按标签浏览：</span>
            {allTags.map((t) => (
              <button
                key={t}
                onClick={() => toggleTag(t)}
                className={`rounded-full px-2.5 py-0.5 text-[11px] transition-colors ${
                  activeTag === t
                    ? "bg-primary text-primary-text"
                    : "bg-muted text-muted-foreground hover:bg-primary/15"
                }`}
              >
                {t}
              </button>
            ))}
            {activeTag && (
              <button
                onClick={() => toggleTag(activeTag)}
                className="text-[11px] text-destructive hover:underline"
              >
                ✕ 清除筛选
              </button>
            )}
          </div>
        )}
        {loading ? (
          <p className="py-6 text-center text-sm text-muted-foreground">加载中…</p>
        ) : musicWorks.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            还没有作品。去「音乐创作助手」开一场圆桌，定稿会自动存到这里
          </p>
        ) : (
          <>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {musicWorks.slice(0, 9).map((w) => (
                <div
                  key={w.id}
                  className="flex flex-col gap-1.5 rounded-lg border border-border p-3"
                >
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      className="truncate font-medium hover:text-primary-text"
                      onClick={() => setDetailWork(w)}
                      title="查看详情"
                    >
                      {w.title}
                    </button>
                    {w.style && (
                      <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary-text">
                        {w.style}
                      </span>
                    )}
                    {workVersionOf(w) > 1 && (
                      <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        第 {workVersionOf(w)} 稿
                      </span>
                    )}
                  </div>
                  {w.tags && (
                    <div className="flex flex-wrap gap-1">
                      {w.tags
                        .split(",")
                        .map((t) => t.trim())
                        .filter(Boolean)
                        .slice(0, 4)
                        .map((t) => (
                          <span
                            key={t}
                            className="rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground"
                          >
                            {t}
                          </span>
                        ))}
                    </div>
                  )}
                  <label className="flex shrink-0 items-center justify-end gap-1 text-[11px] text-muted-foreground">
                    <input
                      type="checkbox"
                      checked={compareIds.includes(w.id)}
                      onChange={(e) => {
                        const checked = e.target.checked;
                        setCompareIds((prev) => {
                          if (!checked) return prev.filter((x) => x !== w.id);
                          if (prev.length >= 2) {
                            const keep = (prev[1] ?? prev[0]) ?? "";
                            return [keep, w.id];
                          }
                          return [...prev, w.id];
                        });
                      }}
                      className="h-3 w-3 accent-[var(--primary)]"
                    />
                    对比
                  </label>
                  <p className="line-clamp-3 whitespace-pre-wrap text-[11px] leading-relaxed text-muted-foreground">
                    {w.lyrics.slice(0, 120)}
                    {w.lyrics.length > 120 ? "…" : ""}
                  </p>
                  <div className="mt-auto flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                    <span>{fmtTime(w.created_at)}</span>
                    <span className="rounded bg-muted px-1.5 py-0.5">
                      {w.source === "roundtable" ? "圆桌" : w.source}
                    </span>
                    <button
                      onClick={() => void copyShareUrl("music", w.id)}
                      className="text-primary-text hover:underline"
                    >
                      分享
                    </button>
                    <button
                      onClick={() => setPublishFor(publishFor === w.id ? "" : w.id)}
                      className="text-primary-text hover:underline"
                    >
                      发布到群
                    </button>
                    <button
                      onClick={() => void deleteMusicWork(w.id)}
                      className="ml-auto text-danger hover:underline"
                    >
                      删除
                    </button>
                  </div>
                  {publishFor === w.id && (
                    <div className="mt-1 flex flex-wrap gap-1.5 border-t border-border pt-1.5">
                      {rooms.length === 0 ? (
                        <span className="text-[11px] text-muted-foreground">
                          还没有群，先去 AI 导演工作室建群
                        </span>
                      ) : (
                        rooms.slice(0, 4).map((r) => (
                          <button
                            key={r.id}
                            onClick={() => void publishToChat(w.id, r.id)}
                            className="rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] hover:border-primary"
                          >
                            📢 {r.title}
                          </button>
                        ))
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>

            {compareWorks.length === 2 && (
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                {compareWorks.map((w, i) => (
                  <div
                    key={w.id}
                    className="rounded-lg border border-primary/30 bg-muted/20 p-3"
                  >
                    <p className="mb-1.5 text-sm font-semibold">
                      第 {i + 1} 首 ·《{w.title}》
                      {w.style && (
                        <span className="ml-2 rounded bg-primary/10 px-1.5 py-0.5 text-[10px]">
                          {w.style}
                        </span>
                      )}
                    </p>
                    <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs leading-relaxed">
                      {w.lyrics}
                    </pre>
                    {w.arrangement && (
                      <p className="mt-1.5 text-[11px] text-muted-foreground">
                        🎧 {w.arrangement.slice(0, 100)}…
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}
            {musicWorks.length > 9 && (
              <p className="mt-2 text-[11px] text-muted-foreground">
                共 {musicWorks.length} 首，仅显示最近 9 首
              </p>
            )}
          </>
        )}
        <button
          onClick={() => navigate("/create/music")}
          className="mt-3 text-xs text-primary-text hover:underline"
        >
          去创作新歌（音乐创作助手）→
        </button>
      </section>

      {/* 群演作品 */}
      <section className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <BookOpen className="h-4 w-4 text-primary-text" aria-hidden />
          群演作品（{playWorks.length}）
          <button
            onClick={() => navigate("/story")}
            className="ml-auto text-xs text-primary-text hover:underline"
            title="全部创作项目（含非群演剧本）"
          >
            查看全部项目 →
          </button>
        </h2>
        {loading ? (
          <p className="py-6 text-center text-sm text-muted-foreground">加载中…</p>
        ) : playWorks.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            还没有作品。群聊里演完后，点「群信息 → 存入创作工作室」即可存档
          </p>
        ) : (
          <ul className="space-y-2">
            {playWorks.slice(0, 6).map((w) => (
              <li key={w.id}>
                <button
                  onClick={() => navigate(`/story/${w.id}`)}
                  className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2 text-left transition-colors hover:border-primary"
                >
                  <span className="truncate font-medium">{w.title}</span>
                  <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">
                    {fmtTime(w.updated_at)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {works.length > playWorks.length && (
          <button
            onClick={() => navigate("/story")}
            className="mt-3 text-xs text-primary-text hover:underline"
          >
            查看全部创作工作室项目（{works.length}）→
          </button>
        )}
      </section>

      {/* 创作群 */}
      <section className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <MessageCircle className="h-4 w-4 text-primary-text" aria-hidden />
          我的创作群（{rooms.length}）
        </h2>
        {loading ? (
          <p className="py-6 text-center text-sm text-muted-foreground">加载中…</p>
        ) : rooms.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            还没有群。去「AI 导演工作室」给个主题，一键建组开演
          </p>
        ) : (
          <ul className="space-y-2">
            {rooms.slice(0, 6).map((r) => (
              <li key={r.id}>
                <button
                  onClick={() => navigate(`/roleplay?chat=${r.id}`)}
                  className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2 text-left transition-colors hover:border-primary"
                >
                  <span className="truncate font-medium">{r.title}</span>
                  <span className="ml-auto shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    {r.message_count} 条演出
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <button
          onClick={() => navigate("/create/studio")}
          className="mt-3 text-xs text-primary-text hover:underline"
        >
          新建创作群（AI 导演工作室）→
        </button>
      </section>

      {/* 角色演员池 */}
      <section className="rounded-[var(--radius-card)] border border-border bg-surface p-4 lg:col-span-2">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <Users className="h-4 w-4 text-primary-text" aria-hidden />
          角色演员池（{chars.length}）——选角时自动检索复用，越用越厚
        </h2>
        {loading ? (
          <p className="py-6 text-center text-sm text-muted-foreground">加载中…</p>
        ) : chars.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            还没有角色卡。AI 导演建组时会自动创建并沉淀到这里
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {chars.slice(0, 24).map((c) => (
              <button
                key={c.asset_id}
                onClick={() => navigate("/roleplay")}
                className="rounded-full border border-border bg-muted/40 px-3 py-1 text-xs transition-colors hover:border-primary"
                title="点击前往角色扮演"
              >
                {c.name || c.filename}
              </button>
            ))}
            {chars.length > 24 && (
              <span className="px-2 py-1 text-xs text-muted-foreground">
                +{chars.length - 24} 位…
              </span>
            )}
          </div>
        )}
        <button
          onClick={() => navigate("/roleplay")}
          className="mt-3 flex items-center gap-1 text-xs text-primary-text hover:underline"
        >
          前往角色扮演管理角色卡 →
        </button>
      </section>

      {/* 音乐作品详情弹窗 */}
      <Dialog
        open={detailWork !== null}
        onClose={() => setDetailWork(null)}
        title={detailWork ? `《${detailWork.title}》` : ""}
      >
        {detailWork && (
          <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto text-sm">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {detailWork.style && (
                <span className="rounded bg-primary/10 px-2 py-0.5 text-primary-text">
                  {detailWork.style}
                </span>
              )}
              {detailWork.tags &&
                detailWork.tags
                  .split(",")
                  .filter(Boolean)
                  .slice(0, 4)
                  .map((t) => (
                    <span
                      key={t}
                      className="rounded bg-muted px-2 py-0.5 text-muted-foreground"
                    >
                      {t}
                    </span>
                  ))}
              <span className="text-muted-foreground">
                {detailWork.created_at
                  ? new Date(detailWork.created_at).toLocaleString("zh-CN")
                  : ""}
              </span>
              <span className="rounded bg-muted px-2 py-0.5 text-muted-foreground">
                {detailWork.source === "roundtable" ? "圆桌" : detailWork.source}
              </span>
            </div>
            {detailWork.theme && (
              <p className="text-xs text-muted-foreground">主题：{detailWork.theme}</p>
            )}
            <div>
              <p className="mb-1 text-xs font-semibold text-foreground">🎤 歌词</p>
              <pre className="whitespace-pre-wrap rounded-lg bg-muted/40 p-3 text-xs leading-relaxed">
                {detailWork.lyrics}
              </pre>
            </div>
            {detailWork.chords && (
              <div>
                <p className="mb-1 text-xs font-semibold text-foreground">🎸 和弦谱</p>
                <pre className="whitespace-pre-wrap rounded-lg bg-muted/40 p-3 font-mono text-xs leading-relaxed">
                  {detailWork.chords}
                </pre>
              </div>
            )}
            {detailWork.arrangement && (
              <div>
                <p className="mb-1 text-xs font-semibold text-foreground">🎧 编曲思路</p>
                <p className="rounded-lg bg-muted/40 p-3 text-xs leading-relaxed">
                  {detailWork.arrangement}
                </p>
              </div>
            )}
            {detailWork.style_en && (
              <p className="text-xs text-muted-foreground">
                🎼 Suno 风格：{detailWork.style_en}
              </p>
            )}
            <div className="flex flex-wrap gap-2 border-t border-border pt-3">
              <button
                onClick={() => void copyShareUrl("music", detailWork.id)}
                className="rounded-full border border-border px-3 py-1 text-xs hover:border-primary"
              >
                🔗 复制分享链接
              </button>
              {rooms.length > 0 && (
                <select
                  value=""
                  onChange={(e) => {
                    if (e.target.value) {
                      void publishToChat(detailWork.id, e.target.value);
                    }
                  }}
                  className="rounded-full border border-border px-3 py-1 text-xs"
                >
                  <option value="">发布到创作群…</option>
                  {rooms.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.title || r.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              )}
              <button
                onClick={() => {
                  if (window.confirm(`确认删除「${detailWork.title}」？`)) {
                    void deleteMusicWork(detailWork.id);
                    setDetailWork(null);
                  }
                }}
                className="rounded-full border border-border px-3 py-1 text-xs text-danger hover:border-danger"
              >
                🗑 删除
              </button>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
