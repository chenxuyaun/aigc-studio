import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Textarea } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

import type { CrewStage, StoryCharacter } from "@aigc/shared-types";

interface Props {
  projectId: string;
  characters: StoryCharacter[];
  onChanged: () => void;
}

const CREW_STAGES: { stage: CrewStage; label: string; desc: string }[] = [
  { stage: "director", label: "主编", desc: "规划下一章剧情方向" },
  { stage: "writer", label: "作家", desc: "按方向生成章节" },
  { stage: "editor", label: "校对", desc: "一致性/伏笔审校" },
  { stage: "stagehand", label: "剧务", desc: "推进角色当前状态" },
];

/** 角色实例管理 + 创作团队（crew）阶段执行。 */
export function CrewPanel({ projectId, characters, onChanged }: Props) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<StoryCharacter | null>(null);
  const [busy, setBusy] = useState("");
  const [form, setForm] = useState({
    name: "", character_asset_id: "", role: "supporting",
    description: "", goals: "", arc: "", current_state: "", skill_ids: "",
  });

  const openCreate = () => {
    setEditing(null);
    setForm({ name: "", character_asset_id: "", role: "supporting", description: "", goals: "", arc: "", current_state: "", skill_ids: "" });
    setOpen(true);
  };

  const openEdit = (c: StoryCharacter) => {
    setEditing(c);
    setForm({
      name: c.name, character_asset_id: c.character_asset_id ?? "",
      role: c.role, description: c.description, goals: c.goals,
      arc: c.arc, current_state: c.current_state, skill_ids: c.skill_ids.join(","),
    });
    setOpen(true);
  };

  const save = async () => {
    try {
      const body = { ...form, skill_ids: form.skill_ids.split(/[,，]/).map((s) => s.trim()).filter(Boolean) };
      if (editing) {
        await apiClient.put(`/story/characters/${editing.id}`, body);
      } else {
        await apiClient.post(`/story/projects/${projectId}/characters`, body);
      }
      setOpen(false);
      onChanged();
      toast.success("已保存");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    }
  };

  const remove = async (c: StoryCharacter) => {
    if (!window.confirm(`移除角色「${c.name}」？`)) return;
    try {
      await apiClient.del(`/story/characters/${c.id}`);
      onChanged();
      toast.success("已移除");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "移除失败");
    }
  };

  const runStage = async (stage: CrewStage) => {
    setBusy(stage);
    try {
      const r = await apiClient.post<Record<string, unknown>>(`/story/projects/${projectId}/crew`, {
        project_id: projectId, stage, model: "",
      });
      const stageName = CREW_STAGES.find((s) => s.stage === stage)?.label ?? stage;
      if (stage === "stagehand") {
        const states = (r.states as { character: string; current_state: string }[]) ?? [];
        toast.success(`剧务更新了 ${states.length} 个角色状态`);
        onChanged();
      } else {
        const detail = String((r.direction as string) ?? (r.review as string) ?? "").slice(0, 120);
        toast.success(`${stageName}完成${detail ? "：" + detail : ""}`);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "执行失败");
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">角色阵容</h3>
        <Button size="sm" variant="outline" onClick={openCreate}>+ 添加角色</Button>
      </div>
      <div className="flex-1 space-y-2 overflow-y-auto">
        {characters.length === 0 && (
          <p className="pt-6 text-center text-xs text-muted-foreground">
            把角色卡加入项目后在故事中的实例<br />（可补充目标/弧线/当前状态）
          </p>
        )}
        {characters.map((c) => (
          <div key={c.id} className="rounded-xl border border-border bg-surface p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">
                {c.name}
                {c.role === "protagonist" && (
                  <span className="ml-1.5 rounded bg-primary/15 px-1.5 py-0.5 text-[10px] text-primary-text">主角</span>
                )}
              </span>
              <div className="flex gap-2 text-xs">
                <button className="text-muted-foreground hover:text-foreground" onClick={() => openEdit(c)}>编辑</button>
                <button className="text-danger/70 hover:text-danger" onClick={() => remove(c)}>移除</button>
              </div>
            </div>
            {c.current_state && (
              <p className="mt-1.5 rounded-lg bg-surface-raised p-2 text-xs text-muted-foreground">
                <span className="text-foreground">当前状态：</span>{c.current_state}
              </p>
            )}
            {c.goals && <p className="mt-1 text-xs text-muted-foreground">目标：{c.goals}</p>}
          </div>
        ))}
      </div>

      <div className="border-t border-border pt-3">
        <h3 className="mb-2 text-sm font-semibold">创作团队</h3>
        <div className="grid grid-cols-2 gap-2">
          {CREW_STAGES.map((s) => (
            <Button
              key={s.stage}
              size="sm"
              variant="outline"
              disabled={busy !== ""}
              onClick={() => runStage(s.stage)}
              className="justify-start"
            >
              <span className="truncate">
                {busy === s.stage ? "执行中…" : `${s.label}：${s.desc}`}
              </span>
            </Button>
          ))}
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
          作家阶段需要先在章节编辑器中选择章节；主编输出写入剧情方向，自动注入后续章节生成。
        </p>
      </div>

      <Dialog open={open} onClose={() => setOpen(false)} title={editing ? "编辑角色" : "添加角色"}>
        <div className="space-y-3">
          <Field label="角色名">
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            )}
          </Field>
          <Field label="定位">
            {({ id, describedBy }) => (
              <select
                id={id}
                aria-describedby={describedBy}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
                value={form.role}
                onChange={(e) => setForm({ ...form, role: e.target.value })}
              >
                <option value="protagonist">主角</option>
                <option value="supporting">配角</option>
              </select>
            )}
          </Field>
          <Field label="角色卡 asset_id（留空为文字占位角色）">
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
                value={form.character_asset_id}
                onChange={(e) => setForm({ ...form, character_asset_id: e.target.value })}
              />
            )}
          </Field>
          <Field label="目标">
            {({ id, describedBy }) => (
              <Textarea
                id={id}
                aria-describedby={describedBy}
                rows={2}
                value={form.goals}
                onChange={(e) => setForm({ ...form, goals: e.target.value })}
              />
            )}
          </Field>
          <Field label="成长弧线">
            {({ id, describedBy }) => (
              <Textarea
                id={id}
                aria-describedby={describedBy}
                rows={2}
                value={form.arc}
                onChange={(e) => setForm({ ...form, arc: e.target.value })}
              />
            )}
          </Field>
          <Field label="当前状态">
            {({ id, describedBy }) => (
              <Textarea
                id={id}
                aria-describedby={describedBy}
                rows={2}
                value={form.current_state}
                onChange={(e) => setForm({ ...form, current_state: e.target.value })}
              />
            )}
          </Field>
          <Field label="技能 id（逗号分隔，技能说明会注入生成提示词）">
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
                value={form.skill_ids}
                onChange={(e) => setForm({ ...form, skill_ids: e.target.value })}
              />
            )}
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>取消</Button>
            <Button onClick={save}>保存</Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
