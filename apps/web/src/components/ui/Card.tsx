import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

export interface CardProps extends ComponentProps<"div"> {
  /** 可交互卡片：悬浮微抬升 + 阴影加深（列表项/统计卡/可点击区块用） */
  hoverable?: boolean;
}

export function Card({ className, hoverable = false, ...props }: CardProps) {
  return (
    <div
      className={cn(
        "shadow-soft rounded-[var(--radius-card)] border border-border bg-surface-raised",
        hoverable && "hover-lift hover:border-border-strong",
        className,
      )}
      {...props}
    />
  );
}
