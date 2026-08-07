import type { ReactNode } from "react";

/**
 * 页面头部：标题行 + 可选工具条（筛选/搜索/tab）。
 * sticky 吸顶，滚动时标题与工具条保持可见，只有内容区滚动。
 */
export function PageHeader({
  title,
  description,
  actions,
  children,
  onTitleClick,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  children?: ReactNode;
  /** 标题点击回调（隐藏彩蛋/手势触发用） */
  onTitleClick?: () => void;
}) {
  return (
    <div className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur">
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-4 md:px-6">
        <div>
          <h1
            onClick={onTitleClick}
            className={`text-lg font-semibold text-foreground ${
              onTitleClick ? "cursor-pointer select-none" : ""
            }`}
          >
            {title}
          </h1>
          {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children && (
        <div className="flex flex-wrap items-center gap-2 px-4 pb-3 md:px-6">{children}</div>
      )}
    </div>
  );
}
