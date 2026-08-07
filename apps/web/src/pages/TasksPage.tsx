import { useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  ChevronLeft,
  ChevronRight,
  Eye,
  Plus,
  RefreshCw,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import type { GenerationTask, Paginated } from "@aigc/shared-types";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Dialog } from "@/components/ui/Dialog";
import { ListSkeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { AppError, apiClient } from "@/lib/apiClient";

const TYPE_LABEL: Record<string, string> = {
  text: "文本",
  image: "图片",
  video: "视频",
  audio: "语音",
};

const STATUS_OPTS = [
  { v: "", label: "全部状态" },
  { v: "queued", label: "排队中" },
  { v: "processing", label: "进行中" },
  { v: "succeeded", label: "成功" },
  { v: "failed", label: "失败" },
  { v: "cancelled", label: "已取消" },
];

const TYPE_OPTS = [
  { v: "", label: "全部类型" },
  { v: "text", label: "文本" },
  { v: "image", label: "图片" },
  { v: "video", label: "视频" },
  { v: "audio", label: "语音" },
];

const CREATE_LINKS = [
  { to: "/create/image", label: "图片" },
  { to: "/create/text", label: "文本" },
  { to: "/create/video", label: "视频" },
  { to: "/create/audio", label: "语音" },
] as const;

const PAGE_SIZE = 20;
const TERMINAL = new Set(["succeeded", "failed", "cancelled", "expired"]);

function parseResult(raw: string): { asset_id?: string; text?: string; mime?: string } | null {
  if (!raw) return null;
  try {
    const obj = JSON.parse(raw) as { asset_id?: string; mime?: string };
    if (obj && typeof obj === "object") return obj;
  } catch {
    return { text: raw };
  }
  return { text: raw };
}

function parseParams(raw?: string): Record<string, unknown> {
  if (!raw) return {};
  try {
    const obj = JSON.parse(raw) as unknown;
    return obj && typeof obj === "object" && !Array.isArray(obj)
      ? (obj as Record<string, unknown>)
      : {};
  } catch {
    return {};
  }
}

/** 把任务 params 映射到各创作页 location.state，实现「再次运行」。 */
function rerunState(task: GenerationTask): { path: string; state: Record<string, unknown> } | null {
  const p = parseParams(task.params);
  switch (task.task_type) {
    case "image":
      return {
        path: "/create/image",
        state: {
          prompt: typeof p.prompt === "string" ? p.prompt : "",
          negative_prompt: typeof p.negative_prompt === "string" ? p.negative_prompt : "",
          width: typeof p.width === "number" ? p.width : undefined,
          height: typeof p.height === "number" ? p.height : undefined,
          reference_photo_id:
            typeof p.reference_photo_id === "string" ? p.reference_photo_id : undefined,
          reference_asset_id:
            typeof p.reference_asset_id === "string" ? p.reference_asset_id : undefined,
        },
      };
    case "text":
      return {
        path: "/create/text",
        state: {
          prompt: typeof p.prompt === "string" ? p.prompt : "",
          model: typeof p.model === "string" ? p.model : task.model,
        },
      };
    case "video":
      return {
        path: "/create/video",
        state: {
          prompt: typeof p.prompt === "string" ? p.prompt : "",
          duration: typeof p.duration === "number" ? p.duration : undefined,
        },
      };
    case "audio":
      return {
        path: "/create/audio",
        state: {
          text: typeof p.text === "string" ? p.text : typeof p.prompt === "string" ? p.prompt : "",
          voice: typeof p.voice === "string" ? p.voice : undefined,
        },
      };
    default:
      return null;
  }
}

export function TasksPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [taskType, setTaskType] = useState("");
  const [detail, setDetail] = useState<GenerationTask | null>(null);
  const [toDelete, setToDelete] = useState<GenerationTask | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // 正在取消的任务 id（按行 loading，不再整页共用）
  const [cancelingId, setCancelingId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);

  const query = useQuery({
    queryKey: ["tasks", { page, status, taskType }],
    queryFn: () => {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (status) params.set("status", status);
      if (taskType) params.set("task_type", taskType);
      return apiClient.get<Paginated<GenerationTask>>(`/tasks/?${params}`);
    },
    refetchInterval: (q) => {
      const items = q.state.data?.items ?? [];
      return items.some((t) => !TERMINAL.has(t.status)) ? 2500 : false;
    },
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => {
      setCancelingId(id);
      return apiClient.post(`/tasks/${id}/cancel`);
    },
    onSettled: () => setCancelingId(null),
    onSuccess: () => {
      setActionError(null);
      void qc.invalidateQueries({ queryKey: ["tasks"] });
      if (detail) {
        void apiClient
          .get<GenerationTask>(`/tasks/${detail.id}`)
          .then(setDetail)
          .catch(() => undefined);
      }
    },
    onError: (err) => {
      setActionError(err instanceof AppError ? err.message : "取消失败");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.del(`/tasks/${id}`),
    onSuccess: (_data, id) => {
      setActionError(null);
      setToDelete(null);
      if (detail?.id === id) setDetail(null);
      void qc.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (err) => {
      setActionError(err instanceof AppError ? err.message : "删除失败");
    },
  });

  const pages = query.data?.pages ?? 0;
  const total = query.data?.total ?? 0;
  const resultView = useMemo(
    () => (detail ? parseResult(detail.result || "") : null),
    [detail],
  );
  const detailParams = useMemo(
    () => (detail ? parseParams(detail.params) : {}),
    [detail],
  );

  function handleRerun(task: GenerationTask) {
    const target = rerunState(task);
    if (!target) {
      setActionError("该任务类型暂不支持再次运行");
      return;
    }
    navigate(target.path, { state: target.state });
  }

  return (
    <div>
      <PageHeader
        title="任务中心"
        description={total > 0 ? `共 ${total} 条任务` : "查看全部生成任务与实时状态"}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden />
              新建任务
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void query.refetch()}
              loading={query.isFetching}
            >
              <RefreshCw className="h-4 w-4" aria-hidden />
              刷新
            </Button>
          </div>
        }
      >
        <select
          value={taskType}
          onChange={(e) => {
            setTaskType(e.target.value);
            setPage(1);
          }}
          className="h-9 rounded-lg border border-input bg-surface px-3 text-sm"
          aria-label="任务类型"
        >
          {TYPE_OPTS.map((o) => (
            <option key={o.v || "all"} value={o.v}>
              {o.label}
            </option>
          ))}
        </select>
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
          className="h-9 rounded-lg border border-input bg-surface px-3 text-sm"
          aria-label="任务状态"
        >
          {STATUS_OPTS.map((o) => (
            <option key={o.v || "all"} value={o.v}>
              {o.label}
            </option>
          ))}
        </select>
      </PageHeader>
      <div className="space-y-4 p-4 md:p-6">
        {actionError && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {actionError}
          </p>
        )}

        {query.isPending ? (
          <ListSkeleton />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : query.data.items.length === 0 ? (
          <EmptyState
            title="还没有任务"
            description="从文本或图片生成开始，你的任务会显示在这里。"
            action={
              <Button size="sm" onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4" aria-hidden />
                新建任务
              </Button>
            }
          />
        ) : (
          <>
            <ul className="space-y-2">
              {query.data.items.map((task) => (
                <Card
                  key={task.id}
                  className="flex flex-wrap items-center justify-between gap-3 p-3"
                >
                  <button
                    type="button"
                    className="min-w-0 flex-1 text-left"
                    onClick={() => setDetail(task)}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded bg-secondary px-1.5 py-0.5 text-xs text-secondary-foreground">
                        {TYPE_LABEL[task.task_type] ?? task.task_type}
                      </span>
                      <span className="truncate text-sm text-muted-foreground">{task.model}</span>
                      <StatusBadge status={task.status} />
                    </div>
                    <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{task.id}</p>
                  </button>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {task.status === "processing" && (
                      <span className="text-xs tabular-nums text-muted-foreground">
                        {task.progress}%
                      </span>
                    )}
                    <Button variant="ghost" size="sm" onClick={() => setDetail(task)}>
                      <Eye className="h-4 w-4" aria-hidden />
                      详情
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleRerun(task)}
                      title="用相同参数再次生成"
                    >
                      <RotateCcw className="h-4 w-4" aria-hidden />
                      再跑
                    </Button>
                    {!TERMINAL.has(task.status) && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="text-danger"
                        loading={cancelingId === task.id}
                        disabled={cancelingId !== null && cancelingId !== task.id}
                        onClick={() => cancelMutation.mutate(task.id)}
                      >
                        <Ban className="h-4 w-4" aria-hidden />
                        取消
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-danger"
                      onClick={() => setToDelete(task)}
                      aria-label="删除任务"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </Button>
                  </div>
                </Card>
              ))}
            </ul>

            {pages > 1 && (
              <div className="flex items-center justify-center gap-3 pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  <ChevronLeft className="h-4 w-4" aria-hidden />
                  上一页
                </Button>
                <span className="text-sm text-muted-foreground">
                  {page} / {pages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= pages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  下一页
                  <ChevronRight className="h-4 w-4" aria-hidden />
                </Button>
              </div>
            )}
          </>
        )}
      </div>

      {detail && (
        <Dialog
          open
          onClose={() => setDetail(null)}
          title={`任务 · ${TYPE_LABEL[detail.task_type] ?? detail.task_type}`}
        >
          <div className="space-y-3 p-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={detail.status} />
              <span className="text-muted-foreground">{detail.model}</span>
              {detail.status === "processing" && (
                <span className="tabular-nums text-muted-foreground">{detail.progress}%</span>
              )}
            </div>
            <p className="break-all font-mono text-xs text-muted-foreground">{detail.id}</p>
            {detail.error_message && (
              <p className="rounded-lg bg-danger/10 px-3 py-2 text-danger">{detail.error_message}</p>
            )}
            {typeof detailParams.prompt === "string" && detailParams.prompt && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">提示词</p>
                <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-surface p-3 text-xs">
                  {String(detailParams.prompt).slice(0, 2000)}
                </pre>
              </div>
            )}
            {["seed", "cfg_scale", "steps", "width", "height", "num_images"].some(
              (k) => detailParams[k] !== undefined && detailParams[k] !== null,
            ) && (
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">生成参数</p>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 rounded-lg border border-border bg-surface p-3 text-xs">
                  {[
                    ["模型", detail.model],
                    ["尺寸", detailParams.width && detailParams.height
                      ? `${detailParams.width}×${detailParams.height}`
                      : undefined],
                    ["张数", detailParams.num_images],
                    ["种子 Seed", detailParams.seed],
                    ["CFG 强度", detailParams.cfg_scale],
                    ["采样步数", detailParams.steps],
                  ]
                    .map(([k, v]) => {
                      const value = v as string | number | undefined;
                      if (value === undefined || value === null || value === "") return null;
                      return (
                        <div key={String(k)} className="flex justify-between gap-2">
                          <dt className="text-muted-foreground">{String(k)}</dt>
                          <dd className="font-mono">{String(value)}</dd>
                        </div>
                      );
                    })}
                </dl>
              </div>
            )}
            {resultView?.asset_id && (
              <p>
                产物素材：{" "}
                <Link
                  className="text-primary-text hover:underline"
                  to="/assets"
                  state={{ highlight: resultView.asset_id }}
                >
                  {resultView.asset_id}
                </Link>
                {" · "}
                <Link className="text-primary-text hover:underline" to="/assets">
                  打开素材库
                </Link>
              </p>
            )}
            {resultView?.text && (
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-surface p-3 text-xs">
                {resultView.text.slice(0, 4000)}
              </pre>
            )}
            {!resultView?.asset_id && !resultView?.text && detail.result && (
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-surface p-3 text-xs">
                {detail.result.slice(0, 2000)}
              </pre>
            )}
            <div className="flex flex-wrap gap-2 pt-1">
              <Button variant="outline" onClick={() => handleRerun(detail)}>
                <RotateCcw className="h-4 w-4" aria-hidden />
                再次运行
              </Button>
              {!TERMINAL.has(detail.status) && (
                <Button
                  variant="outline"
                  className="text-danger"
                  loading={cancelingId === detail.id}
                  onClick={() => cancelMutation.mutate(detail.id)}
                >
                  <Ban className="h-4 w-4" aria-hidden />
                  取消任务
                </Button>
              )}
              <Button
                variant="outline"
                className="text-danger"
                onClick={() => setToDelete(detail)}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
                删除
              </Button>
              <Button variant="ghost" onClick={() => setDetail(null)}>
                关闭
              </Button>
            </div>
          </div>
        </Dialog>
      )}

      {createOpen && (
        <Dialog open onClose={() => setCreateOpen(false)} title="新建任务">
          <div className="space-y-3 p-4">
            <p className="text-sm text-muted-foreground">
              任务由各创作入口创建。选择类型进入对应页面开始生成。
            </p>
            <div className="grid grid-cols-2 gap-2">
              {CREATE_LINKS.map((link) => (
                <Button
                  key={link.to}
                  variant="outline"
                  className="justify-start"
                  onClick={() => {
                    setCreateOpen(false);
                    navigate(link.to);
                  }}
                >
                  <Plus className="h-4 w-4" aria-hidden />
                  {link.label}生成
                </Button>
              ))}
            </div>
          </div>
        </Dialog>
      )}

      <ConfirmDialog
        open={Boolean(toDelete)}
        title="删除任务"
        description={`将删除任务「${toDelete?.id?.slice(0, 8) ?? ""}…」（${TYPE_LABEL[toDelete?.task_type ?? ""] ?? toDelete?.task_type ?? ""}）。产物素材不会自动删除。`}
        confirmText="删除"
        loading={deleteMutation.isPending}
        onConfirm={() => toDelete && deleteMutation.mutate(toDelete.id)}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}
