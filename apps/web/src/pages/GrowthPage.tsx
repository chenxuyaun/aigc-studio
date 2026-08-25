/**
 * AI 成长足迹（批8+9）：
 * - 上：「AI 记得的你」长期记忆卡（偏好/背景/事件/情绪），可删除；
 * - 下：成长日记时间线——每几轮对话后台自动反思生成一篇（干了什么/学到/亮点）。
 * 数据源 /growth/diary、/growth/memories。
 */

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";

interface DiaryItem {
  id: string;
  session_id: string;
  summary: string;
  lessons: string[];
  highlights: string[];
  msg_count: number;
  created_at: string | null;
}

interface MemoryItem {
  id: string;
  kind: string;
  content: string;
  updated_at: string | null;
}

const KIND_META: Record<string, { label: string; icon: string; cls: string }> = {
  preference: { label: "偏好", icon: "🎯", cls: "border-cyan-500/30 bg-cyan-500/10 text-cyan-300" },
  fact: { label: "背景", icon: "📌", cls: "border-sky-500/30 bg-sky-500/10 text-sky-300" },
  event: { label: "事件", icon: "⚡", cls: "border-amber-500/30 bg-amber-500/10 text-amber-300" },
  emotion: { label: "情绪", icon: "💗", cls: "border-pink-500/30 bg-pink-500/10 text-pink-300" },
};

function kindMeta(k: string) {
  return KIND_META[k] ?? { label: k, icon: "🧩", cls: "border-white/15 bg-white/5 text-slate-300" };
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

export default function GrowthPage() {
  const [diaries, setDiaries] = useState<DiaryItem[]>([]);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (p: number) => {
    setLoading(true);
    setError(null);
    try {
      const [d, m] = await Promise.all([
        apiClient.get<{ items: DiaryItem[]; total: number }>(
          `/growth/diary?page=${p}&page_size=8`,
        ),
        apiClient.get<{ items: MemoryItem[] }>(`/growth/memories`),
      ]);
      setDiaries((prev) => (p === 1 ? d.items : [...prev, ...d.items]));
      setTotal(d.total);
      setPage(p);
      setMemories(m.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(1);
  }, [load]);

  async function removeMemory(id: string) {
    setMemories((prev) => prev.filter((m) => m.id !== id));
    try {
      await apiClient.post(`/growth/memories/delete`, { ids: [id] });
    } catch {
      void load(page); // 删除失败回滚刷新
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-6">
      <header>
        <h1 className="text-xl font-semibold text-slate-100">🌱 AI 成长足迹</h1>
        <p className="mt-1 text-xs text-slate-400">
          AI 在每次对话后自动复盘：沉淀成长日记，并记住你的偏好与背景（新对话自动带上）。
        </p>
      </header>

      {/* 记忆区 */}
      <section className="ai-glass rounded-2xl p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-slate-200">
            🧠 AI 记得的你
            <span className="ml-2 text-[11px] text-slate-500">{memories.length} 条</span>
          </h2>
        </div>
        {memories.length === 0 ? (
          <p className="mt-3 text-xs text-slate-500">
            还没有记忆。多聊几句，AI 会自动提炼你的偏好和背景存到这里。
          </p>
        ) : (
          <ul className="mt-3 flex flex-wrap gap-2">
            {memories.map((m) => {
              const meta = kindMeta(m.kind);
              return (
                <li
                  key={m.id}
                  className={cn(
                    "group flex max-w-full items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs",
                    meta.cls,
                  )}
                >
                  <span aria-hidden>{meta.icon}</span>
                  <span className="font-medium">{meta.label}</span>
                  <span className="max-w-[16rem] truncate text-slate-200">{m.content}</span>
                  <button
                    type="button"
                    onClick={() => void removeMemory(m.id)}
                    className="ml-0.5 text-slate-400 opacity-0 transition-opacity hover:text-rose-300 group-hover:opacity-100"
                    title="让 AI 忘记这条"
                  >
                    ✕
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {/* 日记时间线 */}
      <section className="ai-glass rounded-2xl p-4">
        <h2 className="text-sm font-medium text-slate-200">
          📔 成长日记
          <span className="ml-2 text-[11px] text-slate-500">共 {total} 篇</span>
        </h2>
        {error && <p className="mt-3 text-xs text-rose-300">{error}</p>}
        {!error && diaries.length === 0 && !loading && (
          <p className="mt-3 text-xs text-slate-500">
            还没有日记。去「AI 调度大厅」聊几轮，AI 会开始记录自己的成长。
          </p>
        )}
        <ol className="mt-4 flex flex-col gap-4 border-l border-white/10 pl-4">
          {diaries.map((d) => (
            <li key={d.id} className="relative">
              <span
                className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.7)]"
                aria-hidden
              />
              <div className="text-[11px] text-slate-500">{fmtDate(d.created_at)}</div>
              <p className="mt-0.5 text-sm leading-relaxed text-slate-100">{d.summary}</p>
              {!!d.lessons.length && (
                <ul className="mt-1.5 flex flex-col gap-1">
                  {d.lessons.map((l, i) => (
                    <li key={i} className="text-xs text-indigo-300">
                      💡 {l}
                    </li>
                  ))}
                </ul>
              )}
              {!!d.highlights.length && (
                <ul className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
                  {d.highlights.map((h, i) => (
                    <li key={i} className="text-xs text-amber-300/90">
                      ⭐ {h}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
        {diaries.length < total && (
          <button
            type="button"
            onClick={() => void load(page + 1)}
            disabled={loading}
            className="ai-glass-input mt-4 rounded-lg px-4 py-1.5 text-xs text-slate-300 hover:text-slate-100 disabled:opacity-50"
          >
            {loading ? "加载中…" : "加载更早的日记"}
          </button>
        )}
      </section>
    </div>
  );
}
