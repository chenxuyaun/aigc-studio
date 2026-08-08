import { useMemo, useState, type FormEvent } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, GitBranch, Heart, Play, Plus, Search, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { Paginated, Workflow, WorkflowCategory } from "@aigc/shared-types";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Field";
import { MarkdownContent } from "@/components/ui/MarkdownContent";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { PageHeader } from "@/components/layout/PageHeader";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";

const PAGE_SIZE = 24;

interface CatResp {
  items: WorkflowCategory[];
}
interface FavIds {
  ids: string[];
}

interface WorkflowRunResult {
  results: Record<string, string>;
  order: string[];
  node_names: Record<string, string>;
}

export function WorkflowsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [favMode, setFavMode] = useState(false);
  const [selected, setSelected] = useState<Workflow | null>(null);
  const [runResult, setRunResult] = useState<{ name: string; data: WorkflowRunResult } | null>(
    null,
  );

  const runMut = useMutation({
    mutationFn: (id: string) =>
      apiClient.post<{ data: WorkflowRunResult }>(`/workflows/${id}/run`),
    onSuccess: (res, id) => {
      const wf = (listQ.data?.items ?? []).find((w) => w.id === id);
      setRunResult({ name: wf?.name ?? "工作流", data: res.data });
      void qc.invalidateQueries({ queryKey: ["workflows"] });
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "运行失败，请检查工作流"),
  });

  const catsQ = useQuery({
    queryKey: ["workflows", "categories"],
    queryFn: () => apiClient.get<CatResp>("/workflows/categories"),
    staleTime: 5 * 60_000,
  });
  const favIdsQ = useQuery({
    queryKey: ["workflows", "fav-ids"],
    queryFn: () => apiClient.get<FavIds>("/workflows/mine/favorite-ids"),
  });
  const favSet = useMemo(() => new Set(favIdsQ.data?.ids ?? []), [favIdsQ.data]);

  const listQ = useQuery({
    queryKey: ["workflows", "list", { search, fav: favMode }],
    queryFn: () => {
      const params = new URLSearchParams({ page: "1", page_size: String(PAGE_SIZE) });
      if (search) params.set("search", search);
      return apiClient.get<Paginated<Workflow>>(
        favMode ? `/workflows/mine/favorites?${params}` : `/workflows/?${params}`,
      );
    },
  });

  const favMut = useMutation({
    mutationFn: (id: string) => apiClient.post(`/workflows/${id}/favorite`),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["workflows", "fav-ids"] });
      void qc.invalidateQueries({ queryKey: ["workflows", "list"] });
    },
  });

  const items = listQ.data?.items ?? [];
  const total = listQ.data?.total ?? 0;
  const catNames = useMemo(
    () => new Map((catsQ.data?.items ?? []).map((c) => [c.id, c.name])),
    [catsQ.data],
  );

  return (
    <div>
      <PageHeader
        title="工作流库"
        description={total > 0 ? `共 ${total} 个工作流` : "管理多步骤创作工作流"}
        actions={
          <Button size="sm" onClick={() => navigate("/workflows/new")}>
            <Plus className="h-4 w-4" aria-hidden />
            新建
          </Button>
        }
      >
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            setSearch(searchInput.trim());
            setFavMode(false);
          }}
          className="relative max-w-md flex-1"
        >
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索工作流名称…"
            className="pl-9"
            aria-label="搜索工作流"
          />
        </form>
        <Button
          variant={favMode ? "primary" : "outline"}
          size="sm"
          onClick={() => setFavMode((v) => !v)}
        >
          <Heart className={cn("h-4 w-4", favMode && "fill-current")} aria-hidden />
          收藏
        </Button>
      </PageHeader>
      <div className="space-y-4 p-4 md:p-6">
        {listQ.isPending ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : listQ.isError ? (
          <ErrorState error={listQ.error} onRetry={() => void listQ.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            title={favMode ? "还没有收藏" : "暂无工作流"}
            description={favMode ? "点 ♥ 收藏常用工作流。" : "点击右上角「新建」创建一个。"}
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {items.map((w) => (
              <article
                key={w.id}
                className="flex flex-col gap-2 rounded-xl border border-border bg-surface-raised p-4 transition-colors hover:border-border-strong"
              >
                <div className="flex items-start justify-between gap-2">
                  <button onClick={() => setSelected(w)} className="min-w-0 flex-1 text-left">
                    <p className="truncate text-sm font-semibold text-foreground">{w.name}</p>
                    <p className="line-clamp-2 text-xs text-muted-foreground">
                      {w.description || "暂无描述"}
                    </p>
                  </button>
                  <button
                    onClick={() => favMut.mutate(w.id)}
                    aria-pressed={favSet.has(w.id)}
                    aria-label={favSet.has(w.id) ? "取消收藏" : "收藏"}
                    className="grid h-8 w-8 flex-none place-items-center rounded-lg border border-border text-muted-foreground hover:text-danger"
                  >
                    <Heart
                      className={cn("h-4 w-4", favSet.has(w.id) && "fill-danger text-danger")}
                      aria-hidden
                    />
                  </button>
                  <button
                    onClick={() => runMut.mutate(w.id)}
                    disabled={runMut.isPending}
                    aria-label={`运行 ${w.name}`}
                    title="运行工作流（按节点顺序串联生成）"
                    className="grid h-8 w-8 flex-none place-items-center rounded-lg border border-border text-muted-foreground hover:border-primary hover:text-primary-text disabled:opacity-50"
                  >
                    <Play className="h-4 w-4" aria-hidden />
                  </button>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <GitBranch className="h-3 w-3" aria-hidden />
                  <span className="truncate">{w.workflow_type}</span>
                  <span className="ml-auto rounded-full bg-secondary px-2 py-0.5">v{w.version}</span>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {selected && (
        <WorkflowDetail
          workflow={selected}
          categoryName={selected.category_id ? (catNames.get(selected.category_id) ?? "") : ""}
          favorited={favSet.has(selected.id)}
          onToggleFav={(id) => favMut.mutate(id)}
          onEdit={() => {
            navigate(`/workflows/${selected.id}/edit`);
            setSelected(null);
          }}
          onClose={() => setSelected(null)}
        />
      )}

      <Dialog
        open={runResult !== null}
        onClose={() => setRunResult(null)}
        title={`运行结果 · ${runResult?.name ?? ""}`}
        className="max-w-2xl"
      >
        {runResult && (
          <div className="flex max-h-[70dvh] flex-col gap-4 overflow-y-auto">
            {runResult.data.order.length === 0 ? (
              <p className="text-sm text-muted-foreground">工作流为空</p>
            ) : (
              runResult.data.order.map((nodeId, i) => (
                <div key={nodeId} className="rounded-xl border border-border p-3">
                  <p className="mb-1.5 flex items-center gap-2 text-sm font-medium">
                    <span className="grid h-5 w-5 place-items-center rounded-full bg-primary/12 text-xs text-primary-text">
                      {i + 1}
                    </span>
                    {runResult.data.node_names[nodeId] ?? "节点"}
                  </p>
                  <div className="max-h-48 overflow-y-auto rounded-lg bg-surface-raised p-2.5">
                    <MarkdownContent content={runResult.data.results[nodeId] ?? "（无输出）"} />
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mt-1.5"
                    onClick={() => {
                      void navigator.clipboard.writeText(runResult.data.results[nodeId] ?? "");
                      toast.success("已复制节点输出");
                    }}
                  >
                    <Copy className="h-3.5 w-3.5" aria-hidden />
                    复制
                  </Button>
                </div>
              ))
            )}
          </div>
        )}
      </Dialog>
    </div>
  );
}

function WorkflowDetail({
  workflow,
  categoryName,
  favorited,
  onToggleFav,
  onEdit,
  onClose,
}: {
  workflow: Workflow;
  categoryName: string;
  favorited: boolean;
  onToggleFav: (id: string) => void;
  onEdit: () => void;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [confirmDel, setConfirmDel] = useState(false);
  const delMut = useMutation({
    mutationFn: () => apiClient.del(`/workflows/${workflow.id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workflows", "list"] });
      onClose();
    },
  });
  const dupMut = useMutation({
    mutationFn: () => apiClient.post<Workflow>(`/workflows/${workflow.id}/duplicate`),
    onSuccess: (data) => {
      void qc.invalidateQueries({ queryKey: ["workflows", "list"] });
      onClose();
      if (data?.id) navigate(`/workflows/${data.id}/edit`);
    },
  });
  return (
    <Dialog open onClose={onClose} title={workflow.name}>
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {categoryName && (
            <span className="rounded-full bg-secondary px-2.5 py-1 text-secondary-foreground">
              {categoryName}
            </span>
          )}
          <span className="flex items-center gap-1">
            <GitBranch className="h-3 w-3" aria-hidden />
            {workflow.workflow_type}
          </span>
          <span className="rounded-full bg-secondary px-2 py-0.5">v{workflow.version}</span>
        </div>
        {workflow.description && (
          <p className="text-sm text-muted-foreground">{workflow.description}</p>
        )}
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">图（Graph）</p>
          <pre className="max-h-[40dvh] overflow-auto rounded-xl border border-border bg-surface p-3 text-xs">
            {JSON.stringify(workflow.graph, null, 2)}
          </pre>
        </div>
      </div>
      <div className="sticky bottom-0 flex gap-2 border-t border-border bg-surface-raised p-4">
        <Button
          variant="outline"
          size="icon"
          onClick={() => onToggleFav(workflow.id)}
          aria-pressed={favorited}
          aria-label={favorited ? "取消收藏" : "收藏"}
        >
          <Heart className={cn("h-4 w-4", favorited && "fill-danger text-danger")} aria-hidden />
        </Button>
        <Button
          variant="outline"
          onClick={() => dupMut.mutate()}
          loading={dupMut.isPending}
          title="复制工作流"
          aria-label="复制工作流"
        >
          <Copy className="h-4 w-4" aria-hidden />
        </Button>
        <Button variant="outline" onClick={onEdit} className="flex-1">
          编辑
        </Button>
        {confirmDel ? (
          <Button
            variant="danger"
            onClick={() => delMut.mutate()}
            loading={delMut.isPending}
            className="flex-1"
          >
            <Trash2 className="h-4 w-4" aria-hidden />
            确认删除
          </Button>
        ) : (
          <Button variant="outline" onClick={() => setConfirmDel(true)} className="flex-1">
            <Trash2 className="h-4 w-4" aria-hidden />
            删除
          </Button>
        )}
      </div>
    </Dialog>
  );
}
