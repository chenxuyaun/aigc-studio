import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ErrorState, LoadingState } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";
import { ChapterEditor } from "@/pages/storystudio/ChapterEditor";
import { ChapterList } from "@/pages/storystudio/ChapterList";
import { CrewPanel } from "@/pages/storystudio/CrewPanel";
import { SearchPanel } from "@/pages/storystudio/SearchPanel";
import { SerialPanel } from "@/pages/storystudio/SerialPanel";
import { WorldPanel } from "@/pages/storystudio/WorldPanel";

import type { StoryBible, StoryChapter, StoryProject } from "@aigc/shared-types";
import { DEFAULT_MODEL, FALLBACK_MODELS } from "@/lib/constants";

type RightTab = "characters" | "world" | "search" | "serial";

/** 创作项目页：左章节树 / 中编辑器 / 右角色·世界书·连载。 */
export function StoryProjectPage() {
  const { projectId = "" } = useParams();
  const [params] = useSearchParams();
  const toast = useToast();
  const navigate = useNavigate();
  const [bible, setBible] = useState<StoryBible | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<StoryChapter | null>(null);
  const [rightTab, setRightTab] = useState<RightTab>("characters");
  const [models, setModels] = useState<string[]>([]);
  const [unhealthyModels, setUnhealthyModels] = useState<Set<string>>(new Set());
  const [outlineModel, setOutlineModel] = useState("");
  const [outlineBusy, setOutlineBusy] = useState(false);
  const [consistencyBusy, setConsistencyBusy] = useState(false);
  const [consistencyReport, setConsistencyReport] = useState<string | null>(null);
  const [docsOpen, setDocsOpen] = useState(false);
  const [allDocs, setAllDocs] = useState<{ id: string; title: string }[]>([]);
  const [docIds, setDocIds] = useState<string[]>([]);

  // 选中章节 → 拉全文（bible 只返回摘要）
  const { error: toastError } = useToast();
  const loadChapter = useCallback(
    async (ch: StoryChapter) => {
      try {
        const r = await apiClient.get<{ chapter: StoryChapter }>(`/story/chapters/${ch.id}`);
        setSelected(r.chapter);
      } catch (e) {
        toastError(e instanceof Error ? e.message : "加载章节失败");
      }
    },
    [toastError],
  );

  const load = useCallback(async () => {
    try {
      const r = await apiClient.get<StoryBible>(`/story/projects/${projectId}/bible`);
      setBible(r);
      setError("");
      setSelected((prev) =>
        prev ? (r.chapters.find((c) => c.id === prev.id) ?? null) : null,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }, [projectId]);

  // 无选中章节时自动打开第一章（拉全文）；URL 带 ?chapter= 时优先打开指定章节
  useEffect(() => {
    if (!selected && bible && bible.chapters.length > 0) {
      const target = params.get("chapter")
        ? bible.chapters.find((c) => c.id === params.get("chapter"))
        : null;
      const ch = target ?? bible.chapters[0];
      if (ch) void loadChapter(ch);
    }
  }, [bible, selected, loadChapter, params]);

  const onSelectChapter = (ch: StoryChapter | null) => {
    if (ch) void loadChapter(ch);
    else setSelected(null);
  };

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const loadModels = async () => {
      try {
        const r = await apiClient.get<
          { items: { id: string; name: string; healthy?: boolean }[] }
        >("/providers/catalog");
        const list = (r.items ?? [])
          .filter((p) => p.id !== "mock")
          .map((p) => p.id);
        setModels(list.length ? list : FALLBACK_MODELS);
        setUnhealthyModels(
          new Set((r.items ?? []).filter((p) => p.healthy === false).map((p) => p.id)),
        );
      } catch {
        setModels(FALLBACK_MODELS);
      }
    };
    void loadModels();
  }, []);

  const updateProject = async (fields: Partial<StoryProject>) => {
    try {
      const r = await apiClient.put<{ project: StoryProject }>(
        `/story/projects/${projectId}`,
        fields,
      );
      setBible((b) => (b ? { ...b, project: r.project } : b));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    }
  };

  const generateOutline = async () => {
    setOutlineBusy(true);
    try {
      const q = outlineModel ? `&model=${encodeURIComponent(outlineModel)}` : "";
      const r = await apiClient.post<{ chapters: StoryChapter[] }>(
        `/story/projects/${projectId}/outline?chapters=8${q}`,
      );
      await load();
      const first = r.chapters[0];
      if (first) {
        void loadChapter(first);
        toast.success(`已生成 ${r.chapters.length} 章大纲`);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "大纲生成失败");
    } finally {
      setOutlineBusy(false);
    }
  };

  const onChapterChanged = (ch: StoryChapter) => {
    setBible((b) => {
      if (!b) return b;
      const idx = b.chapters.findIndex((c) => c.id === ch.id);
      const chapters = idx >= 0
        ? b.chapters.map((c) => (c.id === ch.id ? ch : c))
        : [...b.chapters, ch].sort((a, b) => a.chapter_no - b.chapter_no);
      return { ...b, chapters };
    });
    setSelected(ch);
  };

  const onCharactersChanged = () => {
    void load();
  };

  if (error) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10">
        <ErrorState error={error} onRetry={() => void load()} />
        <Button variant="outline" className="mt-4" onClick={() => navigate("/story")}>
          返回创作工作室
        </Button>
      </div>
    );
  }
  if (!bible) return <LoadingState />;
  const p = bible.project;

  return (
    // 固定视口高度：AppShell 的 main 是滚动容器（auto 高度），h-full 会塌陷，
    // 三栏与内部滚动区需要明确高度（顶栏 h-15 = 3.75rem）
    <div className="flex h-[calc(100dvh-3.75rem)] flex-col">
      {/* 顶栏 */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-2.5">
        <button onClick={() => navigate("/story")} className="text-sm text-muted-foreground hover:text-foreground">
          ← 工作室
        </button>
        <input
          value={p.title}
          onChange={(e) => setBible((b) => (b ? { ...b, project: { ...b.project, title: e.target.value } } : b))}
          onBlur={(e) => { if (e.target.value !== p.title) void updateProject({ title: e.target.value }); }}
          className="w-56 rounded-lg border border-transparent bg-transparent px-2 py-1 text-base font-semibold outline-none hover:border-border focus:border-primary"
        />
        <span className="rounded-lg bg-surface px-2.5 py-1 text-xs text-muted-foreground">{p.genre || "未分类"}</span>
        <span className="text-xs text-muted-foreground">
          {bible.chapters.filter((c) => c.status === "done").length}/{bible.chapters.length} 章已完成
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={async () => {
              try {
                const docs = await apiClient.get<{ id: string; title: string }[]>(
                  "/knowledge/documents",
                );
                setAllDocs(docs);
                const current = (p.settings?.knowledge_doc_ids as string[] | undefined) ?? [];
                setDocIds(current);
                setDocsOpen(true);
              } catch (e) {
                toast.error(e instanceof Error ? e.message : "加载知识库文档失败");
              }
            }}
          >
            项目资料
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={consistencyBusy}
            onClick={async () => {
              setConsistencyBusy(true);
              try {
                const r = await apiClient.post<{ report: string }>(
                  `/story/projects/${projectId}/crew`,
                  { stage: "consistency", model: DEFAULT_MODEL },
                );
                setConsistencyReport(r.report);
              } catch (e) {
                toast.error(e instanceof Error ? e.message : "一致性检查失败");
              } finally {
                setConsistencyBusy(false);
              }
            }}
          >
            {consistencyBusy ? "检查中…" : "一致性检查"}
          </Button>
          <select
            value={p.status}
            onChange={(e) => void updateProject({ status: e.target.value as StoryProject["status"] })}
            className="rounded-lg border border-border bg-surface px-2 py-1 text-xs"
          >
            <option value="drafting">构思中</option>
            <option value="ongoing">连载中</option>
            <option value="completed">已完成</option>
          </select>
        </div>
      </div>

      {/* 三栏：移动端堆叠（章节列表 → 编辑器 → 右栏），桌面三栏并排 */}
      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[220px_minmax(0,1fr)_300px] lg:overflow-visible">
        <aside className="min-h-0 border-r border-border lg:overflow-y-auto">
          <ChapterList
            chapters={bible.chapters}
            selectedId={selected?.id ?? null}
            onSelect={onSelectChapter}
            onChanged={onChapterChanged}
            projectId={projectId}
            onOutline={() => void generateOutline()}
            outlineBusy={outlineBusy}
            models={models}
            outlineModel={outlineModel}
            onOutlineModel={setOutlineModel}
          />
        </aside>

        <main className="min-h-0 lg:overflow-y-auto">
          <ChapterEditor
            projectId={projectId}
            chapter={selected}
            models={models}
            unhealthyModels={unhealthyModels}
            onChanged={onChapterChanged}
          />
        </main>

        <aside className="flex min-h-0 flex-col border-t border-border lg:border-l lg:border-t-0">
          <div className="flex border-b border-border text-xs">
            {([
              ["characters", "角色与团队"],
              ["world", "世界书"],
              ["search", "查找"],
              ["serial", "连载"],
            ] as [RightTab, string][]).map(([tab, label]) => (
              <button
                key={tab}
                onClick={() => setRightTab(tab)}
                className={`flex-1 px-2 py-2.5 transition-colors ${
                  rightTab === tab ? "border-b-2 border-primary font-medium" : "text-muted-foreground"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">
            {rightTab === "characters" && (
              <CrewPanel
                projectId={projectId}
                characters={bible.characters}
                onChanged={onCharactersChanged}
              />
            )}
            {rightTab === "world" && <WorldPanel projectId={projectId} onChanged={() => void load()} />}
            {rightTab === "search" && (
              <SearchPanel
                projectId={projectId}
                onOpenChapter={(chapterId) => {
                  const ch = bible.chapters.find((c) => c.id === chapterId);
                  if (ch) onSelectChapter(ch);
                }}
              />
            )}
            {rightTab === "serial" && <SerialPanel projectId={projectId} />}
          </div>
        </aside>
      </div>
      <Dialog open={consistencyReport !== null} onClose={() => setConsistencyReport(null)} title="全书一致性检查报告">
        <div className="max-h-[70vh] overflow-y-auto whitespace-pre-wrap rounded-md bg-muted/40 p-4 text-sm leading-relaxed">
          {consistencyReport}
        </div>
      </Dialog>
      <Dialog open={docsOpen} onClose={() => setDocsOpen(false)} title="项目资料（知识库文档）">
        <div className="flex max-h-[60vh] flex-col gap-2 overflow-y-auto">
          <p className="text-xs text-muted-foreground">
            勾选的文档会在生成大纲/章节时自动检索相关片段注入提示词（如本格推理规范、创作方法论）。
          </p>
          {allDocs.length === 0 && (
            <p className="text-sm text-muted-foreground">知识库暂无文档，请先到「知识库」上传。</p>
          )}
          {allDocs.map((d) => (
            <label
              key={d.id}
              className="flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            >
              <input
                type="checkbox"
                checked={docIds.includes(d.id)}
                onChange={(e) =>
                  setDocIds((prev) =>
                    e.target.checked
                      ? [...prev, d.id]
                      : prev.filter((x) => x !== d.id),
                  )
                }
                className="accent-primary"
              />
              <span className="truncate">{d.title}</span>
            </label>
          ))}
        </div>
        <div className="mt-3 flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => setDocsOpen(false)}>
            取消
          </Button>
          <Button
            size="sm"
            onClick={async () => {
              try {
                await updateProject({ settings: { knowledge_doc_ids: docIds } });
                toast.success("已保存项目资料配置");
                setDocsOpen(false);
              } catch {
                toast.error("保存失败");
              }
            }}
          >
            保存
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

export default StoryProjectPage;
