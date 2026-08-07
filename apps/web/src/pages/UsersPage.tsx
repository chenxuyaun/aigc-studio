import { useState, type FormEvent } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, ShieldCheck, UserRound, UserRoundX } from "lucide-react";

import type { UserRow } from "@aigc/shared-types";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

interface UserCreateForm {
  username: string;
  email: string;
  password: string;
  role: "user" | "admin";
}

const EMPTY: UserCreateForm = { username: "", email: "", password: "", role: "user" };

export function UsersPage() {
  const toast = useToast();
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<UserCreateForm>(EMPTY);

  const users = useQuery({
    queryKey: ["users"],
    queryFn: () => apiClient.get<UserRow[]>("/users/"),
  });

  const createUser = useMutation({
    mutationFn: () =>
      apiClient.post<UserRow>("/users/", {
        username: form.username.trim(),
        email: form.email.trim(),
        password: form.password,
        role: form.role,
      }),
    onSuccess: (u) => {
      toast.success(`已创建用户 ${u.username}`);
      setCreating(false);
      setForm(EMPTY);
      void qc.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "创建失败，请重试"),
  });

  const toggleActive = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      apiClient.put<UserRow>(`/users/${id}`, { is_active }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["users"] }),
    onError: (err) => toast.error(err instanceof Error ? err.message : "操作失败，请重试"),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!form.username.trim() || !form.password) {
      toast.error("用户名和密码不能为空");
      return;
    }
    createUser.mutate();
  }

  return (
    <div>
      <PageHeader
        title="用户管理"
        description="创建/停用账号（登录后各用户数据相互隔离）"
        actions={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            新建用户
          </Button>
        }
      />
      <div className="p-4 md:p-6">
        <div className="rounded-[var(--radius-card)] border border-border bg-surface">
          {users.isLoading ? (
            <p className="p-6 text-center text-sm text-muted-foreground">加载中…</p>
          ) : (
            <ul className="divide-y divide-border">
              {(users.data ?? []).map((u) => (
                <li key={u.id} className="flex items-center gap-3 px-4 py-3">
                  <span className="grid h-9 w-9 flex-none place-items-center rounded-full bg-primary/12 text-primary">
                    {u.role === "admin" ? (
                      <ShieldCheck className="h-4 w-4" aria-hidden />
                    ) : (
                      <UserRound className="h-4 w-4" aria-hidden />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-2 text-sm font-medium">
                      {u.username}
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] ${
                          u.is_active ? "bg-success/10 text-success" : "bg-danger/10 text-danger"
                        }`}
                      >
                        {u.is_active ? "正常" : "已停用"}
                      </span>
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {u.email} · {u.role === "admin" ? "管理员" : "普通用户"}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={u.username === "admin"}
                    title={u.username === "admin" ? "内置管理员不可停用" : undefined}
                    onClick={() => toggleActive.mutate({ id: u.id, is_active: !u.is_active })}
                  >
                    {u.is_active ? (
                      <UserRoundX className="h-4 w-4 text-danger" aria-hidden />
                    ) : (
                      <UserRound className="h-4 w-4" aria-hidden />
                    )}
                    {u.is_active ? "停用" : "启用"}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <Dialog open={creating} onClose={() => setCreating(false)} title="新建用户">
        <form onSubmit={submit} className="flex flex-col gap-4">
          <Field label="用户名" required>
            {({ id }) => (
              <Input
                id={id}
                value={form.username}
                onChange={(e) => setForm({ ...form, username: e.target.value })}
                placeholder="登录用户名"
                maxLength={50}
              />
            )}
          </Field>
          <Field label="邮箱" required>
            {({ id }) => (
              <Input
                id={id}
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="user@example.com"
              />
            )}
          </Field>
          <Field label="初始密码" required hint="创建后请提醒用户尽快修改">
            {({ id }) => (
              <Input
                id={id}
                type="text"
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="至少 6 位"
                minLength={6}
              />
            )}
          </Field>
          <Field label="角色">
            {({ id }) => (
              <select
                id={id}
                value={form.role}
                onChange={(e) =>
                  setForm({ ...form, role: e.target.value as "user" | "admin" })
                }
                className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm"
              >
                <option value="user">普通用户</option>
                <option value="admin">管理员</option>
              </select>
            )}
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setCreating(false)}>
              取消
            </Button>
            <Button type="submit" loading={createUser.isPending}>
              创建
            </Button>
          </div>
        </form>
      </Dialog>
    </div>
  );
}
