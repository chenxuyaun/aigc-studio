import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

export interface CardProps extends ComponentProps<"div"> {
  /** 可交互卡片：hover 时边框转青瓷（v11 动效纪律：不变高不缩放） */
  hoverable?: boolean;
}

export function Card({ className, hoverable = false, ...props }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-line bg-surface shadow-zen",
        hoverable && "transition-colors hover:border-primary/40",
        className,
      )}
      {...props}
    />
  );
}
