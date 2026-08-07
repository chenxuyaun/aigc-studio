import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Textarea } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

import type { StoryProject } from "@aigc/shared-types";

interface RoleplayChar {
  asset_id: string;
  name?: string;
  url?: string;
}

/** 创作工作室：项目列表 + 新建向导（标题/梗概/类型/选择角色卡）。 */
export function StoryStudioPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<StoryProject[] | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [chars, setChars] = useState<RoleplayChar[]>([]);
  const [form, setForm] = useState({
    title: "", genre: "奇幻", synopsis: "",
    character_asset_ids: [] as string[],
  });

  const load = useCallback(async () => {
    try {
      const r = await apiClient.get<{ items: StoryProject[] }>("/story/projects");
      setProjects(r.items);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = async () => {
    setForm({ title: "", genre: "奇幻", synopsis: "", character_asset_ids: [] });
    setOpen(true);
    try {
      const r = await apiClient.get<{ items: RoleplayChar[] }>("/roleplay/characters");
      setChars(r.items);
    } catch {
      setChars([]);
    }
  };

  const create = async () => {
    if (!form.title.trim()) {
      toast.error("请填写书名");
      return;
    }
    setBusy(true);
    try {
      const r = await apiClient.post<{ project: StoryProject }>("/story/projects", form);
      setOpen(false);
      navigate(`/story/${r.project.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (p: StoryProject) => {
    if (!window.confirm(`删除《${p.title}》及其全部章节？`)) return;
    try {
      await apiClient.del(`/story/projects/${p.id}`);
      toast.success("已删除");
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const exportBook = async (p: StoryProject, fmt: "markdown" | "jsonl" | "epub") => {
    try {
      const blob = await apiClient.getBlob(`/story/projects/${p.id}/export?format=${fmt}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const ext = fmt === "markdown" ? "md" : fmt === "epub" ? "epub" : "jsonl";
      a.href = url;
      a.download = `${p.title}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "导出失败");
    }
  };

  const toggleChar = (id: string) => {
    setForm((f) => ({
      ...f,
      character_asset_ids: f.character_asset_ids.includes(id)
        ? f.character_asset_ids.filter((x) => x !== id)
        : [...f.character_asset_ids, id],
    }));
  };

  if (error) return <ErrorState error={error} onRetry={() => void load()} />;
  if (projects === null) return <LoadingState />;

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <PageHeader
        title="创作工作室"
        description="以角色扮演的方式创作小说与剧本：设定即角色卡，章节由扮演引擎驱动，团队与连载自动推进"
        actions={
          <Button onClick={() => void openCreate()}>+ 新建创作项目</Button>
        }
      />

      {projects.length === 0 ? (
        <EmptyState
          title="还没有创作项目"
          description="新建一本书：选择角色卡（或稍后添加），生成大纲，然后逐章创作"
          action={<Button onClick={() => void openCreate()}>开始创作</Button>}
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <div key={p.id} className="flex flex-col rounded-2xl border border-border bg-surface p-4 shadow-soft">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="truncate text-base font-semibold">{p.title}</h3>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {p.genre || "未分类"} · {p.status === "completed" ? "已完成" : p.status === "ongoing" ? "连载中" : "构思中"}
                  </p>
                </div>
                <button onClick={() => remove(p)} className="text-xs text-danger/70 hover:text-danger">
                  删除
                </button>
              </div>
              {p.synopsis && (
                <p className="mt-2 line-clamp-3 flex-1 text-sm text-muted-foreground">{p.synopsis}</p>
              )}
              <p className="mt-2 text-xs text-muted-foreground">
                {p.chapter_count ?? 0} 章 · {(p.total_words ?? 0).toLocaleString()} 字
              </p>
              <div className="mt-3 flex items-center gap-2">
                <Button size="sm" className="flex-1" onClick={() => navigate(`/story/${p.id}`)}>
                  进入创作
                </Button>
                <Button size="sm" variant="outline" onClick={() => void exportBook(p, "markdown")}>MD</Button>
                <Button size="sm" variant="outline" onClick={() => void exportBook(p, "jsonl")}>JSONL</Button>
                <Button size="sm" variant="outline" onClick={() => void exportBook(p, "epub")}>EPUB</Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Dialog open={open} onClose={() => setOpen(false)} title="新建创作项目">
        <div className="space-y-3">
          <Field label="书名">
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
                value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })}
                placeholder="《晨星山物语》"
              />
            )}
          </Field>
          <Field label="类型">
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
                value={form.genre}
                onChange={(e) => setForm({ ...form, genre: e.target.value })}
              />
            )}
          </Field>
          <Field label="故事梗概">
            {({ id, describedBy }) => (
              <Textarea
                id={id}
                aria-describedby={describedBy}
                rows={3}
                value={form.synopsis}
                onChange={(e) => setForm({ ...form, synopsis: e.target.value })}
                placeholder="一句话或一段话描述这个故事"
              />
            )}
          </Field>
          <Field label={`选择角色卡（已选 ${form.character_asset_ids.length}）`}>
            {({ id, describedBy }) => (
              <div id={id} aria-describedby={describedBy} className="flex max-h-40 flex-wrap gap-2 overflow-y-auto rounded-lg border border-border p-2">
                {chars.length === 0 && (
                  <p className="text-xs text-muted-foreground">素材库暂无角色卡，可稍后在项目中添加</p>
                )}
                {chars.map((c) => (
                  <button
                    key={c.asset_id}
                    onClick={() => toggleChar(c.asset_id)}
                    className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                      form.character_asset_ids.includes(c.asset_id)
                        ? "border-primary bg-primary/15 text-primary-text"
                        : "border-border bg-surface text-muted-foreground hover:border-border-strong"
                    }`}
                  >
                    {c.name || c.asset_id.slice(0, 8)}
                  </button>
                ))}
              </div>
            )}
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>取消</Button>
            <Button disabled={busy} onClick={() => void create()}>创建并进入</Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
