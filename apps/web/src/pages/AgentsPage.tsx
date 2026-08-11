import { useMemo, useState, type FormEvent } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Heart, Play, Plus, Search, Sparkles, Trash2, Wrench } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import type { Agent, AgentCategory, Paginated } from "@aigc/shared-types";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { PageHeader } from "@/components/layout/PageHeader";
import { AgentDirectoryPage } from "@/pages/AgentDirectoryPage";
import { SkillsPage } from "@/pages/SkillsPage";
import { WorkflowsPage } from "@/pages/WorkflowsPage";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";

const PAGE_SIZE = 24;

interface CatResp {
  items: AgentCategory[];
}
interface FavIds {
  ids: string[];
}

interface AgentForm {
  name: string;
  description: string;
  system_prompt: string;
  agent_type: string;
  model: string;
  tools: string;
}

const EMPTY: AgentForm = {
  name: "",
  description: "",
  system_prompt: "",
  agent_type: "generic",
  model: "",
  tools: "",
};

export function AgentsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [favMode, setFavMode] = useState(false);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Agent | null>(null);
  const [section, setSection] = useState<"agents" | "skills" | "workflows" | "directory">("agents");

  const catsQ = useQuery({
    queryKey: ["agents", "categories"],
    queryFn: () => apiClient.get<CatResp>("/agents/categories"),
    staleTime: 5 * 60_000,
  });
  const favIdsQ = useQuery({
    queryKey: ["agents", "fav-ids"],
    queryFn: () => apiClient.get<FavIds>("/agents/mine/favorite-ids"),
  });
  const favSet = useMemo(() => new Set(favIdsQ.data?.ids ?? []), [favIdsQ.data]);

  const listQ = useQuery({
    queryKey: ["agents", "list", { search, fav: favMode }],
    queryFn: () => {
      const params = new URLSearchParams({ page: "1", page_size: String(PAGE_SIZE) });
      if (search) params.set("search", search);
      return apiClient.get<Paginated<Agent>>(
        favMode ? `/agents/mine/favorites?${params}` : `/agents/?${params}`,
      );
    },
  });

  const favMut = useMutation({
    mutationFn: (id: string) => apiClient.post(`/agents/${id}/favorite`),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["agents", "fav-ids"] });
      void qc.invalidateQueries({ queryKey: ["agents", "list"] });
    },
  });

  // Mission 现场角色转正：临时 Agent → 正式 Agent（进入长期团队）
  const promoteMut = useMutation({
    mutationFn: (id: string) => apiClient.post<Agent>(`/agents/${id}/promote`, {}),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["agents", "list"] });
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
        title="Agent 库"
        description={total > 0 ? `共 ${total} 个 Agent，可收藏与复用` : "管理可复用的 AI Agent"}
        actions={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            新建
          </Button>
        }
      >
        {/* 同级功能入口：技能库 / 工作流 / Agent 目录（原孤儿路由，补导航） */}
        <div className="mb-3 flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">关联：</span>
          <Link
            to="/skills"
            className="rounded-full border border-border px-2.5 py-1 text-muted-foreground hover:border-primary hover:text-foreground"
          >
            🧩 技能库
          </Link>
          <Link
            to="/workflows"
            className="rounded-full border border-border px-2.5 py-1 text-muted-foreground hover:border-primary hover:text-foreground"
          >
            🔀 工作流
          </Link>
          <Link
            to="/agent-directory"
            className="rounded-full border border-border px-2.5 py-1 text-muted-foreground hover:border-primary hover:text-foreground"
          >
            📁 Agent 目录
          </Link>
        </div>
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
            placeholder="搜索 Agent 名称…"
            className="pl-9"
            aria-label="搜索 Agent"
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
      <div className="flex gap-1 border-b px-4">
        {(
          [
            ["agents", "我的 Agent"],
            ["skills", "技能库"],
            ["workflows", "工作流"],
            ["directory", "外部目录"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            className={`border-b-2 px-4 py-2 text-sm ${
              section === k ? "border-primary font-medium" : "border-transparent text-muted-foreground"
            }`}
            onClick={() => setSection(k)}
          >
            {label}
          </button>
        ))}
      </div>
      {section !== "agents" && (
        <div className="p-4 md:p-6">
          {section === "skills" ? (
            <SkillsPage />
          ) : section === "workflows" ? (
            <WorkflowsPage />
          ) : (
            <AgentDirectoryPage />
          )}
        </div>
      )}
      <div className={section === "agents" ? "space-y-4 p-4 md:p-6" : "hidden"}>
        {listQ.isPending ? (
          <p className="text-sm text-muted-foreground">加载中…</p>
        ) : listQ.isError ? (
          <ErrorState error={listQ.error} onRetry={() => void listQ.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            title={favMode ? "还没有收藏" : "暂无 Agent"}
            description={favMode ? "点 ♥ 收藏常用的 Agent。" : "点击右上角「新建」创建一个。"}
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {items.map((a) => (
              <article
                key={a.id}
                className="flex flex-col gap-2 rounded-xl border border-border bg-surface-raised p-4 transition-colors hover:border-border-strong"
              >
                <div className="flex items-start justify-between gap-2">
                  <button
                    onClick={() => setSelected(a)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <p className="truncate text-sm font-semibold text-foreground">{a.name}</p>
                    <p className="line-clamp-2 text-xs text-muted-foreground">
                      {a.description || "暂无描述"}
                    </p>
                  </button>
                  <button
                    onClick={() => favMut.mutate(a.id)}
                    aria-pressed={favSet.has(a.id)}
                    aria-label={favSet.has(a.id) ? "取消收藏" : "收藏"}
                    className="grid h-8 w-8 flex-none place-items-center rounded-lg border border-border text-muted-foreground hover:text-danger"
                  >
                    <Heart
                      className={cn("h-4 w-4", favSet.has(a.id) && "fill-danger text-danger")}
                      aria-hidden
                    />
                  </button>
                  <button
                    onClick={() => navigate(`/agents/${a.id}/chat`)}
                    aria-label={`运行 ${a.name}`}
                    title={`运行 ${a.name}`}
                    className="grid h-8 w-8 flex-none place-items-center rounded-lg border border-border text-muted-foreground hover:border-primary hover:text-primary-text"
                  >
                    <Play className="h-4 w-4" aria-hidden />
                  </button>
                </div>
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Wrench className="h-3 w-3" aria-hidden />
                  <span className="truncate">{a.model || "默认模型"}</span>
                  {a.source_type === "mission" ? (
                    <>
                      <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-amber-600">
                        🤖 Mission 角色
                      </span>
                      <button
                        onClick={() => promoteMut.mutate(a.id)}
                        title="转正为正式 Agent（进入你的长期团队，可被后续任务复用）"
                        className="ml-auto rounded-full border border-border px-2 py-0.5 hover:border-primary hover:text-primary-text"
                      >
                        转正
                      </button>
                    </>
                  ) : (
                    <span className="ml-auto rounded-full bg-secondary px-2 py-0.5">
                      {a.agent_type}
                    </span>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      {selected && (
        <AgentDetail
          agent={selected}
          categoryName={selected.category_id ? (catNames.get(selected.category_id) ?? "") : ""}
          favorited={favSet.has(selected.id)}
          onToggleFav={(id) => favMut.mutate(id)}
          onEdit={() => {
            setEditing(selected);
            setSelected(null);
          }}
          onClose={() => setSelected(null)}
        />
      )}

      {(creating || editing) && (
        <AgentEditor
          agent={editing}
          onClose={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={() => {
            setCreating(false);
            setEditing(null);
            void qc.invalidateQueries({ queryKey: ["agents", "list"] });
          }}
        />
      )}
    </div>
  );
}

function AgentDetail({
  agent,
  categoryName,
  favorited,
  onToggleFav,
  onEdit,
  onClose,
}: {
  agent: Agent;
  categoryName: string;
  favorited: boolean;
  onToggleFav: (id: string) => void;
  onEdit: () => void;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [confirmDel, setConfirmDel] = useState(false);
  const delMut = useMutation({
    mutationFn: () => apiClient.del(`/agents/${agent.id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["agents", "list"] });
      onClose();
    },
  });
  return (
    <Dialog open onClose={onClose} title={agent.name}>
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {categoryName && (
            <span className="rounded-full bg-secondary px-2.5 py-1 text-secondary-foreground">
              {categoryName}
            </span>
          )}
          {agent.model && (
            <span className="flex items-center gap-1">
              <Sparkles className="h-3 w-3" aria-hidden />
              {agent.model}
            </span>
          )}
        </div>
        {agent.description && (
          <p className="text-sm text-muted-foreground">{agent.description}</p>
        )}
        <div className="rounded-xl border border-border bg-surface p-3">
          <p className="whitespace-pre-wrap break-words font-mono-ui text-[13px] leading-relaxed text-foreground">
            {agent.system_prompt}
          </p>
        </div>
        {agent.tools.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {agent.tools.map((t) => (
              <span key={t} className="rounded-full bg-secondary px-2.5 py-1 text-xs">
                {t}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="sticky bottom-0 flex gap-2 border-t border-border bg-surface-raised p-4">
        <Button
          variant="outline"
          size="icon"
          onClick={() => onToggleFav(agent.id)}
          aria-pressed={favorited}
          aria-label={favorited ? "取消收藏" : "收藏"}
        >
          <Heart className={cn("h-4 w-4", favorited && "fill-danger text-danger")} aria-hidden />
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

function AgentEditor({
  agent,
  onClose,
  onSaved,
}: {
  agent: Agent | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<AgentForm>(
    agent
      ? {
          name: agent.name,
          description: agent.description,
          system_prompt: agent.system_prompt,
          agent_type: agent.agent_type,
          model: agent.model,
          tools: agent.tools.join(", "),
        }
      : EMPTY,
  );
  const mut = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name.trim(),
        description: form.description.trim(),
        system_prompt: form.system_prompt,
        agent_type: form.agent_type,
        model: form.model.trim(),
        tools: form.tools
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      };
      return agent
        ? apiClient.put(`/agents/${agent.id}`, body)
        : apiClient.post(`/agents/`, body);
    },
    onSuccess: onSaved,
  });

  return (
    <Dialog open onClose={onClose} title={agent ? "编辑 Agent" : "新建 Agent"}>
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
              placeholder="一句话说明这个 Agent 的用途"
            />
          )}
        </Field>
        <Field label="系统提示词" required>
          {(p) => (
            <Textarea
              {...p}
              rows={8}
              value={form.system_prompt}
              onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
              required
            />
          )}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="类型">
            {(p) => (
              <Input
                {...p}
                value={form.agent_type}
                onChange={(e) => setForm({ ...form, agent_type: e.target.value })}
              />
            )}
          </Field>
          <Field label="模型">
            {(p) => (
              <Input
                {...p}
                value={form.model}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
                placeholder="留空用默认"
              />
            )}
          </Field>
        </div>
        <Field label="工具（逗号分隔）">
          {(p) => (
            <Input
              {...p}
              value={form.tools}
              onChange={(e) => setForm({ ...form, tools: e.target.value })}
              placeholder="search, calc"
            />
          )}
        </Field>
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
