/**
 * Agent 团队协作（批10）：给一个目标 → AI 规划分工 → 成员串行接力 → 最终报告。
 * 运行过程 3s 轮询，实时看到每位成员的产出。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";

interface Member {
  name: string;
  role: string;
  task: string;
}
interface Step {
  name: string;
  role: string;
  output: string;
}
interface TeamRun {
  id: string;
  goal: string;
  status: "planning" | "running" | "done" | "failed";
  members: Member[];
  steps: Step[];
  final_report?: string;
  error?: string;
  created_at: string | null;
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  planning: { label: "规划分工中…", cls: "bg-amber-500/15 text-amber-300 border-amber-500/40" },
  running: { label: "成员接力执行中…", cls: "bg-cyan-500/15 text-cyan-300 border-cyan-500/40 animate-pulse" },
  done: { label: "✅ 已完成", cls: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40" },
  failed: { label: "❌ 失败", cls: "bg-rose-500/15 text-rose-300 border-rose-500/40" },
};

export default function TeamPage() {
  const [goal, setGoal] = useState("");
  const [run, setRun] = useState<TeamRun | null>(null);
  const [history, setHistory] = useState<TeamRun[]>([]);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      const r = await apiClient.get<{ items: TeamRun[] }>(`/teams?limit=8`);
      setHistory(r.items);
    } catch {
      /* 列表失败静默 */
    }
  }, []);

  useEffect(() => {
    void loadHistory();
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [loadHistory]);

  // 运行中轮询
  useEffect(() => {
    if (!run || run.status === "done" || run.status === "failed") return;
    timerRef.current = setInterval(async () => {
      try {
        const fresh = await apiClient.get<TeamRun>(`/teams/${run.id}`);
        setRun(fresh);
        if (fresh.status === "done" || fresh.status === "failed") {
          if (timerRef.current) clearInterval(timerRef.current);
          void loadHistory();
        }
      } catch {
        /* 单次轮询失败忽略 */
      }
    }, 3000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [run, loadHistory]);

  async function start() {
    const g = goal.trim();
    if (g.length < 2) return;
    setStarting(true);
    setError(null);
    try {
      const r = await apiClient.post<{ id: string }>("/teams/start", { goal: g });
      setRun({
        id: r.id,
        goal: g,
        status: "planning",
        members: [],
        steps: [],
        final_report: "",
        created_at: null,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "启动失败");
    } finally {
      setStarting(false);
    }
  }

  const statusMeta = run ? STATUS_META[run.status] ?? STATUS_META.planning : null;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">🤖 Agent 团队协作</h1>
        <p className="mt-1 text-xs text-slate-400">
          给一个目标，AI 自动组建团队（策划→执行→审校），成员接力完成并交付最终报告。
        </p>
      </header>

      {/* 发起 */}
      <section className="ai-glass rounded-2xl p-4">
        <textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          rows={2}
          placeholder="例：为一款手冲咖啡壶写一套上市文案（含名字、slogan、详情页要点）"
          className="ai-glass-input w-full resize-y rounded-lg px-3 py-2 text-sm text-slate-100 outline-none"
        />
        <div className="mt-2 flex items-center gap-3">
          <button
            type="button"
            onClick={() => void start()}
            disabled={starting || goal.trim().length < 2}
            className="rounded-lg bg-cyan-600/80 px-4 py-1.5 text-sm font-medium text-white hover:bg-cyan-600 disabled:opacity-50"
          >
            {starting ? "组建中…" : "🚀 组建团队开工"}
          </button>
          {error && <span className="text-xs text-rose-300">{error}</span>}
        </div>
      </section>

      {/* 当前运行 */}
      {run && (
        <section className="ai-glass rounded-2xl p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="max-w-[60%] truncate text-sm font-medium text-slate-200">
              🎯 {run.goal}
            </h2>
            <span className={cn("rounded-full border px-3 py-1 text-[11px]", statusMeta?.cls)}>
              {statusMeta?.label}
            </span>
          </div>

          {!!run.members.length && (
            <ol className="mt-3 flex flex-wrap gap-2">
              {run.members.map((m, i) => {
                const started = run.steps.length > i;
                return (
                  <li
                    key={i}
                    className={cn(
                      "rounded-lg border px-3 py-1.5 text-xs",
                      started
                        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                        : "border-white/10 bg-white/5 text-slate-400",
                    )}
                    title={m.task}
                  >
                    {started ? "✓" : i + 1}. {m.name} · {m.role}
                  </li>
                );
              })}
            </ol>
          )}

          <ol className="mt-4 flex flex-col gap-3">
            {(run.steps ?? []).map((s, i) => (
              <li key={i} className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-3">
                <div className="text-xs font-medium text-cyan-300">
                  👤 {s.name} · {s.role}
                </div>
                <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
                  {s.output}
                </p>
              </li>
            ))}
          </ol>

          {run.status === "done" && !!run.final_report && (
            <div className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3">
              <div className="text-xs font-medium text-emerald-300">📦 最终交付报告</div>
              <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-slate-100">
                {run.final_report}
              </p>
            </div>
          )}
          {run.status === "failed" && (
            <p className="mt-3 text-xs text-rose-300">失败原因：{run.error}</p>
          )}
        </section>
      )}

      {/* 历史 */}
      {!!history.length && (
        <section className="ai-glass rounded-2xl p-4">
          <h2 className="text-sm font-medium text-slate-200">🗂️ 最近协作</h2>
          <ul className="mt-3 flex flex-col gap-2">
            {history.map((h) => {
              const meta = STATUS_META[h.status] ?? {
                label: "规划分工中…",
                cls: "bg-amber-500/15 text-amber-300 border-amber-500/40",
              };
              return (
                <li key={h.id}>
                  <button
                    type="button"
                    onClick={() => setRun(h)}
                    className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-slate-300 hover:bg-white/5"
                  >
                    <span className={cn("shrink-0 rounded-full border px-2 py-0.5 text-[10px]", meta.cls)}>
                      {meta.label}
                    </span>
                    <span className="min-w-0 flex-1 truncate">{h.goal}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
