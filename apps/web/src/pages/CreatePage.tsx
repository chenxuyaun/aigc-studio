import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { cn } from "@/lib/cn";
import { CREATE_TOOLS } from "@/shared/createTools";

export function CreatePage() {
  const navigate = useNavigate();
  return (
    <div>
      <PageHeader title="AI 创作" description="选择一个工具开始创作" />
      <div className="grid gap-3 p-4 sm:grid-cols-2 md:p-6 lg:grid-cols-3">
        {CREATE_TOOLS.map((t) => (
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
  );
}
