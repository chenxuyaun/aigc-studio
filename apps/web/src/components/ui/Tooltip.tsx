import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/** 悬浮提示：hover/键盘聚焦显示，纯 CSS 实现，不阻塞交互。 */
export function Tooltip({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={cn("group/tip relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          "shadow-pop pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 -translate-x-1/2",
          "whitespace-nowrap rounded-lg border border-border bg-surface-raised px-2 py-1 text-xs text-foreground",
          "opacity-0 transition-opacity duration-150 group-hover/tip:opacity-100 group-focus-within/tip:opacity-100",
        )}
      >
        {label}
      </span>
    </span>
  );
}
