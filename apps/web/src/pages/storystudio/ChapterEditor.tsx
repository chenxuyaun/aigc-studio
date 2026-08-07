import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Textarea } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient, streamSse } from "@/lib/apiClient";
import { MarkdownContent } from "@/components/ui/MarkdownContent";

import type { StoryChapter } from "@aigc/shared-types";

interface ChapterVersion {
  id: string;
  word_count: number;
  note: string;
  created_at?: string | null;
}

interface Props {
  projectId: string;
  chapter: StoryChapter | null;
  models: string[];
  unhealthyModels?: Set<string>;
  onChanged: (ch: StoryChapter) => void;
}

/**
 * 章节编辑器：标题/大纲/正文编辑 + 生成（叙事/剧本）+ 流式渲染 + 修订。
 * 生成走 SSE（复用 streamSse），产出直接落库；草稿可手动编辑保存。
 */
export function ChapterEditor({ projectId, chapter, models, unhealthyModels, onChanged }: Props) {
  const toast = useToast();
  const [title, setTitle] = useState("");
  const [outline, setOutline] = useState("");
  const [content, setContent] = useState("");
  const [model, setModel] = useState("");
  const [versions, setVersions] = useState<ChapterVersion[]>([]);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [busy, setBusy] = useState(false);
  const [streaming, setStreaming] = useState("");
  const [reviseText, setReviseText] = useState("");
  const [tab, setTab] = useState<"write" | "preview">("preview");
  const [toolLoop, setToolLoop] = useState(false);
  const savedRef = useRef(false);

  useEffect(() => {
    savedRef.current = false;
    setTitle(chapter?.title ?? "");
    setOutline(chapter?.outline ?? "");
    setContent(chapter?.content ?? "");
    setStreaming("");
    // 仅在章节切换时重置表单（依赖 chapter.id 即可）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapter?.id]);

  const save = async () => {
    if (!chapter) return;
    try {
      const r = await apiClient.put<{ chapter: StoryChapter }>(
        `/story/chapters/${chapter.id}`,
        { title, outline, content },
      );
      onChanged(r.chapter);
      savedRef.current = true;
      toast.success("已保存");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    }
  };

  const generate = async (mode: "narrative" | "script") => {
    if (!chapter) return;
    setBusy(true);
    setStreaming("");
    try {
      // 工具循环走同步生成端点（流式不支持 tool_calls）；普通模式走 SSE
      if (toolLoop && mode === "narrative") {
        const r = await apiClient.post<{ content: string; word_count: number; tool_calls?: unknown[] }>(
          `/story/chapters/${chapter.id}/generate`,
          { project_id: projectId, model, mode, tool_loop: true },
        );
        setContent(String(r.content ?? ""));
        setStreaming("");
        onChanged({ ...chapter, content: String(r.content ?? ""), status: "done" });
        const calls = (r.tool_calls ?? []) as { name: string; summary: string }[];
        toast.success(`生成完成（${r.word_count ?? 0} 字${calls.length ? `，调用工具 ${calls.length} 次` : ""}）`);
        return;
      }
      await streamSse(
        `/story/chapters/${chapter.id}/generate/stream`,
        { project_id: projectId, model, mode, rounds: 6 },
        (ev) => {
          if (ev.type === "chunk" && typeof ev.content === "string") {
            setStreaming((prev) => prev + ev.content);
          } else if (ev.type === "done") {
            setContent(String(ev.content ?? ""));
            setStreaming("");
            onChanged({ ...chapter, content: String(ev.content ?? ""), status: "done" });
            toast.success(`生成完成（${ev.word_count ?? 0} 字）`);
          } else if (ev.type === "error") {
            toast.error(String(ev.error ?? "生成失败"));
          }
        },
      );
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "生成失败");
    } finally {
      setBusy(false);
    }
  };

  const revise = async () => {
    if (!chapter || !reviseText.trim()) return;
    setBusy(true);
    try {
      const params = new URLSearchParams({ instruction: reviseText, model });
      const r = await apiClient.post<{ chapter_id: string; content: string; word_count: number }>(
        `/story/chapters/${chapter.id}/revise?${params.toString()}`,
      );
      setContent(r.content);
      onChanged({ ...chapter, content: r.content, word_count: r.word_count });
      toast.success("修订完成");
      setReviseText("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "修订失败");
    } finally {
      setBusy(false);
    }
  };

  if (!chapter) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        从左侧选择或新建一个章节开始创作
      </div>
    );
  }

  const display = streaming || content;

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-lg bg-surface px-2.5 py-1 text-xs font-medium text-muted-foreground">
          第 {chapter.chapter_no} 章
        </span>
        {chapter.status === "draft" && (
          <span className="rounded-lg bg-warning/15 px-2.5 py-1 text-xs font-medium text-warning">
            草稿（上次生成中断，已保留）
          </span>
        )}
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="rounded-lg border border-border bg-surface px-2 py-1 text-xs"
        >
          <option value="">自动（最优模型）</option>
          {models.map((m) => (
            <option key={m} value={m}>
              {m}{unhealthyModels?.has(m) ? "（维护中）" : ""}
            </option>
          ))}
        </select>
        <div className="ml-auto flex items-center gap-2">
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground" title="生成时允许模型调用技能/创作工具（需支持 function calling 的模型）">
            <input
              type="checkbox"
              checked={toolLoop}
              onChange={(e) => setToolLoop(e.target.checked)}
              className="accent-primary"
            />
            技能工具
          </label>
          <Button size="sm" variant="secondary" disabled={busy} onClick={() => generate("narrative")}>
            {busy && !streaming ? "生成中…" : "生成章节"}
          </Button>
          <Button size="sm" variant="outline" disabled={busy} onClick={() => generate("script")}>
            剧本模式
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!chapter}
            onClick={async () => {
              try {
                const r = await apiClient.get<{ items: ChapterVersion[] }>(
                  `/story/chapters/${chapter.id}/versions`,
                );
                setVersions(r.items);
                setVersionsOpen(true);
              } catch (e) {
                toast.error(e instanceof Error ? e.message : "加载版本失败");
              }
            }}
          >
            版本历史
          </Button>
          <Button size="sm" variant="ghost" onClick={save}>保存</Button>
        </div>
      </div>

      <Field label="章节标题">
        {({ id, describedBy }) => (
          <input
            id={id}
            aria-describedby={describedBy}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
            placeholder="章节标题"
          />
        )}
      </Field>
      <Field label="本章大纲（生成时会注入提示词）">
        {({ id, describedBy }) => (
          <Textarea
            id={id}
            aria-describedby={describedBy}
            value={outline}
            onChange={(e) => setOutline(e.target.value)}
            rows={2}
            placeholder="本章剧情要点：发生什么、涉及哪些角色、结局走向"
          />
        )}
      </Field>

      <div className="flex items-center gap-2 border-b border-border pb-1 text-xs">
        {(["write", "preview"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-md px-2 py-1 ${tab === t ? "bg-surface text-foreground" : "text-muted-foreground"}`}
          >
            {t === "write" ? "编辑" : "预览"}
          </button>
        ))}
        {chapter.status === "done" && (
          <span className="ml-auto text-muted-foreground">{chapter.word_count} 字</span>
        )}
      </div>

      {tab === "write" ? (
        <Textarea
          value={display}
          onChange={(e) => { setContent(e.target.value); setStreaming(""); }}
          rows={24}
          className="flex-1 font-mono text-sm"
          placeholder="章节正文（可直接手写，或点「生成章节」让 AI 以角色扮演方式创作）"
        />
      ) : (
        <div className="markdown-body flex-1 overflow-y-auto rounded-xl border border-border bg-surface p-4">
          <MarkdownContent content={display || "（空）"} />
        </div>
      )}

      <div className="flex items-end gap-2">
        <div className="flex-1">
          <Field label="修订指令（保持情节，只按指令调整）">
            {({ id, describedBy }) => (
              <input
                id={id}
                aria-describedby={describedBy}
                value={reviseText}
                onChange={(e) => setReviseText(e.target.value)}
                className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-primary"
                placeholder="例如：加强氛围描写，突出露娜的犹豫"
              />
            )}
          </Field>
        </div>
        <Button size="sm" variant="outline" disabled={busy || !reviseText.trim()} onClick={revise}>
          修订
        </Button>
      </div>
      <Dialog open={versionsOpen} onClose={() => setVersionsOpen(false)} title="版本历史">
        <div className="flex max-h-[60vh] flex-col gap-2 overflow-y-auto">
          {versions.length === 0 && (
            <p className="text-sm text-muted-foreground">暂无历史版本（修订或重新生成时会自动保存旧稿）</p>
          )}
          {versions.map((v) => (
            <div key={v.id} className="flex items-center justify-between gap-3 rounded-lg border bg-surface p-3">
              <div className="min-w-0">
                <p className="truncate text-sm">{v.note || "（无说明）"}</p>
                <p className="text-xs text-muted-foreground">
                  {v.word_count} 字
                  {v.created_at ? " · " + new Date(v.created_at).toLocaleString("zh-CN") : ""}
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={restoring}
                onClick={async () => {
                  setRestoring(true);
                  try {
                    await apiClient.post(`/story/chapters/${chapter.id}/restore?version_id=${v.id}`);
                    toast.success("已还原该版本");
                    setVersionsOpen(false);
                    onChanged(chapter);
                  } catch (e) {
                    toast.error(e instanceof Error ? e.message : "还原失败");
                  } finally {
                    setRestoring(false);
                  }
                }}
              >
                还原
              </Button>
            </div>
          ))}
        </div>
      </Dialog>
    </div>
  );
}
