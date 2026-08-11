import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { cn } from "@/lib/cn";
import { CREATE_TOOLS } from "@/shared/createTools";

const GROUPS = [
  {
    key: "core" as const,
    label: "引擎直控",
    hint: "更简单？去工作台一句话就能搞定这些",
    items: CREATE_TOOLS.filter((t) => t.group === "core"),
  },
  {
    key: "suite" as const,
    label: "创作套件",
    hint: "导演选角 · 角色卡 · 提示词 · 写真",
    items: CREATE_TOOLS.filter((t) => t.group === "suite"),
  },
];

export function CreatePage() {
  const navigate = useNavigate();
  const [idea, setIdea] = useState("");

  function handToMission() {
    const goal = idea.trim();
    if (!goal) return;
    navigate(`/?goal=${encodeURIComponent(goal)}`);
  }

  return (
    <div>
      <PageHeader title="AI 创作" description="要什么直接说，或选引擎精调" />

      {/* 目标驱动条（Harness 主入口）：一句话 → 任务总控自主编排 */}
      <div className="mx-4 mb-4 rounded-2xl border border-primary/25 bg-primary/5 p-4 md:mx-6">
        <p className="mb-2 text-xs font-semibold">🎯 目标驱动（推荐）</p>
        <div className="flex items-center gap-2">
          <input
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handToMission();
            }}
            placeholder="想要什么？直接说（写歌、配图、做网页、写小说…）"
            className="min-w-0 flex-1 rounded-xl border border-border bg-surface px-3 py-2.5 text-sm outline-none focus:border-primary"
          />
          <button
            onClick={handToMission}
            disabled={!idea.trim()}
            className="shrink-0 rounded-xl border border-primary/40 bg-primary/10 px-4 py-2.5 text-sm font-semibold text-primary-text hover:bg-primary/20 disabled:opacity-50"
          >
            🎯 交给任务总控
          </button>
        </div>
      </div>

      {GROUPS.map((g) => (
        <div key={g.key} className="mb-4 px-4 md:px-6">
          <p className="mb-1 flex items-baseline gap-2 text-sm font-semibold">
            {g.label}
            <span className="text-[11px] font-normal text-muted-foreground">{g.hint}</span>
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {g.items.map((t) => (
              <button
                key={t.to}
                disabled={!t.ready}
                onClick={() => t.ready && navigate(t.to)}
                className={cn(
                  "flex flex-col gap-3 rounded-[var(--radius-card)] border border-border bg-surface p-5 text-left transition-all",
                  t.ready ? "hover:-translate-y-0.5 hover:border-primary" : "cursor-not-allowed opacity-55",
                )}
              >
                <span className="grid h-11 w-11 place-items-center rounded-xl bg-primary/12 text-primary-text">
                  <t.icon className="h-5.5 w-5.5" aria-hidden />
                </span>
                <span>
                  <span className="block text-[15px] font-semibold">{t.title}</span>
                  <span className="mt-1 block text-sm text-muted-foreground">{t.desc}</span>
                </span>
                <span className="mt-auto font-mono-ui text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                  {t.scene}
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
