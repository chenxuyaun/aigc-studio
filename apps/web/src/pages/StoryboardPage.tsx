import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { ErrorState, LoadingState } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { AppError, apiClient } from "@/lib/apiClient";
import type { StoryBible } from "@aigc/shared-types";

interface SceneState {
  title: string;
  prompt: string;
  taskId: string | null;
  status: string; // queued / processing / succeeded / failed / idle
  assetUrl?: string | null;
  error?: string | null;
}

interface RecentItem {
  id: string;
  status: string;
  progress?: number | null;
  asset_url?: string | null;
  error_message?: string | null;
}

interface StoryboardScene {
  title: string;
  prompt: string;
  task_id?: string;
  status?: string;
}

const SCENE_OPTIONS = [4, 6, 8, 12];

export function StoryboardPage() {
  const { projectId = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [bible, setBible] = useState<StoryBible | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [chapterId, setChapterId] = useState(params.get("chapter") || "");
  const [sceneCount, setSceneCount] = useState(6);
  const [scenes, setScenes] = useState<SceneState[]>([]);
  const [splitting, setSplitting] = useState(false);
  const [splitError, setSplitError] = useState<string | null>(null);
  const sceneRef = useRef<SceneState[]>([]);

  useEffect(() => {
    sceneRef.current = scenes;
  }, [scenes]);

  useEffect(() => {
    let alive = true;
    apiClient
      .get<StoryBible>(`/story/projects/${projectId}/bible`)
      .then((b) => {
        if (!alive) return;
        setBible(b);
        setChapterId((prev) => prev || b.chapters?.[0]?.id || "");
      })
      .catch((err) => {
        if (alive) setLoadError(err instanceof AppError ? err.message : "加载失败");
      });
    return () => {
      alive = false;
    };
  }, [projectId]);

  // 轮询：每 6s 拉全部 video 任务，按 taskId 对账更新状态/播放地址
  const hasScenes = scenes.length > 0;
  useEffect(() => {
    if (!hasScenes) return;
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      try {
        const r = await apiClient.get<{ items: RecentItem[] }>(
          "/generations/recent?task_type=video&status=all&limit=100",
        );
        if (!alive) return;
        const byId = new Map(r.items.map((it) => [it.id, it]));
        setScenes((prev) =>
          prev.map((s) => {
            if (!s.taskId) return s;
            const cur = byId.get(s.taskId);
            if (!cur) return s;
            return {
              ...s,
              status: cur.status,
              assetUrl: cur.asset_url ?? null,
              error: cur.status === "failed" ? (cur.error_message ?? "生成失败") : (s.error ?? null),
            };
          }),
        );
      } catch {
        // 网络抖动忽略，下轮再试
      }
    };
    void tick();
    const timer = setInterval(() => void tick(), 6000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [hasScenes]);

  const running = scenes.some((s) => s.status === "queued" || s.status === "processing");

  const splitStoryboard = useCallback(async () => {
    if (!chapterId) {
      toast.error("请先选择要影视化的章节");
      return;
    }
    setSplitting(true);
    setSplitError(null);
    setScenes([]);
    try {
      const r = await apiClient.post<{ scenes: StoryboardScene[] }>("/generations/video/storyboard", {
        chapter_id: chapterId,
        scenes: sceneCount,
        model: "",
      });
      setScenes(
        (r.scenes || []).map((s) => ({
          title: s.title,
          prompt: s.prompt,
          taskId: s.task_id || null,
          status: s.status ?? "queued",
        })),
      );
      toast.success(`已拆解 ${(r.scenes || []).length} 个分镜，已交给 GPU 节点出片`);
    } catch (err) {
      setSplitError(err instanceof AppError ? err.message : "分镜生成失败");
    } finally {
      setSplitting(false);
    }
  }, [chapterId, sceneCount, toast]);

  const retryScene = useCallback(
    async (idx: number) => {
      const s = sceneRef.current[idx];
      if (!s) return;
      try {
        const task = await apiClient.post<{ id: string }>("/generations/video/generate", {
          model: "",
          prompt: s.prompt,
          duration: 5,
        });
        setScenes((prev) =>
          prev.map((sc, i) =>
            i === idx
              ? { ...sc, taskId: task.id, status: "queued", assetUrl: null, error: null }
              : sc,
          ),
        );
        toast.success("已重新提交生成");
      } catch (err) {
        toast.error(err instanceof AppError ? err.message : "提交失败");
      }
    },
    [toast],
  );

  const updatePrompt = useCallback((idx: number, prompt: string) => {
    setScenes((prev) => prev.map((sc, i) => (i === idx ? { ...sc, prompt } : sc)));
  }, []);

  const retryAll = useCallback(async () => {
    for (let i = 0; i < sceneRef.current.length; i += 1) {
      const sc = sceneRef.current[i];
      if (sc && sc.status !== "succeeded") {
        await retryScene(i);
      }
    }
  }, [retryScene]);

  const chapter = bible?.chapters?.find((c) => c.id === chapterId);

  if (loadError) return <ErrorState error={loadError} />;
  if (!bible) return <LoadingState label="加载项目…" />;

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-border bg-surface px-4 py-3">
        <button
          onClick={() => navigate(`/story/${projectId}`)}
          className="rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          ← 返回故事
        </button>
        <h1 className="text-base font-semibold">{bible.project?.title ?? "剧本影视化"}</h1>
        <select
          value={chapterId}
          onChange={(e) => setChapterId(e.target.value)}
          className="rounded-lg border border-border bg-surface px-2 py-1 text-xs"
        >
          <option value="">选择章节…</option>
          {(bible.chapters || []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.chapter_no}. {c.title || "未命名"}
            </option>
          ))}
        </select>
        <select
          value={sceneCount}
          onChange={(e) => setSceneCount(Number(e.target.value))}
          className="rounded-lg border border-border bg-surface px-2 py-1 text-xs"
        >
          {SCENE_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n} 个分镜
            </option>
          ))}
        </select>
        <Button size="sm" onClick={() => void splitStoryboard()} disabled={splitting || running}>
          {splitting ? "拆解中…" : "🎬 生成分镜"}
        </Button>
        {scenes.length > 0 && (
          <Button size="sm" variant="ghost" onClick={() => void retryAll()} disabled={running}>
            重试失败镜头
          </Button>
        )}
        {!chapter && (
          <span className="ml-auto text-xs text-muted-foreground">
            {bible.chapters?.length ? "请选择章节" : "该故事还没有章节，先去故事页写正文"}
          </span>
        )}
      </header>

      {splitError && (
        <div className="mx-4 mt-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {splitError}
        </div>
      )}

      {scenes.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
          <div className="text-3xl">🎞️</div>
          <p>选择章节后点击「生成分镜」——AI 导演会把章节拆成连续镜头，</p>
          <p>每个镜头交给 160 GPU 节点（Wan2.1）逐段生成视频。</p>
        </div>
      ) : (
        <div className="grid flex-1 grid-cols-1 gap-4 overflow-y-auto p-4 md:grid-cols-2 xl:grid-cols-3">
          {scenes.map((scene, idx) => (
            <SceneCard
              key={`${scene.taskId || idx}-${idx}`}
              scene={scene}
              index={idx}
              onRetry={() => void retryScene(idx)}
              onUpdatePrompt={(prompt) => updatePrompt(idx, prompt)}
            />
          ))}
        </div>
      )}

      {running && (
        <footer className="border-t border-border bg-surface px-4 py-2 text-xs text-muted-foreground">
          ⏳ 视频在 160 GPU 节点上逐镜生成中（每镜约 1~2 分钟），页面每 6 秒自动刷新进度。
        </footer>
      )}
    </div>
  );
}

function SceneCard({
  scene,
  index,
  onRetry,
  onUpdatePrompt,
}: {
  scene: SceneState;
  index: number;
  onRetry: () => void;
  onUpdatePrompt: (prompt: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(scene.prompt);

  const busy = scene.status === "queued" || scene.status === "processing";

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3">
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-xs font-semibold text-primary">
          {index + 1}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{scene.title}</span>
        <StatusBadge status={scene.status} />
      </div>

      {scene.status === "succeeded" && scene.assetUrl ? (
        <video
          src={scene.assetUrl}
          controls
          className="aspect-video w-full rounded-lg bg-black/60"
          preload="metadata"
        />
      ) : busy ? (
        <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-lg bg-muted/40 text-xs text-muted-foreground">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          {scene.status === "queued" ? "排队中…" : "生成中…（约 1~2 分钟）"}
        </div>
      ) : scene.status === "failed" ? (
        <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 rounded-lg bg-destructive/10 text-xs text-destructive">
          <span>生成失败</span>
          <Button size="sm" variant="ghost" onClick={onRetry}>
            重试
          </Button>
        </div>
      ) : (
        <div className="flex h-24 items-center justify-center rounded-lg bg-muted/30 text-xs text-muted-foreground">
          待生成
        </div>
      )}

      <div className="text-xs leading-relaxed text-muted-foreground">
        {editing ? (
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            className="w-full rounded-md border border-border bg-surface p-2 text-xs"
          />
        ) : (
          <p className="line-clamp-3">{scene.prompt}</p>
        )}
      </div>

      <div className="flex items-center gap-2">
        {editing ? (
          <>
            <Button
              size="sm"
              variant="ghost"
              className="px-2 py-1 text-xs"
              onClick={() => {
                onUpdatePrompt(draft.trim() || scene.prompt);
                setEditing(false);
              }}
            >
              保存
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="px-2 py-1 text-xs"
              onClick={() => setEditing(false)}
            >
              取消
            </Button>
          </>
        ) : (
          <Button size="sm" variant="ghost" className="px-2 py-1 text-xs" onClick={() => setEditing(true)}>
            编辑
          </Button>
        )}
        {scene.status === "failed" && (
          <Button size="sm" variant="ghost" className="px-2 py-1 text-xs text-destructive" onClick={onRetry}>
            重试
          </Button>
        )}
        {scene.error && <span className="ml-auto truncate text-[10px] text-muted-foreground">{scene.error}</span>}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    queued: "排队中",
    processing: "生成中",
    succeeded: "已完成",
    failed: "失败",
  };
  const cls: Record<string, string> = {
    queued: "bg-muted text-muted-foreground",
    processing: "bg-blue-500/15 text-blue-600",
    succeeded: "bg-emerald-500/15 text-emerald-600",
    failed: "bg-destructive/15 text-destructive",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${cls[status] ?? "bg-muted text-muted-foreground"}`}
    >
      {map[status] ?? status}
    </span>
  );
}