import { useState, type CSSProperties } from "react";

import { useQuery } from "@tanstack/react-query";
import {
  AudioLines,
  Camera,
  Clapperboard,
  Image as ImageIcon,
  Sparkles,
  Type as TypeIcon,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import type {
  DashboardStats, GenerationTask, Paginated, Prompt } from "@aigc/shared-types";

interface InspectionReport {
  ts?: string;
  sections?: {
    data?: { agent_projects?: number; agent_articles?: number; tasks_total?: number };
    tasks_24h?: Record<string, number>;
    upstream?: Record<string, unknown>;
    grok?: string;
    asmr?: { total?: number; updated_24h?: number; last_sync_at?: string | null; healthy?: boolean };
    serial_project_alerts?: Array<{ title?: string; days_since_update?: number; note?: string }>;
  };
}

import { Card } from "@/components/ui/Card";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/stores/auth";

type CreateType = "image" | "text" | "video" | "audio";

const TYPES: { v: CreateType; label: string }[] = [
  { v: "image", label: "图片" },
  { v: "text", label: "文本" },
  { v: "video", label: "视频" },
  { v: "audio", label: "语音" },
];

const ROUTE: Record<CreateType, string> = {
  image: "/create/image",
  text: "/create/text",
  video: "/create/video",
  audio: "/create/audio",
};

const TOOLS = [
  { icon: TypeIcon, label: "文本生成", to: "/create/text" },
  { icon: ImageIcon, label: "图片生成", to: "/create/image" },
  { icon: Clapperboard, label: "视频生成", to: "/create/video" },
  { icon: AudioLines, label: "语音生成", to: "/create/audio" },
  { icon: Sparkles, label: "提示词生成", to: "/create/prompt" },
  { icon: Camera, label: "写真摄影", to: "/photography" },
];

const TYPE_LABEL: Record<string, string> = {
  text: "文本",
  image: "图片",
  video: "视频",
  audio: "语音",
};


export function DashboardPage() {
  const navigate = useNavigate();
  const [idea, setIdea] = useState("");
  const [type, setType] = useState<CreateType>("image");
  // 巡检接口仅 admin 可访问（安全加固）；普通用户不查询，避免 403 控制台噪音
  const isAdmin = useAuthStore((s) => s.user?.role === "admin");

  const featured = useQuery({
    queryKey: ["dashboard", "featured"],
    queryFn: () => apiClient.get<Paginated<Prompt>>("/prompts/?page=1&page_size=6"),
    staleTime: 5 * 60_000,
  });

  const stats = useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: () => apiClient.get<DashboardStats>("/dashboard/stats"),
    staleTime: 30_000,
  });

  const recentTasks = useQuery({
    queryKey: ["dashboard", "recent-tasks"],
    queryFn: () => apiClient.get<Paginated<GenerationTask>>("/tasks/?page=1&page_size=5"),
    staleTime: 15_000,
  });

  const inspection = useQuery({
    queryKey: ["dashboard", "inspection"],
    queryFn: () =>
      apiClient.get<{ report: InspectionReport | null; created_at?: string }>(
        "/dashboard/inspections/latest",
      ),
    staleTime: 60_000,
    enabled: isAdmin,
  });

  function generate() {
    navigate(ROUTE[type], { state: { prompt: idea } });
  }

  // 任一数据查询失败时给出统一提示 + 重试（不再静默吞错）
  const queryError = featured.isError || stats.isError || recentTasks.isError;
  function refetchAll() {
    void featured.refetch();
    void stats.refetch();
    void recentTasks.refetch();
  }

  const s = stats.data?.data;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 md:px-6 md:py-8">
      {queryError && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning">
          <span>部分数据加载失败</span>
          <button
            type="button"
            onClick={refetchAll}
            className="rounded-lg border border-warning/40 px-2.5 py-1 text-xs font-medium hover:bg-warning/10"
          >
            重试
          </button>
        </div>
      )}
      <Card className="animate-enter p-6 sm:p-7">
        <h1 className="font-display text-2xl font-bold tracking-tight sm:text-[28px]">你想创作什么？</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          输入一句话，或从下方灵感开始。无需任何模型 Key 也能完整体验。
        </p>
        <div className="mt-5 rounded-2xl border border-border-strong bg-background p-3.5">
          <textarea
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            rows={2}
            placeholder="例如：星空下的一只猫，写实电影感光影，暖色调…"
            className="w-full resize-none border-0 bg-transparent text-[15px] text-foreground placeholder:text-muted-foreground focus:outline-none"
            style={{ minHeight: 46 }}
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <div className="inline-flex gap-1 rounded-xl border border-border-strong bg-surface p-1">
              {TYPES.map((t) => (
                <button
                  key={t.v}
                  onClick={() => setType(t.v)}
                  className={cn(
                    "rounded-lg px-3 py-1.5 text-sm transition-colors",
                    type === t.v
                      ? "bg-primary/12 font-semibold text-primary-text"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <button
              onClick={generate}
              className="ml-auto inline-flex items-center gap-1.5 rounded-xl bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-[0_6px_16px_-8px_rgba(232,145,42,0.7)] transition-all duration-200 hover:-translate-y-px hover:bg-primary-hover hover:shadow-[0_10px_24px_-8px_rgba(232,145,42,0.8)] active:scale-[0.98]"
            >
              <Sparkles className="h-4 w-4" aria-hidden />
              开始创作
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2.5">
          {TOOLS.map((t) => (
            <button
              key={t.to}
              onClick={() => navigate(t.to)}
              className="inline-flex items-center gap-2.5 rounded-xl border border-border bg-surface px-3.5 py-2.5 text-sm font-medium transition-all duration-200 hover:-translate-y-px hover:border-primary hover:shadow-soft active:scale-[0.98]"
            >
              <span className="grid h-7 w-7 place-items-center rounded-lg bg-primary/12 text-primary-text">
                <t.icon className="h-4 w-4" aria-hidden />
              </span>
              {t.label}
            </button>
          ))}
        </div>
      </Card>

      {inspection.data?.report && (
        <section className="animate-enter mt-6" style={{ "--stagger": "80ms" } as CSSProperties}>
          <Card className="p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">系统巡检</h2>
              <span className="text-xs text-muted-foreground">
                {inspection.data.created_at
                  ? new Date(inspection.data.created_at).toLocaleString("zh-CN")
                  : ""}
              </span>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                {
                  label: "AgentList 项目",
                  value: inspection.data.report.sections?.data?.agent_projects ?? "-",
                },
                {
                  label: "AgentList 文章",
                  value: inspection.data.report.sections?.data?.agent_articles ?? "-",
                },
                { label: "Grok", value: inspection.data.report.sections?.grok ?? "-" },
                {
                  label: "注册机",
                  value:
                    typeof inspection.data.report.sections?.upstream?.register === "object"
                      ? "running"
                      : String(inspection.data.report.sections?.upstream?.register ?? "-"),
                },
                {
                  label: "ASMR 库",
                  value: inspection.data.report.sections?.asmr?.total ?? "-",
                },
                {
                  label: "ASMR 24h 更新",
                  value: inspection.data.report.sections?.asmr?.updated_24h ?? "-",
                },
                {
                  label: "连载停滞",
                  value: (() => {
                    const alerts =
                      inspection.data.report.sections?.serial_project_alerts;
                    const n = Array.isArray(alerts) ? alerts.length : 0;
                    return n > 0
                      ? `${n} 个待关注`
                      : "正常";
                  })(),
                  warn:
                    (Array.isArray(
                      inspection.data.report.sections?.serial_project_alerts,
                    )
                      ? inspection.data.report.sections.serial_project_alerts.length
                      : 0) > 0,
                },
              ].map((item) => (
                <div
                  key={item.label}
                  className={`rounded-lg p-3 ${
                    "warn" in item && item.warn
                      ? "bg-destructive/10 ring-1 ring-destructive/40"
                      : "bg-muted/40"
                  }`}
                >
                  <p className="text-xs text-muted-foreground">{item.label}</p>
                  <p className="mt-0.5 truncate font-display text-lg font-semibold tabular-nums">
                    {item.value}
                  </p>
                </div>
              ))}
            </div>
          </Card>
        </section>
      )}

      {s && (
        <>
          <section
            className="animate-enter mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4"
            style={{ "--stagger": "140ms" } as CSSProperties}
          >
            {[
              { label: "总任务", value: s.total_tasks },
              { label: "成功", value: s.succeeded },
              { label: "失败", value: s.failed },
              { label: "图片任务", value: s.image_count },
            ].map((item) => (
              <Card key={item.label} hoverable className="p-4">
                <p className="text-xs text-muted-foreground">{item.label}</p>
                <p className="mt-1 font-display text-[26px] font-semibold tabular-nums">{item.value}</p>
              </Card>
            ))}
          </section>

          {s.trend_7d && s.trend_7d.length > 0 && (
            <section
              className="animate-enter mt-6"
              style={{ "--stagger": "200ms" } as CSSProperties}
            >
              <Card className="p-4">
                <h2 className="text-[15px] font-semibold">近 7 天生成趋势</h2>
                <div className="mt-4 flex h-36 items-end gap-2 sm:gap-3">
                  {s.trend_7d.map((d, idx) => {
                    const max = Math.max(...s.trend_7d!.map((x) => x.count), 1);
                    const height = Math.max((d.count / max) * 100, d.count > 0 ? 8 : 2);
                    const label = d.date.slice(5).replace("-", "/");
                    return (
                      <div key={d.date} className="flex flex-1 flex-col items-center gap-1.5">
                        <span className="text-xs font-medium tabular-nums text-muted-foreground">
                          {d.count > 0 ? d.count : ""}
                        </span>
                        <div
                          className={cn(
                            "bar-grow w-full rounded-t-md transition-all",
                            d.count > 0
                              ? "bg-primary/70 hover:bg-primary"
                              : "bg-muted",
                          )}
                          style={
                            {
                              height: `${height}%`,
                              "--stagger": `${idx * 45}ms`,
                            } as CSSProperties
                          }
                          title={`${d.date}: ${d.count} 个任务`}
                        />
                        <span className="text-[11px] tabular-nums text-muted-foreground">
                          {label}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </Card>
            </section>
          )}
        </>
      )}

      <section
        className="animate-enter mt-8"
        style={{ "--stagger": "240ms" } as CSSProperties}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold">最近任务</h2>
          <button onClick={() => navigate("/tasks")} className="text-sm text-primary-text hover:underline">
            全部任务
          </button>
        </div>
        {(recentTasks.data?.items?.length ?? 0) === 0 ? (
          <p className="text-sm text-muted-foreground">还没有任务，先去创作一波。</p>
        ) : (
          <ul className="space-y-2">
            {(recentTasks.data?.items ?? []).map((t) => (
              <Card
                key={t.id}
                hoverable
                className="flex cursor-pointer items-center justify-between gap-3 p-3"
                onClick={() => navigate("/tasks")}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                      {TYPE_LABEL[t.task_type] ?? t.task_type}
                    </span>
                    <span className="truncate text-xs text-muted-foreground">{t.model}</span>
                  </div>
                  <p className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">{t.id}</p>
                </div>
                <StatusBadge status={t.status} />
              </Card>
            ))}
          </ul>
        )}
      </section>

      <section
        className="animate-enter mt-9"
        style={{ "--stagger": "280ms" } as CSSProperties}
      >
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold">精选灵感</h2>
          <button
            onClick={() => navigate("/prompts")}
            className="text-sm text-primary-text hover:underline"
          >
            查看全部
          </button>
        </div>
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-6">
          {(featured.data?.items ?? []).map((p) => (
            <button
              key={p.id}
              onClick={() =>
                navigate("/create/image", {
                  state: { prompt: p.content },
                })
              }
              title={p.title}
              className="group hover-lift relative aspect-square overflow-hidden rounded-2xl border border-border bg-muted"
            >
              {p.cover_url && (
                <img
                  src={p.cover_url}
                  alt={p.title}
                  loading="lazy"
                  className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-105"
                />
              )}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
