import type { ReactNode } from "react";

import { AlertTriangle, Inbox, Loader2, SearchX } from "lucide-react";

import { AppError } from "@/lib/apiClient";

import { Button } from "./Button";

export function LoadingState({ label = "加载中…" }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
      <Loader2 className="h-6 w-6 animate-spin" aria-hidden />
      <p className="text-sm" role="status">
        {label}
      </p>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <Inbox className="h-8 w-8 text-muted-foreground" aria-hidden />
      <h3 className="text-base font-semibold text-foreground">{title}</h3>
      {description && <p className="max-w-sm text-sm text-muted-foreground">{description}</p>}
      {action}
    </div>
  );
}

/** 搜索/筛选无结果：区别于空库的 EmptyState，附带「清除筛选」复位。 */
export function EmptyQuery({ onReset, label = "没有匹配的结果" }: { onReset?: () => void; label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <SearchX className="h-8 w-8 text-muted-foreground" aria-hidden />
      <h3 className="text-base font-semibold text-foreground">{label}</h3>
      <p className="max-w-sm text-sm text-muted-foreground">试试换一个关键词，或清除筛选条件。</p>
      {onReset && (
        <Button variant="outline" size="sm" onClick={onReset}>
          清除筛选
        </Button>
      )}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof AppError ? error.message : "发生了未知错误，请稍后重试。";
  const requestId = error instanceof AppError ? error.requestId : undefined;
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <AlertTriangle className="h-8 w-8 text-danger" aria-hidden />
      <h3 className="text-base font-semibold text-foreground">出错了</h3>
      <p className="max-w-sm text-sm text-muted-foreground">{message}</p>
      {requestId && <p className="text-xs text-muted-foreground">Request ID: {requestId}</p>}
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          重试
        </Button>
      )}
    </div>
  );
}
