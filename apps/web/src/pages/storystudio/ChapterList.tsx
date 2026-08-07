import { Button } from "@/components/ui/Button";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

import type { StoryChapter } from "@aigc/shared-types";

interface Props {
  chapters: StoryChapter[];
  selectedId: string | null;
  onSelect: (ch: StoryChapter | null) => void;
  onChanged: (ch: StoryChapter) => void;
  projectId: string;
  onOutline: () => void;
  outlineBusy: boolean;
  models: string[];
  outlineModel: string;
  onOutlineModel: (m: string) => void;
}

/** 章节树：编号/标题/状态徽章；支持新建与删除。 */
export function ChapterList({
  chapters,
  selectedId,
  onSelect,
  onChanged,
  projectId,
  onOutline,
  outlineBusy,
  models,
  outlineModel,
  onOutlineModel,
}: Props) {
  const toast = useToast();

  const createChapter = async () => {
    try {
      const r = await apiClient.post<{ chapter: StoryChapter }>(
        `/story/projects/${projectId}/chapters`,
        {},
      );
      onChanged(r.chapter);
      onSelect(r.chapter);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "新建失败");
    }
  };

  const remove = async (ch: StoryChapter) => {
    if (!window.confirm(`删除「第 ${ch.chapter_no} 章 ${ch.title}」？`)) return;
    try {
      await apiClient.del(`/story/chapters/${ch.id}`);
      if (selectedId === ch.id) onSelect(chapters[0] ?? null);
      toast.success("已删除");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  return (
    <div className="flex h-full flex-col gap-2 p-3">
      <div className="flex items-center gap-2">
        <Button size="sm" className="flex-1" onClick={createChapter}>+ 新建章节</Button>
        <Button size="sm" variant="outline" disabled={outlineBusy} onClick={onOutline}>
          {outlineBusy ? "生成中…" : "生成大纲"}
        </Button>
      </div>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span>大纲模型</span>
        <select
          value={outlineModel}
          onChange={(e) => onOutlineModel(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-border bg-surface px-1.5 py-1 text-xs"
          title="生成大纲使用的模型；「自动」选择优先级最高的可用模型"
        >
          <option value="">自动（最优）</option>
          {models.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto">
        {chapters.length === 0 && (
          <p className="pt-8 text-center text-xs text-muted-foreground">
            还没有章节。<br />点「生成大纲」一键规划，<br />或手动新建。
          </p>
        )}
        {chapters.map((ch) => (
          <button
            key={ch.id}
            onClick={() => onSelect(ch)}
            className={`w-full rounded-xl border px-3 py-2 text-left transition-colors ${
              selectedId === ch.id
                ? "border-primary bg-surface-raised"
                : "border-border bg-surface hover:border-border-strong"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-medium">
                {ch.chapter_no}. {ch.title || "未命名"}
              </span>
              <StatusBadge status={ch.status === "done" ? "succeeded" : ch.status === "draft" ? "processing" : "queued"} />
            </div>
            {ch.outline && (
              <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{ch.outline}</p>
            )}
            {ch.word_count > 0 && (
              <span className="mt-1 block text-right text-[10px] text-muted-foreground">
                {ch.word_count} 字
              </span>
            )}
            {selectedId === ch.id && (
              <span
                role="button"
                tabIndex={0}
                onClick={(e) => { e.stopPropagation(); remove(ch); }}
                onKeyDown={(e) => { if (e.key === "Enter") remove(ch); }}
                className="mt-1 block text-right text-xs text-danger/70 hover:text-danger"
              >
                删除本章
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
