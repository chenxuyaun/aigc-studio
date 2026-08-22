import { Navigate } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { useAuthStore } from "@/stores/auth";

/**
 * P3 终态（deprecation-plan.md）：provider_configs 表已删除，
 * 供应商管理唯一入口 = 模型中心（服务器内网 :8511）。本页仅作指引。
 */
export function ProvidersPage() {
  const user = useAuthStore((s) => s.user);
  const isAdmin = user?.role === "admin";

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  return (
    <div>
      <PageHeader
        title="模型 / Provider 配置"
        description="本页已退役：供应商管理已全面迁移至模型中心"
      />
      <div className="space-y-4 p-4 md:p-6">
        <div className="rounded-xl border border-border bg-surface p-4" role="note">
          <p className="text-sm font-semibold">🚚 供应商管理已迁移至「模型中心」</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-muted-foreground">
            <li>供应商新增 / 编辑 / 删除、按能力槽位切换、故障转移链、模型管理：全部在模型中心操作（服务器内网 :8511）</li>
            <li>对话 / 生图 / 语音等生成链路已只认模型中心的槽位候选链</li>
            <li>本页对应的旧数据库配置表已删除；如遇模型中心不可用，文本将回退到服务器 .env 兜底通道</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
