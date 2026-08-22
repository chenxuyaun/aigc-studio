import { useQuery } from "@tanstack/react-query";
import { Server } from "lucide-react";
import { Navigate } from "react-router-dom";

import type { ProviderAdminRow } from "@aigc/shared-types";

import { PageHeader } from "@/components/layout/PageHeader";
import { Card } from "@/components/ui/Card";
import { ListSkeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { apiClient } from "@/lib/apiClient";
import { useAuthStore } from "@/stores/auth";

/**
 * P2 只读页（deprecation-plan.md）：供应商管理已迁移至模型中心（服务器 :8511）。
 * 本页仅展示 DB 应急回退配置（只读），写操作已在后端 410 下线。
 */
export function ProvidersPage() {
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.role === "admin";

  const query = useQuery({
    queryKey: ["providers", "admin"],
    queryFn: () => apiClient.get<ProviderAdminRow[]>("/providers/admin"),
    enabled: isAdmin,
  });

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  const rows = query.data ?? [];

  return (
    <div>
      <PageHeader
        title="模型 / Provider 配置"
        description="应急回退通道（只读）：仅当模型中心不可用时才会启用；日常管理请使用模型中心（服务器 :8511）"
      />

      <div className="space-y-4 p-4 md:p-6">
        <div className="rounded-xl border border-border bg-surface p-4" role="note">
          <p className="text-sm font-semibold">🚚 供应商管理已迁移至「模型中心」</p>
          <p className="mt-1 text-xs text-muted-foreground">
            日常切换、故障转移链、模型管理请在模型中心操作；本页为应急回退的只读快照，
            新增 / 编辑 / 删除已下线。
          </p>
        </div>

        {query.isPending ? (
          <ListSkeleton />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            title="没有应急回退配置"
            description="所有供应商均由模型中心管理。"
          />
        ) : (
          <ul className="space-y-2">
            {rows.map((row) => (
              <Card key={row.id} className="flex flex-wrap items-start justify-between gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Server className="h-4 w-4 text-primary-text" aria-hidden />
                    <span className="font-semibold">{row.name}</span>
                    <span
                      className={
                        row.is_enabled
                          ? "rounded-full bg-primary/12 px-2 py-0.5 text-[11px] text-primary-text"
                          : "rounded-full bg-muted px-2 py-0.5 text-[11px] text-muted-foreground"
                      }
                    >
                      {row.is_enabled ? "启用" : "停用"}
                    </span>
                    <span className="text-xs text-muted-foreground">{row.provider_type}</span>
                  </div>
                  <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                    {row.base_url || "（无 base_url）"}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    模型 <span className="font-mono">{row.default_model || "—"}</span>
                    {" · "}优先级 {row.priority}
                    {" · "}
                    {row.has_api_key
                      ? `密钥已配置 (${row.api_key_fingerprint || "****"})`
                      : "未配置密钥"}
                  </p>
                </div>
              </Card>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
