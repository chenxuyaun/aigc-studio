import { Ban, CheckCircle2, Clock, Loader2, XCircle } from "lucide-react";

import type { TaskStatus } from "@aigc/shared-types";

import { cn } from "@/lib/cn";

const CONFIG: Record<TaskStatus, { label: string; className: string; spin?: boolean }> = {
  queued: { label: "排队中", className: "text-muted-foreground" },
  submitting: { label: "提交中", className: "text-info", spin: true },
  processing: { label: "处理中", className: "text-info", spin: true },
  succeeded: { label: "已完成", className: "text-success" },
  failed: { label: "失败", className: "text-danger" },
  cancelled: { label: "已取消", className: "text-muted-foreground" },
  expired: { label: "已过期", className: "text-warning" },
};

function iconFor(status: TaskStatus) {
  switch (status) {
    case "succeeded":
      return CheckCircle2;
    case "failed":
      return XCircle;
    case "cancelled":
      return Ban;
    case "processing":
    case "submitting":
      return Loader2;
    default:
      return Clock;
  }
}

/** 任务状态徽章：文字 + 图标 + 颜色三重表达（不依赖颜色单独区分）。 */
export function StatusBadge({ status }: { status: TaskStatus | string | undefined }) {
  const cfg = CONFIG[status as TaskStatus];
  if (!cfg) {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
        <Clock className="h-4 w-4" aria-hidden />
        {status ?? "未知"}
      </span>
    );
  }
  const Icon = iconFor(status as TaskStatus);
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm font-medium", cfg.className)}>
      <Icon className={cn("h-4 w-4", cfg.spin && "animate-spin")} aria-hidden />
      {cfg.label}
    </span>
  );
}
