import { useSearchParams } from "react-router-dom";

import { Sparkles, Wand2 } from "lucide-react";

import { cn } from "@/lib/cn";
import { PageHeader } from "@/components/layout/PageHeader";
import { PromptGeneratorPanel } from "@/pages/PromptGeneratorPage";
import { PromptOptimizerPanel } from "@/pages/PromptOptimizerPage";

/**
 * v2：提示词生成器 + 优化器合并为双 tab 工坊（原两个独立页面/两条导航收敛）。
 * /create/prompt?tab=optimize 直达优化 tab；旧 /create/prompt-optimize 路由 301 到此。
 */
export function PromptStudioPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "optimize" ? "optimize" : "generate";

  return (
    <div className="space-y-4">
      <PageHeader
        title="提示词工坊"
        description="生成结构化提示词，或对已有提示词诊断优化"
      />
      <div className="inline-flex gap-1 rounded-xl border border-border bg-surface p-1 text-sm">
        {(
          [
            ["generate", "✨ 生成", <Sparkles key="i1" className="h-3.5 w-3.5" aria-hidden />],
            ["optimize", "🔧 优化", <Wand2 key="i2" className="h-3.5 w-3.5" aria-hidden />],
          ] as const
        ).map(([key, label, icon]) => (
          <button
            key={key}
            onClick={() => setParams(key === "generate" ? {} : { tab: "optimize" }, { replace: true })}
            className={cn(
              "flex items-center gap-1.5 rounded-lg px-4 py-1.5 transition-colors",
              tab === key
                ? "bg-primary/12 font-semibold text-primary-text"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {icon}
            {label}
          </button>
        ))}
      </div>
      {tab === "generate" ? <PromptGeneratorPanel /> : <PromptOptimizerPanel />}
    </div>
  );
}
