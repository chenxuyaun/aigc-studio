import { useState, type FormEvent } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Plus, Search, Trash2, Wrench } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { Paginated, Skill } from "@aigc/shared-types";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { PageHeader } from "@/components/layout/PageHeader";
import { apiClient } from "@/lib/apiClient";
import { DEFAULT_MODEL } from "@/lib/constants";

const PAGE_SIZE = 24;

interface SkillForm {
  name: string;
  description: string;
  instructions: string;
  skill_type: string;
  model: string;
  inputs_schema: string;
}

const EMPTY: SkillForm = {
  name: "",
  description: "",
  instructions: "",
  skill_type: "tool",
  model: "",
  inputs_schema: "{}",
};

export function SkillsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [editing, setEditing] = useState<Skill | null>(null);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Skill | null>(null);

  const listQ = useQuery({
    queryKey: ["skills", "list", { search }],
    queryFn: () => {
      const params = new URLSearchParams({ page: "1", page_size: String(PAGE_SIZE) });
      if (search) params.set("search", search);
      return apiClient.get<Paginated<Skill>>(`/skills/?${params}`);
    },
  });

  const items = listQ.data?.items ?? [];
  const total = listQ.data?.total ?? 0;

  return (
    <div>
      <PageHeader
        title="技能库"
        description={total > 0 ? `共 ${total} 个技能，可被 Agent 与工作流引用` : "管理可复用的技能"}
        actions={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            新建
          </Button>
        }
      >
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            setSearch(searchInput.trim());
          }}
          className="relative max-w-md"
        >
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索技能名称…"
            className="pl-9"
            aria-label="搜索技能"
          />
        </form>
      </PageHeader>
      <div className="space-y-4 p-4 md:p-6">
        {listQ.isPending ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : listQ.isError ? (
          <ErrorState error={listQ.error} onRetry={() => void listQ.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState title="暂无技能" description="点击右上角「新建」创建一个。" />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {items.map((s) => (
              <article
                key={s.id}
                className="flex flex-col gap-2 rounded-xl border border-border bg-surface-raised p-4 transition-colors hover:border-border-strong"
              >
                <button onClick={() => setSelected(s)} className="min-w-0 flex-1 text-left">
                  <p className="truncate text-sm font-semibold text-foreground">{s.name}</p>
                  <p className="line-clamp-2 text-xs text-muted-foreground">
                    {s.description || "暂无描述"}
                  </p>
                </button>
                <button
                  onClick={() => navigate(`/skills/${s.id}/chat`)}
                  aria-label={`运行 ${s.name}`}
                  title="运行技能（携带技能指令对话）"
                  className="grid h-8 w-8 flex-none place-items-center rounded-lg border border-border text-muted-foreground hover:border-primary hover:text-primary-text"
                >
                  <Play className="h-4 w-4" aria-hidden />
                </button>
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Wrench className="h-3 w-3" aria-hidden />
                  <span className="truncate">{s.skill_type}</span>
                  <span className="ml-auto rounded-full bg-secondary px-2 py-0.5">
                    用 {s.use_count}
                  </span>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {selected && (
        <SkillDetail
          skill={selected}
          onEdit={() => {
            setEditing(selected);
            setSelected(null);
          }}
          onClose={() => setSelected(null)}
        />
      )}

      {(creating || editing) && (
        <SkillEditor
          skill={editing}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={() => {
            setCreating(false);
            setEditing(null);
            void qc.invalidateQueries({ queryKey: ["skills", "list"] });
          }}
        />
      )}
    </div>
  );
}

function SkillDetail({
  skill,
  onEdit,
  onClose,
}: {
  skill: Skill;
  onEdit: () => void;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [confirmDel, setConfirmDel] = useState(false);
  const delMut = useMutation({
    mutationFn: () => apiClient.del(`/skills/${skill.id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["skills", "list"] });
      onClose();
    },
  });
  return (
    <Dialog open onClose={onClose} title={skill.name}>
      <div className="space-y-4 p-5">
        {skill.description && (
          <p className="text-sm text-muted-foreground">{skill.description}</p>
        )}
        <div className="rounded-xl border border-border bg-surface p-3">
          <p className="whitespace-pre-wrap break-words font-mono-ui text-[13px] leading-relaxed text-foreground">
            {skill.instructions}
          </p>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">输入参数</p>
          <pre className="overflow-x-auto rounded-xl border border-border bg-surface p-3 text-xs">
            {JSON.stringify(skill.inputs_schema, null, 2)}
          </pre>
        </div>
      </div>
      <div className="sticky bottom-0 flex gap-2 border-t border-border bg-surface-raised p-4">
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

function SkillEditor({
  skill,
  onClose,
  onSaved,
}: {
  skill: Skill | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<SkillForm>(
    skill
      ? {
          name: skill.name,
          description: skill.description,
          instructions: skill.instructions,
          skill_type: skill.skill_type,
          model: skill.model ?? "",
          inputs_schema: JSON.stringify(skill.inputs_schema, null, 2),
        }
      : EMPTY,
  );
  const mut = useMutation({
    mutationFn: () => {
      let schema: Record<string, unknown> = {};
      try {
        schema = JSON.parse(form.inputs_schema || "{}");
      } catch {
        throw new Error("输入参数 JSON 解析失败");
      }
      const body = {
        name: form.name.trim(),
        description: form.description.trim(),
        instructions: form.instructions,
        skill_type: form.skill_type,
        model: form.model.trim(),
        inputs_schema: schema,
      };
      return skill
        ? apiClient.put(`/skills/${skill.id}`, body)
        : apiClient.post(`/skills/`, body);
    },
    onSuccess: onSaved,
  });

  return (
    <Dialog open onClose={onClose} title={skill ? "编辑技能" : "新建技能"}>
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          mut.mutate();
        }}
        className="space-y-4 p-5"
      >
        <Field label="名称" required>
          {(p) => (
            <Input
              {...p}
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          )}
        </Field>
        <Field label="描述">
          {(p) => (
            <Input
              {...p}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          )}
        </Field>
        <Field label="指令（Instructions）" required>
          {(p) => (
            <Textarea
              {...p}
              rows={8}
              value={form.instructions}
              onChange={(e) => setForm({ ...form, instructions: e.target.value })}
              required
            />
          )}
        </Field>
        <Field label="类型">
          {(p) => (
            <Input
              {...p}
              value={form.skill_type}
              onChange={(e) => setForm({ ...form, skill_type: e.target.value })}
            />
          )}
        </Field>
        <Field label="运行模型" hint="留空自动使用已启用 Provider">
          {(p) => (
            <Input
              {...p}
              value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              placeholder={`如 grok / ${DEFAULT_MODEL}`}
            />
          )}
        </Field>
        <Field label="输入参数（JSON）" hint="描述技能接受的结构化参数">
          {(p) => (
            <Textarea
              {...p}
              rows={6}
              className="font-mono"
              value={form.inputs_schema}
              onChange={(e) => setForm({ ...form, inputs_schema: e.target.value })}
            />
          )}
        </Field>
        {mut.isError && (
          <p className="text-xs text-danger">{(mut.error as Error).message}</p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" loading={mut.isPending}>
            保存
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
