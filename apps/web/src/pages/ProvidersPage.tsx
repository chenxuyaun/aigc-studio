import { useCallback, useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Server, Trash2 } from "lucide-react";
import { Navigate } from "react-router-dom";

import type { ProviderAdminRow } from "@aigc/shared-types";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input } from "@/components/ui/Field";
import { ListSkeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { AppError, apiClient } from "@/lib/apiClient";
import { useAuthStore } from "@/stores/auth";


interface FormState {
  name: string;
  provider_type: string;
  base_url: string;
  default_model: string;
  api_key: string;
  is_enabled: boolean;
  priority: number;
  timeout_seconds: number;
}

const EMPTY: FormState = {
  name: "",
  provider_type: "openai_compatible",
  base_url: "",
  default_model: "",
  api_key: "",
  is_enabled: true,
  priority: 10,
  timeout_seconds: 60,
};

const PRESETS: Array<{ label: string; patch: Partial<FormState> }> = [
  {
    label: "Grok 4.5 代理 :8090",
    patch: {
      name: "Grok 4.5",
      provider_type: "openai_compatible",
      base_url: "http://127.0.0.1:8090/v1",
      default_model: "grok-4.5",
      api_key: "none",
      priority: 5,
    },
  },
  {
    label: "Grok2API :8000",
    patch: {
      name: "Grok2API",
      provider_type: "openai_compatible",
      base_url: "http://127.0.0.1:8000/v1",
      default_model: "grok-chat-fast",
      api_key: "",
      priority: 10,
    },
  },
];

export function ProvidersPage() {
  const user = useAuthStore((s) => s.user);
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<ProviderAdminRow | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [formError, setFormError] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<ProviderAdminRow | null>(null);

  const isAdmin = user?.role === "admin";
  const closeDialog = useCallback(() => {
    setOpen(false);
    setEditing(null);
    setFormError(null);
  }, []);

  const query = useQuery({
    queryKey: ["providers", "admin"],
    queryFn: () => apiClient.get<ProviderAdminRow[]>("/providers/admin"),
    enabled: isAdmin,
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (editing) {
        const body: Record<string, unknown> = {
          name: form.name.trim(),
          provider_type: form.provider_type.trim(),
          base_url: form.base_url.trim(),
          default_model: form.default_model.trim(),
          is_enabled: form.is_enabled,
          priority: form.priority,
          timeout_seconds: form.timeout_seconds,
        };
        if (form.api_key.trim()) body.api_key = form.api_key.trim();
        return apiClient.put<ProviderAdminRow>(`/providers/${editing.id}`, body);
      }
      return apiClient.post<ProviderAdminRow>("/providers/", {
        name: form.name.trim(),
        provider_type: form.provider_type.trim() || "openai_compatible",
        base_url: form.base_url.trim(),
        default_model: form.default_model.trim(),
        api_key: form.api_key.trim(),
        is_enabled: form.is_enabled,
        priority: form.priority,
        timeout_seconds: form.timeout_seconds,
      });
    },
    onSuccess: () => {
      setOpen(false);
      setEditing(null);
      setForm(EMPTY);
      setFormError(null);
      void qc.invalidateQueries({ queryKey: ["providers"] });
    },
    onError: (err) => {
      setFormError(err instanceof AppError ? err.message : "保存失败");
    },
  });

  const importEnvMutation = useMutation({
    mutationFn: () => apiClient.post<ProviderAdminRow>("/providers/import-env"),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["providers"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.del(`/providers/${id}`),
    onSuccess: () => {
      setToDelete(null);
      void qc.invalidateQueries({ queryKey: ["providers"] });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: (row: ProviderAdminRow) =>
      apiClient.put<ProviderAdminRow>(`/providers/${row.id}`, {
        is_enabled: !row.is_enabled,
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["providers"] }),
  });

  const rows = useMemo(() => query.data ?? [], [query.data]);

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  function openCreate(preset?: Partial<FormState>) {
    setEditing(null);
    setForm({ ...EMPTY, ...preset });
    setFormError(null);
    setOpen(true);
  }

  function openEdit(row: ProviderAdminRow) {
    setEditing(row);
    setForm({
      name: row.name,
      provider_type: row.provider_type,
      base_url: row.base_url,
      default_model: row.default_model,
      api_key: "",
      is_enabled: row.is_enabled,
      priority: row.priority,
      timeout_seconds: row.timeout_seconds ?? 60,
    });
    setFormError(null);
    setOpen(true);
  }

  return (
    <div>
      <PageHeader
        title="模型 / Provider 配置"
        description="写入数据库，文本生成会优先读这里；密钥只存服务端，列表不回传明文"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              loading={importEnvMutation.isPending}
              onClick={() => importEnvMutation.mutate()}
            >
              <RefreshCw className="h-4 w-4" aria-hidden />
              从 .env 导入
            </Button>
            <Button size="sm" onClick={() => openCreate()}>
              <Plus className="h-4 w-4" aria-hidden />
              新建
            </Button>
          </div>
        }
      />

      <div className="space-y-4 p-4 md:p-6">
        <Card className="flex flex-wrap gap-2 p-3">
          <span className="w-full text-xs text-muted-foreground sm:w-auto sm:self-center">
            快捷预设（仍可再改）：
          </span>
          {PRESETS.map((p) => (
            <Button key={p.label} variant="outline" size="sm" onClick={() => openCreate(p.patch)}>
              {p.label}
            </Button>
          ))}
        </Card>

        {importEnvMutation.isError && (
          <p className="text-sm text-danger" role="alert">
            {importEnvMutation.error instanceof AppError
              ? importEnvMutation.error.message
              : "导入失败"}
          </p>
        )}

        {query.isPending ? (
          <ListSkeleton />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            title="还没有 Provider"
            description="点「从 .env 导入」或用预设创建 Grok 配置。"
            action={
              <Button onClick={() => openCreate(PRESETS[0]?.patch)}>添加 Grok 4.5</Button>
            }
          />
        ) : (
          <ul className="space-y-2">
            {rows.map((row) => (
              <Card key={row.id} className="flex flex-wrap items-start justify-between gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Server className="h-4 w-4 text-primary" aria-hidden />
                    <span className="font-semibold">{row.name}</span>
                    <span
                      className={
                        row.is_enabled
                          ? "rounded-full bg-primary/12 px-2 py-0.5 text-[11px] text-primary"
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
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => toggleMutation.mutate(row)}
                    loading={toggleMutation.isPending}
                  >
                    {row.is_enabled ? "停用" : "启用"}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => openEdit(row)}>
                    编辑
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-danger"
                    onClick={() => setToDelete(row)}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </Button>
                </div>
              </Card>
            ))}
          </ul>
        )}
      </div>

      {open && (
        <Dialog
          open
          onClose={closeDialog}
          title={editing ? "编辑 Provider" : "新建 Provider"}
        >
          <form
            className="space-y-3 p-4"
            onSubmit={(e) => {
              e.preventDefault();
              if (!form.name.trim() || !form.base_url.trim()) {
                setFormError("名称与 Base URL 必填");
                return;
              }
              saveMutation.mutate();
            }}
          >
            <Field label="显示名称" required>
              {({ id }) => (
                <Input
                  id={id}
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Grok 4.5"
                />
              )}
            </Field>
            <Field label="类型">
              {({ id }) => (
                <select
                  id={id}
                  value={form.provider_type}
                  onChange={(e) => setForm((f) => ({ ...f, provider_type: e.target.value }))}
                  className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm"
                >
                  <option value="openai_compatible">openai_compatible</option>
                  <option value="text">text</option>
                  <option value="image">image（预留）</option>
                </select>
              )}
            </Field>
            <Field label="Base URL" required hint="需含 /v1，例如 http://127.0.0.1:8090/v1">
              {({ id }) => (
                <Input
                  id={id}
                  value={form.base_url}
                  onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))}
                  placeholder="http://127.0.0.1:8090/v1"
                />
              )}
            </Field>
            <Field label="默认模型 ID" hint="上游 models 列表里的 id">
              {({ id }) => (
                <Input
                  id={id}
                  value={form.default_model}
                  onChange={(e) => setForm((f) => ({ ...f, default_model: e.target.value }))}
                  placeholder="grok-4.5"
                />
              )}
            </Field>
            <Field
              label="API Key"
              hint={editing ? "留空表示不修改已有密钥；免 key 可填 none" : "免 key 可填 none"}
            >
              {({ id }) => (
                <Input
                  id={id}
                  type="password"
                  autoComplete="off"
                  value={form.api_key}
                  onChange={(e) => setForm((f) => ({ ...f, api_key: e.target.value }))}
                  placeholder={editing ? "•••• 留空不改" : "none 或真实 key"}
                />
              )}
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="优先级" hint="数字越小越优先">
                {({ id }) => (
                  <Input
                    id={id}
                    type="number"
                    value={form.priority}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, priority: Number(e.target.value) || 10 }))
                    }
                  />
                )}
              </Field>
              <Field label="超时(秒)">
                {({ id }) => (
                  <Input
                    id={id}
                    type="number"
                    min={5}
                    value={form.timeout_seconds}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        timeout_seconds: Number(e.target.value) || 60,
                      }))
                    }
                  />
                )}
              </Field>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={form.is_enabled}
                onChange={(e) => setForm((f) => ({ ...f, is_enabled: e.target.checked }))}
              />
              启用
            </label>
            {formError && (
              <p className="text-sm text-danger" role="alert">
                {formError}
              </p>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="ghost" onClick={closeDialog}>
                取消
              </Button>
              <Button type="submit" loading={saveMutation.isPending}>
                保存
              </Button>
            </div>
          </form>
        </Dialog>
      )}

      <ConfirmDialog
        open={toDelete !== null}
        title="删除 Provider"
        description={`将删除「${toDelete?.name ?? ""}」，文本生成将不再列出它。`}
        confirmText="删除"
        loading={deleteMutation.isPending}
        onConfirm={() => toDelete && deleteMutation.mutate(toDelete.id)}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}
