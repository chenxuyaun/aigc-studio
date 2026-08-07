import type { ComponentProps, ReactNode } from "react";

import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/cn";

/**
 * 下拉选择：原生 select 美化（键盘/读屏零成本），右侧箭头指示。
 * 宽度默认撑满容器；需要自适应宽度时在外层包 inline-flex。
 */
export function Select({
  className,
  children,
  ...props
}: ComponentProps<"select"> & { children: ReactNode }) {
  return (
    <div className="relative">
      <select
        className={cn(
          "h-10 w-full appearance-none rounded-xl border border-input bg-surface pl-3.5 pr-9 text-sm text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          "disabled:opacity-50",
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden
      />
    </div>
  );
}
