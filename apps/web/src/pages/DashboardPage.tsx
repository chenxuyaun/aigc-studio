import { useEffect, useRef, useState, type CSSProperties } from "react";

import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";

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
import { QUICK_TOOLS } from "@/shared/createTools";

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

const TOOLS = QUICK_TOOLS.map((t) => ({ icon: t.icon, label: t.title, to: t.to }));

const TYPE_LABEL: Record<string, string> = {
  text: "文本",
  image: "图片",
  video: "视频",
  audio: "语音",
};

// 近期新增功能速览（新功能入口地图：每个功能一句话 + 直达链接）
interface Scene {
  icon: string;
  title: string; // 场景名（用户语言）
  desc: string; // 什么时候用、怎么走
  to: string; // 主入口
  prompt?: string; // 预填目标模板（一个框驱动）
  links: { label: string; to: string }[]; // 关联子功能直达
}

// 场景化入口：按「想做什么」组织（一个目标框驱动——点场景预填目标模板）
const SCENES: Scene[] = [
  {
    icon: "🎵",
    title: "写一首歌",
    desc: "AI 写歌 → 1对1 打磨 → 圆桌共创，定稿自动入库",
    to: "/create/music",
    prompt: "写一首关于____的歌，贴合我平时的风格",
    links: [
      { label: "我的作品", to: "/works" },
      { label: "创作圆桌", to: "/create/music" },
    ],
  },
  {
    icon: "📖",
    title: "写一个故事",
    desc: "项目 + 罗盘 + 写法特征，章节生成/修订/连载",
    to: "/story",
    prompt: "写一个关于____的故事：先检索相关背景，再写一个章节",
    links: [
      { label: "创作罗盘", to: "/story" },
      { label: "写法特征", to: "/story" },
      { label: "角色卡", to: "/create/character-card" },
    ],
  },
  {
    icon: "🎭",
    title: "和角色聊天",
    desc: "角色扮演 + 记忆 + 状态账本，群聊共创",
    to: "/roleplay",
    prompt: "让角色____评价一下：____",
    links: [
      { label: "状态账本", to: "/roleplay" },
      { label: "SillyTavern", to: "/sillytavern" },
    ],
  },
  {
    icon: "🖼",
    title: "生成图片 / 视频",
    desc: "文生图 / 视频 / 漫画 / 写真，任务中心看进度",
    to: "/create",
    prompt: "生成一张____的图（画面描述要具体）",
    links: [
      { label: "提示词库", to: "/prompts" },
      { label: "素材库", to: "/assets" },
      { label: "任务中心", to: "/tasks" },
    ],
  },
  {
    icon: "📚",
    title: "积累素材",
    desc: "知识库导入 → AI 解读 → 创作自动参考；联网兜底",
    to: "/knowledge",
    prompt: "检索关于____的资料并整理要点",
    links: [
      { label: "待确认素材", to: "/knowledge" },
      { label: "ASMR 库", to: "/asmr" },
    ],
  },
  {
    icon: "🗂",
    title: "管理成果",
    desc: "音乐作品 / 群演作品 / 素材 / 任务，统一回看",
    to: "/works",
    links: [
      { label: "任务中心", to: "/tasks" },
      { label: "全站搜索", to: "/search" },
    ],
  },
];

// Mission 步骤类型元信息（时间线徽章）
const KIND_META: Record<string, { icon: string; label: string }> = {
  music: { icon: "🎵", label: "写歌" },
  text: { icon: "✍️", label: "文本" },
  image: { icon: "🖼", label: "图片" },
  video: { icon: "🎬", label: "视频" },
  comic: { icon: "📚", label: "漫画" },
  search: { icon: "🔍", label: "检索" },
  agent: { icon: "🤖", label: "Agent" },
  story: { icon: "📖", label: "故事" },
  asmr: { icon: "🎧", label: "ASMR" },
  character: { icon: "🎭", label: "角色" },
  memory: { icon: "📒", label: "记忆" },
  code: { icon: "💻", label: "代码" },
};

// SAIOS 执行循环（perceive → plan → execute → observe → reflect → learn）
const MISSION_LOOP = ["🎯 感知", "🗺 计划", "⚡ 执行", "👀 观察", "🪞 反思", "🌱 学习"];

// 媒体任务实时进度（时间线内嵌：轮询任务状态 → 徽章 + 产物缩略图）
const TASK_STATUS_META: Record<string, { icon: string; label: string }> = {
  queued: { icon: "⏳", label: "排队中" },
  submitting: { icon: "⏳", label: "提交中" },
  processing: { icon: "⚙️", label: "生成中" },
  succeeded: { icon: "✅", label: "完成" },
  failed: { icon: "❌", label: "失败" },
  cancelled: { icon: "🚫", label: "已取消" },
  expired: { icon: "⌛", label: "已过期" },
};

function TaskProgress({ taskId, kind }: { taskId: string; kind: string }) {
  const [task, setTask] = useState<GenerationTask | null>(null);
  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const t = await apiClient.get<GenerationTask>(`/tasks/${taskId}`);
        if (stop) return;
        setTask(t);
        if (["succeeded", "failed", "cancelled", "expired"].includes(t.status)) return;
      } catch {
        // 任务接口暂不可用：稍后重试
      }
      if (!stop) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => {
      stop = true;
      if (timer) clearTimeout(timer);
    };
  }, [taskId]);
  const meta = TASK_STATUS_META[task?.status ?? "queued"] ?? { icon: "⏳", label: "…" };
  const done = task?.status === "succeeded" && task.result;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
      <span className="rounded-full bg-muted px-2 py-0.5">
        {meta.icon} {meta.label}
        {task?.status === "processing" && task.progress > 0 ? ` ${task.progress}%` : ""}
      </span>
      {done &&
        (kind === "image" || kind === "comic" ? (
          <img
            src={task.result}
            alt="生成结果"
            className="h-20 w-20 rounded-lg border border-border object-cover"
          />
        ) : (
          <a
            href={task.result}
            target="_blank"
            rel="noreferrer"
            className="underline hover:text-primary-text"
          >
            ▶️ 查看产物
          </a>
        ))}
      {task?.status === "failed" && task.error_message && (
        <span className="truncate text-danger">{task.error_message.slice(0, 80)}</span>
      )}
    </div>
  );
}

export function DashboardPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [idea, setIdea] = useState("");
  const ideaRef = useRef<HTMLTextAreaElement | null>(null);

  // 跨页目标传递：AI 创作页「交给任务总控」→ /?goal=… → 自动填入并触发
  useEffect(() => {
    const goal = new URLSearchParams(location.search).get("goal");
    if (!goal) return;
    setIdea(goal);
    void runMission(goal);
    navigate(location.pathname, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search]);
  // 任务总控（Mission）：目标 → 自动拆解执行
  const [missionBusy, setMissionBusy] = useState(false);
  const [missionLessons, setMissionLessons] = useState<{ goal: string; lesson: string; created_at: string }[]>([]);
  const [missionRuns, setMissionRuns] = useState<
    {
      id: string;
      goal: string;
      plan: { step: number; kind: string; title: string }[];
      summary: string;
      parent_run_id?: string;
      created_at: string;
    }[]
  >([]);
  // 成长档案（平台对你的了解：偏好聚合 + LLM 画像）
  const [missionProfile, setMissionProfile] = useState<{
    preferences: { styles: string[]; themes: string[]; steps: string[]; agents: { id: string; name: string }[] };
    profile: string;
  } | null>(null);
  const [missionResult, setMissionResult] = useState<{
    run_id?: string;
    plan: { step: number; kind: string; title: string; agent?: string; reason?: string }[];
    results: {
      step: number;
      kind: string;
      title: string;
      summary: string;
      ok: boolean;
      agent?: string;
      task_id?: string;
      code?: { path: string; content: string }[];
    }[];
    summary: string;
  } | null>(null);
  // Mission 多轮对话：跑完可继续追问（链式迭代）
  const [continueMsg, setContinueMsg] = useState("");
  const [continueBusy, setContinueBusy] = useState(false);
  // 计划预览（Human-in-the-loop）：AI 拆解 → 人工确认/调整 → 执行
  const [planPreview, setPlanPreview] = useState<{
    goal: string;
    plan: {
      kind: string;
      prompt: string;
      title: string;
      input?: string;
      agent?: string;
      reason?: string;
    }[];
  } | null>(null);
  const [planBusy, setPlanBusy] = useState(false);

  async function runMission(goalArg?: string) {
    const goal = (goalArg ?? idea).trim();
    if (!goal || missionBusy) return;
    setMissionBusy(true);
    setMissionResult(null);
    setPlanPreview(null);
    try {
      // 第一步：只规划（预览确认）
      const p = await apiClient.post<{
        goal: string;
        plan: {
          kind: string;
          prompt: string;
          title: string;
          input?: string;
          agent?: string;
          reason?: string;
        }[];
      }>("/mission/plan", { goal });
      setPlanPreview({ goal, plan: p.plan });
    } finally {
      setMissionBusy(false);
    }
  }

  // 人工确认后的计划 → 执行
  async function executePlannedMission() {
    if (!planPreview || planBusy) return;
    setPlanBusy(true);
    try {
      const r = await apiClient.post<typeof missionResult>("/mission/execute", {
        goal: planPreview.goal,
        plan: planPreview.plan,
      });
      setMissionResult(r);
      setPlanPreview(null);
      void refreshMissionHistory();
    } finally {
      setPlanBusy(false);
    }
  }

  // 快捷：不预览，按 AI 原计划直接执行
  async function runMissionAuto() {
    const goal = planPreview?.goal ?? idea.trim();
    if (!goal || planBusy) return;
    setPlanBusy(true);
    try {
      const r = await apiClient.post<typeof missionResult>("/mission", { goal });
      setMissionResult(r);
      setPlanPreview(null);
      void refreshMissionHistory();
    } finally {
      setPlanBusy(false);
    }
  }

  async function refreshMissionHistory() {
    try {
      const h = await apiClient.get<{
        lessons: { goal: string; lesson: string; created_at: string }[];
        runs: {
          id: string;
          goal: string;
          plan: { step: number; kind: string; title: string }[];
          summary: string;
          created_at: string;
        }[];
      }>("/mission/history");
      setMissionLessons(h.lessons.slice(0, 5));
      setMissionRuns(h.runs.slice(0, 5));
    } catch {
      // 历史拉取失败不阻塞主流程
    }
    try {
      const p = await apiClient.get<{
        preferences: {
          styles: string[];
          themes: string[];
          steps: string[];
          agents: { id: string; name: string }[];
        };
        profile: string;
      }>("/mission/profile");
      setMissionProfile(p);
    } catch {
      // 档案拉取失败不阻塞主流程
    }
  }

  // 多轮对话链回看：整条链一次展开（缓存已拉取的链）
  const [chainCache, setChainCache] = useState<
    Record<
      string,
      {
        id: string;
        goal: string;
        summary: string;
        created_at: string;
        parent_run_id?: string;
        results: { kind: string; ok: boolean; title: string }[];
      }[]
    >
  >({});
  const [chainLoading, setChainLoading] = useState<string | null>(null);

  async function toggleChain(runId: string) {
    if (chainCache[runId]) {
      setChainCache((c) => {
        const next = { ...c };
        delete next[runId];
        return next;
      });
      return;
    }
    setChainLoading(runId);
    try {
      const r = await apiClient.get<{ runs: { id: string; goal: string; summary: string; created_at: string; results: { kind: string; ok: boolean; title: string }[] }[] }>(
        `/mission/runs/${runId}/chain`,
      );
      setChainCache((c) => ({ ...c, [runId]: r.runs }));
    } catch {
      // 链拉取失败：静默
    } finally {
      setChainLoading(null);
    }
  }

  // 多轮对话：基于当前结果继续追问（上下文链式迭代）
  async function continueMission() {
    const runId = missionResult?.run_id;
    const msg = continueMsg.trim();
    if (!runId || !msg || continueBusy) return;
    setContinueBusy(true);
    try {
      const r = await apiClient.post<typeof missionResult>(`/mission/runs/${runId}/continue`, {
        message: msg,
      });
      setMissionResult(r);
      setContinueMsg("");
      const h = await apiClient.get<{ runs: typeof missionRuns }>("/mission/history");
      setMissionRuns(h.runs.slice(0, 5));
    } finally {
      setContinueBusy(false);
    }
  }
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
      {/* 场景入口：按「想做什么」组织（先想场景，再进工具） */}
      <section className="animate-enter mb-6">
        <div className="mb-2 flex items-center gap-2">
          <h2 className="text-[15px] font-semibold">🧭 你想做什么？</h2>
          <span className="text-xs text-muted-foreground">选一个场景，工具会带好路</span>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {SCENES.map((sc) => (
            <div
              key={sc.title}
              className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3 transition-colors hover:border-primary"
            >
              <div className="flex items-center gap-2">
                <span className="text-xl">{sc.icon}</span>
                <span className="text-sm font-semibold">{sc.title}</span>
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">{sc.desc}</p>
              <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-1">
                {sc.prompt ? (
                  <button
                    onClick={() => {
                      setIdea(sc.prompt ?? "");
                      ideaRef.current?.focus();
                      window.scrollTo({ top: 0, behavior: "smooth" });
                    }}
                    className="rounded-full bg-primary px-3 py-1 text-xs text-primary-text hover:opacity-90"
                    title="把目标模板填入输入框，交给任务总控"
                  >
                    🎯 用目标框
                  </button>
                ) : (
                  <Link
                    to={sc.to}
                    className="rounded-full bg-primary px-3 py-1 text-xs text-primary-text hover:opacity-90"
                  >
                    开始 →
                  </Link>
                )}
                {sc.links.map((l) => (
                  <Link
                    key={l.label}
                    to={l.to}
                    className="rounded-full border border-border px-2.5 py-1 text-[11px] text-muted-foreground hover:border-primary hover:text-foreground"
                  >
                    {l.label}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
      <Card className="animate-enter p-6 sm:p-7">
        <h1 className="font-display text-2xl font-bold tracking-tight sm:text-[28px]">你想创作什么？</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          输入一句话，或从下方灵感开始。无需任何模型 Key 也能完整体验。
        </p>
        <div className="mt-5 rounded-2xl border border-border-strong bg-background p-3.5">
          <textarea
            ref={ideaRef}
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
            <button
              onClick={() => void runMission()}
              disabled={missionBusy || !idea.trim()}
              title="交给任务总控：先拆解计划给你确认，可调整后执行"
              className="inline-flex items-center gap-1.5 rounded-xl border border-primary/40 bg-primary/5 px-4 py-2.5 text-sm font-semibold text-primary-text transition-all duration-200 hover:-translate-y-px hover:border-primary disabled:opacity-50"
            >
              🎯 {missionBusy ? "拆解计划中…" : "交给任务总控"}
            </button>
          </div>
        </div>

        {/* 计划预览（Human-in-the-loop）：AI 拆解 → 人工调整 → 执行 */}
        {planPreview && (
          <div className="mt-4 rounded-2xl border border-primary/25 bg-primary/5 p-4">
            <p className="mb-2 flex items-center gap-2 text-sm font-semibold">
              🗺 计划预览
              <span className="text-xs font-normal text-muted-foreground">
                AI 已拆解 {planPreview.plan.length} 步——可调整顺序/删除/改写后执行
              </span>
            </p>
            <div className="flex flex-col gap-2">
              {planPreview.plan.map((step, i) => {
                const meta = KIND_META[step.kind] ?? { icon: "⚙️", label: step.kind };
                return (
                  <div key={i} className="flex items-start gap-2 rounded-xl border border-border bg-surface p-2.5">
                    <span className="mt-1.5 grid h-5 w-5 flex-none place-items-center rounded-full bg-primary/10 text-[10px] text-primary-text">
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-primary-text">
                          {meta.icon} {meta.label}
                        </span>
                        <span className="truncate font-medium">{step.title}</span>
                        {step.agent && (
                          <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-emerald-600">
                            🤖 {step.agent}
                          </span>
                        )}
                      </div>
                      <input
                        value={step.prompt}
                        onChange={(e) =>
                          setPlanPreview((p) =>
                            p
                              ? {
                                  ...p,
                                  plan: p.plan.map((s, j) =>
                                    j === i ? { ...s, prompt: e.target.value } : s,
                                  ),
                                }
                              : p,
                          )
                        }
                        className="w-full rounded-lg border border-border bg-muted/40 px-2 py-1 text-[11px] outline-none focus:border-primary"
                      />
                      {step.reason && (
                        <p className="mt-1 text-[10px] italic text-muted-foreground/80">
                          为什么：{step.reason}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-none flex-col gap-1">
                      <button
                        onClick={() =>
                          setPlanPreview((p) => {
                            if (!p) return p;
                            const plan = [...p.plan];
                            if (i === 0) return p;
                            [plan[i - 1]!, plan[i]!] = [plan[i]!, plan[i - 1]!];
                            return { ...p, plan };
                          })
                        }
                        disabled={i === 0}
                        className="rounded border border-border px-1.5 text-[10px] hover:border-primary disabled:opacity-30"
                        title="上移"
                      >
                        ↑
                      </button>
                      <button
                        onClick={() =>
                          setPlanPreview((p) => {
                            if (!p) return p;
                            const plan = [...p.plan];
                            if (i === plan.length - 1) return p;
                            [plan[i + 1]!, plan[i]!] = [plan[i]!, plan[i + 1]!];
                            return { ...p, plan };
                          })
                        }
                        disabled={i === planPreview.plan.length - 1}
                        className="rounded border border-border px-1.5 text-[10px] hover:border-primary disabled:opacity-30"
                        title="下移"
                      >
                        ↓
                      </button>
                      <button
                        onClick={() =>
                          setPlanPreview((p) =>
                            p ? { ...p, plan: p.plan.filter((_, j) => j !== i) } : p,
                          )
                        }
                        className="rounded border border-border px-1.5 text-[10px] text-danger hover:border-danger"
                        title="删除此步"
                      >
                        ✕
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                onClick={() => void executePlannedMission()}
                disabled={planBusy || planPreview.plan.length === 0}
                className="rounded-xl border border-primary/40 bg-primary/10 px-4 py-2 text-xs font-semibold hover:bg-primary/20 disabled:opacity-50"
              >
                🚀 开始执行
              </button>
              <button
                onClick={() => void runMissionAuto()}
                disabled={planBusy}
                className="rounded-xl border border-border px-3 py-2 text-[11px] text-muted-foreground hover:border-primary"
                title="不预览，按 AI 原计划直接执行"
              >
                ⚡ 直接执行
              </button>
              <button
                onClick={() => setPlanPreview(null)}
                className="rounded-xl border border-border px-3 py-2 text-[11px] text-muted-foreground hover:border-danger"
              >
                取消
              </button>
              {planBusy && <span className="text-xs text-muted-foreground">执行中…</span>}
            </div>
          </div>
        )}

        {/* 任务总控结果：计划 → 逐步执行 → 汇总 */}
        {missionResult && (
          <div className="mt-4 rounded-2xl border border-primary/25 bg-primary/5 p-4">
            <p className="mb-2 flex items-center gap-2 text-sm font-semibold">
              🎯 任务总控
              <span className="text-xs font-normal text-muted-foreground">{missionResult.summary}</span>
            </p>
            {missionProfile && (
              <div className="mb-3 rounded-xl border border-border bg-surface p-3">
                <p className="mb-1 text-xs font-semibold">🧬 成长档案（平台对你的了解）</p>
                {missionProfile.profile && (
                  <p className="mb-2 rounded-lg bg-primary/5 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
                    {missionProfile.profile}
                  </p>
                )}
                <div className="flex flex-wrap gap-1.5 text-[11px]">
                  {missionProfile.preferences.styles.map((s) => (
                    <span key={`s-${s}`} className="rounded-full bg-primary/10 px-2 py-0.5 text-primary-text">
                      🎵 {s}
                    </span>
                  ))}
                  {missionProfile.preferences.themes.map((t) => (
                    <span key={`t-${t}`} className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">
                      {t}
                    </span>
                  ))}
                  {missionProfile.preferences.agents.map((a) => (
                    <span key={a.id} className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-emerald-600">
                      🤖 {a.name}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {/* SAIOS 执行循环指示条 */}
            <div className="mb-3 flex flex-wrap items-center gap-x-1 gap-y-1 text-[10px] text-muted-foreground">
              {MISSION_LOOP.map((s, i) => (
                <span key={s} className="flex items-center gap-1">
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5",
                      i === 2 ? "bg-primary/10 text-primary-text" : "bg-muted",
                    )}
                  >
                    {s}
                  </span>
                  {i < MISSION_LOOP.length - 1 && <span className="text-muted-foreground/40">→</span>}
                </span>
              ))}
            </div>
            {/* 步骤时间线：节点 + 引擎徽章 + Agent 徽章 + 理由 + 产出 */}
            <div className="relative flex flex-col gap-3 pl-5">
              <span className="absolute bottom-3 left-[9px] top-3 w-px bg-border" aria-hidden />
              {missionResult.results.map((res) => {
                const meta = KIND_META[res.kind] ?? { icon: "⚙️", label: res.kind };
                const planStep = missionResult.plan.find((p) => p.step === res.step);
                return (
                  <div key={res.step} className="relative">
                    <span
                      className={cn(
                        "absolute -left-5 top-3.5 h-4 w-4 rounded-full border-2 border-surface",
                        res.ok ? "bg-emerald-500" : "bg-red-500",
                      )}
                      aria-hidden
                    />
                    <div
                      className={cn(
                        "rounded-xl border bg-surface p-3",
                        res.ok ? "border-border" : "border-red-500/40",
                      )}
                    >
                      <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-xs">
                        <span className="font-semibold">{res.ok ? "✅" : "❌"} 步骤 {res.step}</span>
                        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-primary-text">
                          {meta.icon} {meta.label}
                        </span>
                        {res.agent && (
                          <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-emerald-600">
                            🤖 {res.agent}
                          </span>
                        )}
                        <span className="ml-auto font-medium">{res.title}</span>
                      </div>
                      {planStep?.reason && (
                        <p className="mb-1.5 text-[10px] italic text-muted-foreground/80">
                          为什么这步：{planStep.reason}
                        </p>
                      )}
                      <pre className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground">
                        {res.summary}
                      </pre>
                      {/* 媒体产物可视化：任务进度 + 缩略图（图片/视频/漫画） */}
                      {res.task_id &&
                        (res.kind === "image" || res.kind === "video" || res.kind === "comic") && (
                          <TaskProgress taskId={res.task_id} kind={res.kind} />
                        )}
                  {/* 代码产物：文件列表 + 一键复制全部 + 下载项目包 */}
                  {res.code && res.code.length > 0 && (
                    <div className="mt-2 flex flex-col gap-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-medium text-muted-foreground">
                          📦 {res.code.length} 个文件
                        </span>
                        {missionResult && (
                          <button
                            onClick={() => {
                              const runId = (missionResult as { run_id?: string }).run_id;
                              if (!runId) return;
                              window.open(`/api/v1/mission/runs/${runId}/artifacts/zip`, "_blank");
                            }}
                            className="rounded-full border border-border px-2.5 py-0.5 text-[10px] hover:border-primary"
                          >
                            ⬇️ 下载项目包 (zip)
                          </button>
                        )}
                      </div>
                      {res.code.map((f) => (
                        <div key={f.path} className="rounded-lg bg-muted/40 px-2.5 py-1.5">
                          <div className="flex items-center justify-between gap-2">
                            <span className="truncate text-[11px] font-medium">📄 {f.path}</span>
                            <span className="flex shrink-0 gap-1.5">
                              {f.path.endsWith(".py") && (
                                <button
                                  onClick={() => void (async () => {
                                    const runId = (missionResult as { run_id?: string }).run_id;
                                    if (!runId) return;
                                    try {
                                      const r = await apiClient.post<{ ok: boolean; output: string }>(
                                        `/mission/runs/${runId}/exec`,
                                        { path: f.path },
                                      );
                                      alert(`${r.ok ? "✅ 执行成功" : "❌ 执行失败"}\n\n${r.output.slice(0, 1500)}`);
                                    } catch (e) {
                                      alert(`执行失败：${e instanceof Error ? e.message : "未知错误"}`);
                                    }
                                  })()}
                                  className="rounded-full border border-border px-2 py-0.5 text-[10px] hover:border-primary"
                                  title="在容器内执行（15s 超时，仅供验证）"
                                >
                                  ▶️ 运行
                                </button>
                              )}
                              <button
                                onClick={() => void navigator.clipboard.writeText(f.content)}
                                className="rounded-full border border-border px-2 py-0.5 text-[10px] hover:border-primary"
                              >
                                复制
                              </button>
                            </span>
                          </div>
                          <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[10px] leading-relaxed text-muted-foreground">
                            {f.content.slice(0, 1200)}
                            {f.content.length > 1200 ? "\n…（已截断，可复制全文）" : ""}
                          </pre>
                        </div>
                      ))}
                    </div>
                  )}
                    </div>
                    </div>
                  );
                })}
            </div>
            {/* 多轮对话：跑完可继续追问（链式迭代） */}
            {missionResult.run_id && (
              <div className="mt-2 flex items-center gap-2">
                <input
                  value={continueMsg}
                  onChange={(e) => setContinueMsg(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void continueMission();
                    }
                  }}
                  placeholder="继续对话：例如「副歌再温暖一点」…"
                  className="min-w-0 flex-1 rounded-xl border border-border bg-surface px-3 py-2 text-xs outline-none focus:border-primary"
                />
                <button
                  onClick={() => void continueMission()}
                  disabled={continueBusy || !continueMsg.trim()}
                  className="shrink-0 rounded-xl border border-primary/30 bg-primary/10 px-3 py-2 text-xs font-medium hover:bg-primary/20 disabled:opacity-40"
                >
                  {continueBusy ? "迭代中…" : "💬 继续"}
                </button>
              </div>
            )}
            {missionLessons.length > 0 && (
              <div className="mt-2 rounded-xl border border-border bg-surface p-3">
                <p className="mb-1 text-xs font-semibold">🧠 平台从失败中沉淀的教训（后续任务会自动避开）</p>
                <ul className="list-disc pl-4 text-[11px] leading-relaxed text-muted-foreground">
                  {missionLessons.map((l, i) => (
                    <li key={i}>{l.lesson}</li>
                  ))}
                </ul>
              </div>
            )}
            {missionRuns.length > 0 && (
              <div className="mt-2 rounded-xl border border-border bg-surface p-3">
                <p className="mb-1 text-xs font-semibold">🗂 历史任务（平台记得你下达过的目标，可回看再跑）</p>
                <div className="flex flex-col gap-1.5">
                  {missionRuns.map((run) => (
                    <div key={run.id} className="rounded-lg bg-muted/40 px-2.5 py-1.5">
                      <div className="flex items-center gap-2">
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[11px] font-medium">
                            {run.parent_run_id ? "↳ 延续 · " : ""}
                            {run.goal}
                          </span>
                          <span className="block text-[10px] text-muted-foreground">
                            {run.summary} · {run.created_at ? new Date(run.created_at).toLocaleString("zh-CN") : ""}
                          </span>
                        </span>
                        <button
                          onClick={() => void toggleChain(run.id)}
                          disabled={chainLoading === run.id}
                          className="shrink-0 rounded-full border border-border px-2.5 py-1 text-[10px] hover:border-primary"
                          title="展开整条对话链（首轮 → 最新）"
                        >
                          {chainLoading === run.id ? "…" : chainCache[run.id] ? "🔗 收起" : "🔗 链"}
                        </button>
                        <button
                          onClick={() => void (async () => {
                            setMissionBusy(true);
                            try {
                              const r = await apiClient.post<typeof missionResult>(`/mission/runs/${run.id}/reuse`, {});
                              setMissionResult(r);
                            } finally {
                              setMissionBusy(false);
                            }
                          })()}
                          className="shrink-0 rounded-full border border-border px-2.5 py-1 text-[10px] hover:border-primary"
                        >
                          🔁 再跑
                        </button>
                      </div>
                      {chainCache[run.id] && (
                        <div className="mt-2 flex flex-col gap-1.5 border-t border-border pt-2">
                          {chainCache[run.id]!.map((c, ci) => (
                            <div key={c.id} className="rounded-lg bg-surface px-2.5 py-2">
                              <div className="flex items-center gap-1.5 text-[10px]">
                                <span className="rounded-full bg-primary/10 px-2 py-0.5 text-primary-text">
                                  第 {ci + 1} 轮
                                </span>
                                <span className="min-w-0 flex-1 truncate font-medium">{c.goal}</span>
                                <span className="shrink-0 text-muted-foreground">
                                  {c.created_at ? new Date(c.created_at).toLocaleString("zh-CN") : ""}
                                </span>
                              </div>
                              <div className="mt-1 flex flex-wrap items-center gap-1 text-[10px]">
                                {c.results
                                  .filter((r2) => r2.ok)
                                  .map((r2) => {
                                    const m2 = KIND_META[r2.kind] ?? { icon: "⚙️", label: r2.kind };
                                    return (
                                      <span key={r2.kind + r2.title} className="rounded-full bg-muted px-1.5 py-0.5">
                                        {m2.icon} {r2.title}
                                      </span>
                                    );
                                  })}
                                <span className="ml-auto truncate text-muted-foreground">{c.summary}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

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
