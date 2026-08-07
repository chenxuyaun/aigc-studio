import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

interface LoreEntry {
  id: string;
  character_name: string | null;
  project_id: string | null;
  keywords: string[];
  content: string;
  constant: boolean;
  selective: boolean;
  position: string;
  depth: number;
  order_value: number;
  probability: number;
  enabled: boolean;
}

interface Props {
  projectId: string;
  onChanged: () => void;
}

/** 项目级世界书：条目列表 + 新增（关键词/常驻/位置/深度/概率）。 */
export function WorldPanel({ projectId, onChanged }: Props) {
  const toast = useToast();
  const [items, setItems] = useState<LoreEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    keywords: "", content: "", constant: false, position: "before", depth: 4, probability: 100,
  });

  const load = async () => {
    try {
      const r = await apiClient.get<{ items: LoreEntry[] }>(
        `/roleplay/lore?project_id=${projectId}`,
      );
      setItems(r.items);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "加载失败");
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const add = async () => {
    if (!form.keywords.trim() || !form.content.trim()) {
      toast.error("请填写关键词与内容");
      return;
    }
    setBusy(true);
    try {
      await apiClient.post("/roleplay/lore", {
        project_id: projectId,
        keywords: form.keywords.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
        content: form.content,
        constant: form.constant,
        selective: true,
        position: form.position,
        depth: form.depth,
        probability: form.probability,
        order_value: 100,
        enabled: true,
      });
      setForm({ keywords: "", content: "", constant: false, position: "before", depth: 4, probability: 100 });
      await load();
      onChanged();
      toast.success("已添加");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "添加失败");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    if (!window.confirm("删除这条世界设定？")) return;
    try {
      await apiClient.del(`/roleplay/lore/${id}`);
      await load();
      onChanged();
      toast.success("已删除");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <h3 className="text-sm font-semibold">项目世界书</h3>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        项目级世界设定：关键词命中时注入章节生成的提示词（复用世界书引擎）。
      </p>
      <div className="flex-1 space-y-2 overflow-y-auto">
        {items.length === 0 && (
          <p className="pt-6 text-center text-xs text-muted-foreground">还没有世界设定条目</p>
        )}
        {items.map((it) => (
          <div key={it.id} className="rounded-xl border border-border bg-surface p-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium">
                {it.keywords.join(" / ")}
                {it.constant && <span className="ml-1.5 rounded bg-primary/15 px-1.5 py-0.5 text-[10px] text-primary-text">常驻</span>}
              </span>
              <button className="text-xs text-danger/70 hover:text-danger" onClick={() => remove(it.id)}>
                删除
              </button>
            </div>
            <p className="mt-1.5 text-xs text-muted-foreground">{it.content}</p>
            <p className="mt-1 text-[10px] text-muted-foreground">
              位置 {it.position} · 深度 {it.depth} · 概率 {it.probability}%
            </p>
          </div>
        ))}
      </div>
      <div className="space-y-2 border-t border-border pt-3">
        <Field label="关键词（逗号分隔）">
          {({ id, describedBy }) => (
            <input
              id={id}
              aria-describedby={describedBy}
              className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
              value={form.keywords}
              onChange={(e) => setForm({ ...form, keywords: e.target.value })}
              placeholder="晨星山, 星辉"
            />
          )}
        </Field>
        <Field label="内容">
          {({ id, describedBy }) => (
            <Textarea
              id={id}
              aria-describedby={describedBy}
              rows={3}
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
            />
          )}
        </Field>
        <div className="flex items-center gap-3 text-xs">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={form.constant}
              onChange={(e) => setForm({ ...form, constant: e.target.checked })} />
            常驻
          </label>
          <label className="flex items-center gap-1.5">
            位置
            <select className="rounded border border-border bg-surface px-1 py-0.5"
              value={form.position} onChange={(e) => setForm({ ...form, position: e.target.value })}>
              <option value="before">前置</option>
              <option value="after">后置</option>
              <option value="atDepth">深度注入</option>
            </select>
          </label>
          <label className="flex items-center gap-1.5">
            深度
            <input type="number" min={1} max={20} className="w-14 rounded border border-border bg-surface px-1 py-0.5"
              value={form.depth} onChange={(e) => setForm({ ...form, depth: Number(e.target.value) })} />
          </label>
          <label className="flex items-center gap-1.5">
            概率
            <input type="number" min={1} max={100} className="w-14 rounded border border-border bg-surface px-1 py-0.5"
              value={form.probability} onChange={(e) => setForm({ ...form, probability: Number(e.target.value) })} />
          </label>
        </div>
        <Button size="sm" className="w-full" disabled={busy} onClick={add}>添加设定</Button>
      </div>
    </div>
  );
}
