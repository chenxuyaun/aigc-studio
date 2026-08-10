import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

interface StyleFeature {
  name: string;
  desc: string;
  enabled: boolean;
}

interface Props {
  projectId: string;
  settings?: Record<string, unknown> | undefined;
  chapters?: { id: string; title: string; status: string }[];
  onChanged?: () => void;
}

/**
 * 写法特征池（AI-Novel 写法引擎借鉴）：从好章节提取写法特征，
 * 注入后续章节生成/修订——写法延续，质量不漂移。
 */
export function WritingStylePanel({ projectId, settings, chapters, onChanged }: Props) {
  const toast = useToast();
  const [chapterId, setChapterId] = useState("");
  const [features, setFeatures] = useState<StyleFeature[]>(
    () => (((settings?.writing_style ?? []) as StyleFeature[]) ?? []).map((f) => ({ ...f })),
  );
  const [busy, setBusy] = useState(false);

  const doneChapters = (chapters ?? []).filter((c) => c.status === "done" && c.title);

  async function extract() {
    if (!chapterId || busy) return;
    setBusy(true);
    try {
      const r = await apiClient.post<{ features: StyleFeature[] }>(
        `/story/projects/${projectId}/writing-style`,
        { chapter_id: chapterId },
      );
      setFeatures(r.features);
      toast.success("写法特征已提炼并保存（后续章节将延续这些写法）");
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "提取失败（章节正文需 ≥200 字）");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    try {
      await apiClient.put(`/story/projects/${projectId}/writing-style`, { features });
      toast.success("写法特征已保存");
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  function toggle(i: number) {
    setFeatures((prev) => prev.map((f, idx) => (idx === i ? { ...f, enabled: !f.enabled } : f)));
  }

  return (
    <div className="flex flex-col gap-3 p-3 text-xs">
      <p className="leading-relaxed text-muted-foreground">
        ✍️ 写法特征池——从<b>满意的一章</b>提炼「作者是怎么写的」（短句/白描/对话节奏…），
        后续章节生成自动延续。写法稳定，质量不漂移。
      </p>
      <Field label="从哪一章提取（需已完成且 ≥200 字）">
        {({ id }) => (
          <select
            id={id}
            value={chapterId}
            onChange={(e) => setChapterId(e.target.value)}
            className="h-9 w-full rounded-lg border border-border bg-surface px-2 text-xs outline-none focus:border-primary"
          >
            <option value="">选择章节…</option>
            {doneChapters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title || `第 ${c.id.slice(0, 6)} 章`}
              </option>
            ))}
          </select>
        )}
      </Field>
      <Button size="sm" onClick={() => void extract()} loading={busy} disabled={!chapterId}>
        🧬 提取写法特征
      </Button>

      {features.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="font-medium text-foreground">特征池（勾选 = 启用注入）</p>
          {features.map((f, i) => (
            <label
              key={i}
              className="flex items-start gap-2 rounded-lg border border-border bg-surface px-3 py-2"
            >
              <input
                type="checkbox"
                checked={f.enabled}
                onChange={() => toggle(i)}
                className="mt-0.5 h-3.5 w-3.5 accent-[var(--primary)]"
              />
              <span className="min-w-0">
                <span className="block font-medium">{f.name}</span>
                <span className="block text-muted-foreground">{f.desc}</span>
              </span>
            </label>
          ))}
          <Button size="sm" variant="outline" className="self-end" onClick={() => void save()}>
            保存启停
          </Button>
        </div>
      )}
      {features.length === 0 && (
        <p className="rounded-lg bg-muted/40 px-3 py-2 text-muted-foreground">
          还没有特征。写出一章满意的，回来提取——它会成为全书的写法底色。
        </p>
      )}
    </div>
  );
}
