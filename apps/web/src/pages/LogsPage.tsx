import { useState } from "react";

import type { CallLogItem } from "@aigc/shared-types";

import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { apiClient } from "@/lib/apiClient";


const STATUS_META: Record<string, { label: string; cls: string }> = {
  succeeded: { label: "成功", cls: "text-success" },
  fallback: { label: "回退", cls: "text-warning" },
  failed: { label: "失败", cls: "text-danger" },
};

const TYPE_LABEL: Record<string, string> = {
  text: "文本",
  image: "图片",
  audio: "语音",
  video: "视频",
};

function fmtDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false });
}

export function LogsPage() {
  const [taskType, setTaskType] = useState("");
  const [status, setStatus] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const logs = useQuery({
    queryKey: ["call-logs", taskType, status, refreshKey],
    queryFn: async () => {
      const params = new URLSearchParams({ limit: "100" });
      if (taskType) params.set("task_type", taskType);
      if (status) params.set("status", status);
      return apiClient.get<CallLogItem[]>(`/logs/?${params.toString()}`);
    },
    refetchInterval: 10_000,
  });

  return (
    <div>
      <PageHeader
        title="运行日志"
        description="Provider 调用记录：成功 / 回退 / 失败及具体原因（每 10 秒自动刷新）"
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => setRefreshKey((k) => k + 1)}
            loading={logs.isFetching}
          >
            <RefreshCw className="h-4 w-4" aria-hidden />
            刷新
          </Button>
        }
      >
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          类型
          <select
            value={taskType}
            onChange={(e) => setTaskType(e.target.value)}
            className="h-9 rounded-lg border border-input bg-surface px-3 text-sm"
          >
            <option value="">全部</option>
            {Object.entries(TYPE_LABEL).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          状态
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="h-9 rounded-lg border border-input bg-surface px-3 text-sm"
          >
            <option value="">全部</option>
            <option value="succeeded">成功</option>
            <option value="fallback">回退</option>
            <option value="failed">失败</option>
          </select>
        </label>
      </PageHeader>
      <div className="flex flex-col gap-4 p-4 md:p-6">
        {logs.isLoading ? (
          <p className="py-8 text-center text-sm text-muted-foreground">加载中…</p>
        ) : logs.isError ? (
          <div className="flex flex-col items-center gap-3 py-8">
            <p className="text-sm text-danger" role="alert">
              日志加载失败
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void logs.refetch()}
              loading={logs.isFetching}
            >
              <RefreshCw className="h-4 w-4" aria-hidden />
              重试
            </Button>
          </div>
        ) : !logs.data?.length ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            暂无记录——生成过内容后这里会显示每次 Provider 调用的结果
          </p>
        ) : (
          <div className="overflow-x-auto rounded-[var(--radius-card)] border border-border bg-surface">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-border text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 font-medium">时间</th>
                  <th className="px-4 py-3 font-medium">类型</th>
                  <th className="px-4 py-3 font-medium">Provider / 模型</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                  <th className="px-4 py-3 font-medium">耗时</th>
                  <th className="px-4 py-3 font-medium">原因 / 备注</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {logs.data.map((l) => {
                  const meta = STATUS_META[l.status] ?? {
                    label: l.status,
                    cls: "text-muted-foreground",
                  };
                  return (
                    <tr key={l.id} className="align-top">
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                        {fmtTime(l.created_at)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        {TYPE_LABEL[l.task_type] ?? (l.task_type || "—")}
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-mono text-xs">{l.provider || "—"}</span>
                        {l.model && (
                          <span className="block text-xs text-muted-foreground">{l.model}</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <span className={`font-medium ${meta.cls}`}>{meta.label}</span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                        {fmtDuration(l.duration_ms)}
                      </td>
                      <td className="max-w-[380px] px-4 py-3">
                        {l.error_message ? (
                          <span
                            className="block break-all font-mono text-xs text-muted-foreground"
                            title={l.error_message}
                          >
                            {l.error_message}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
