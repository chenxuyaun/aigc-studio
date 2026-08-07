import { cn } from "@/lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-muted", className)} aria-hidden />;
}

/** 任务列表骨架屏。 */
export function ListSkeleton({ count = 6 }: { count?: number }) {
  return (
    <ul className="space-y-2" aria-label="加载中">
      {Array.from({ length: count }).map((_, i) => (
        <li
          key={i}
          className="flex items-center justify-between gap-3 rounded-[var(--radius-card)] border border-border bg-surface-raised p-3"
        >
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-2.5 w-40" />
          </div>
          <Skeleton className="h-5 w-16" />
        </li>
      ))}
    </ul>
  );
}

/** 素材网格骨架屏。 */
export function GridSkeleton({ count = 12 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" aria-label="加载中">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="overflow-hidden rounded-[var(--radius-card)] border border-border">
          <Skeleton className="aspect-square w-full rounded-none" />
          <Skeleton className="m-2 h-3 w-2/3" />
        </div>
      ))}
    </div>
  );
}

/** 画廊瀑布流骨架屏（形状贴近真实卡片，避免布局跳动）。 */
export function GallerySkeleton({ count = 12 }: { count?: number }) {
  const heights = ["h-40", "h-56", "h-44", "h-64", "h-48", "h-60"];
  return (
    <div className="columns-2 gap-3 sm:columns-3 lg:columns-4 xl:columns-5" aria-label="加载中">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="mb-3 break-inside-avoid overflow-hidden rounded-xl border border-border bg-surface-raised"
        >
          <Skeleton className={cn("w-full rounded-none", heights[i % heights.length])} />
          <div className="space-y-2 p-3">
            <Skeleton className="h-3 w-3/4" />
            <Skeleton className="h-2.5 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  );
}
