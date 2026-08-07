import { useCallback, useEffect, useState } from "react";

import { Brain, Eraser, Loader2, Sparkles } from "lucide-react";

import { apiClient } from "@/lib/apiClient";
import { useToast } from "@/components/ui/Toast";
import type { CharacterMemoryOverview } from "@aigc/shared-types";

interface KnowledgeDoc {
  id: string;
  title: string;
  char_count: number;
}

interface MemoryPanelProps {
  assetId: string;
}

/** 角色陪伴记忆面板：原著蒸馏入口 + 档案展示 + 交互记忆（L1/L2/L3）+ 注入开关。 */
export function MemoryPanel({ assetId }: MemoryPanelProps) {
  const { error: toastError, success: toastSuccess } = useToast();
  const [overview, setOverview] = useState<CharacterMemoryOverview | null>(null);
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [docId, setDocId] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [busy, setBusy] = useState(false);
  const [distilling, setDistilling] = useState(false);

  const load = useCallback(async () => {
    if (!assetId) return;
    try {
      const data = await apiClient.get<CharacterMemoryOverview>(`/memory/${assetId}`);
      setOverview(data);
      setDistilling(data.profile?.status === "pending" || data.profile?.status === "running");
    } catch {
      setOverview(null);
    }
  }, [assetId]);

  const loadDocs = useCallback(async () => {
    try {
      setDocs(await apiClient.get<KnowledgeDoc[]>("/knowledge/documents"));
    } catch {
      setDocs([]);
    }
  }, []);

  useEffect(() => {
    void load();
    void loadDocs();
  }, [load, loadDocs]);

  // 蒸馏进行中：轮询状态
  useEffect(() => {
    if (!distilling || !assetId) return;
    const timer = setInterval(() => {
      void apiClient
        .get<{ status: string }>(`/memory/distill/${assetId}`)
        .then((r) => {
          if (r.status === "done" || r.status === "failed") {
            setDistilling(false);
            void load();
          }
        })
        .catch(() => setDistilling(false));
    }, 3000);
    return () => clearInterval(timer);
  }, [distilling, assetId, load]);

  const triggerDistill = async () => {
    const text = pasteText.trim();
    if (!docId && !text) {
      toastError("请选择知识库文档或粘贴书籍文本");
      return;
    }
    setBusy(true);
    try {
      await apiClient.post("/memory/distill", {
        asset_id: assetId,
        doc_id: docId || null,
        text: text || null,
      });
      setDistilling(true);
      toastSuccess("开始蒸馏，完成后自动刷新");
      setPasteText("");
    } catch (e) {
      toastError(e instanceof Error ? e.message : "蒸馏触发失败");
    } finally {
      setBusy(false);
    }
  };

  const toggleInject = async (inject: boolean) => {
    try {
      const r = await apiClient.put<{ config: { inject: boolean; budget: number } }>(
        `/memory/${assetId}/config`,
        { inject, budget: overview?.config.budget ?? 2500 },
      );
      setOverview((prev) => (prev ? { ...prev, config: r.config } : prev));
      toastSuccess(inject ? "记忆注入已开启" : "记忆注入已关闭");
    } catch (e) {
      toastError(e instanceof Error ? e.message : "配置保存失败");
    }
  };

  const clearMemory = async () => {
    if (!window.confirm("确认清空该角色的全部交互记忆（L0-L3）？原著档案不受影响。")) return;
    try {
      await apiClient.post(`/memory/${assetId}/clear`, {});
      toastSuccess("交互记忆已清空");
      void load();
    } catch (e) {
      toastError(e instanceof Error ? e.message : "清空失败");
    }
  };

  const p = overview?.profile;
  return (
    <div className="space-y-4">
      {/* ── 原著蒸馏 ── */}
      <div>
        <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-foreground">
          <Sparkles className="h-3.5 w-3.5 text-primary-text" aria-hidden />
          原著蒸馏（书籍 → 角色档案）
        </p>
        <div className="space-y-2">
          <select
            value={docId}
            onChange={(e) => setDocId(e.target.value)}
            className="w-full rounded-lg border border-border bg-surface px-2 py-1.5 text-xs text-foreground"
          >
            <option value="">选择知识库文档…</option>
            {docs.map((d) => (
              <option key={d.id} value={d.id}>
                {d.title}（{d.char_count.toLocaleString()} 字）
              </option>
            ))}
          </select>
          <textarea
            value={pasteText}
            onChange={(e) => setPasteText(e.target.value)}
            placeholder="或直接粘贴书籍文本（长文本自动分块摘要）"
            rows={3}
            className="w-full resize-none rounded-lg border border-border bg-surface px-2 py-1.5 text-xs text-foreground placeholder:text-muted-foreground"
          />
          <button
            onClick={() => void triggerDistill()}
            disabled={busy || distilling}
            className="w-full rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {distilling ? "蒸馏中…" : busy ? "提交中…" : "开始蒸馏"}
          </button>
        </div>
        {p?.status === "failed" && (
          <p className="mt-1.5 text-[10px] text-danger">蒸馏失败：{p.error}</p>
        )}
      </div>

      {/* ── 原著档案 ── */}
      {p && p.status === "done" && (
        <div className="space-y-2 rounded-xl border border-border bg-surface p-3">
          <p className="flex items-center gap-1.5 text-xs font-medium text-foreground">
            <Brain className="h-3.5 w-3.5 text-primary-text" aria-hidden />
            原著档案 · 《{p.book_title}》
          </p>
          {p.identity && <p className="text-[11px] leading-relaxed text-foreground"><span className="text-muted-foreground">身份：</span>{p.identity}</p>}
          {p.personality && <p className="text-[11px] leading-relaxed text-foreground"><span className="text-muted-foreground">性格：</span>{p.personality}</p>}
          {p.speech_style && <p className="text-[11px] leading-relaxed text-foreground"><span className="text-muted-foreground">说话风格：</span>{p.speech_style}</p>}
          {p.knowledge_bounds && <p className="text-[11px] leading-relaxed text-foreground"><span className="text-muted-foreground">知识边界：</span>{p.knowledge_bounds}</p>}
          {p.relationships.length > 0 && (
            <div>
              <p className="text-[10px] text-muted-foreground">关系网</p>
              <div className="flex flex-wrap gap-1">
                {p.relationships.slice(0, 8).map((r, i) => (
                  <span key={i} className="rounded-full bg-secondary px-2 py-0.5 text-[10px]">
                    {r.name}·{r.relation}
                  </span>
                ))}
              </div>
            </div>
          )}
          {p.core_memories.length > 0 && (
            <div>
              <p className="text-[10px] text-muted-foreground">核心记忆</p>
              <ul className="space-y-0.5 text-[10px] text-muted-foreground">
                {p.core_memories.slice(0, 6).map((m, i) => (
                  <li key={i}>· {m.event}（{m.time}）</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      {!p && (
        <p className="rounded-xl border border-dashed border-border p-3 text-center text-[10px] text-muted-foreground">
          尚未蒸馏。选择一本包含该角色的书，生成它的原著档案后，对话中它会记得书中的自己。
        </p>
      )}

      {/* ── 注入开关 ── */}
      <div className="flex items-center justify-between rounded-xl border border-border bg-surface px-3 py-2">
        <div>
          <p className="text-[11px] font-medium text-foreground">记忆注入</p>
          <p className="text-[10px] text-muted-foreground">
            原著档案 + 交互记忆（L1/L2/L3）注入对话
          </p>
        </div>
        <button
          onClick={() => void toggleInject(!overview?.config.inject)}
          className={`relative h-5 w-9 rounded-full transition-colors ${overview?.config.inject ? "bg-primary" : "bg-border"}`}
          aria-label={overview?.config.inject ? "关闭记忆注入" : "开启记忆注入"}
        >
          <span
            className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${overview?.config.inject ? "left-4.5" : "left-0.5"}`}
          />
        </button>
      </div>

      {/* ── 交互记忆 ── */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="text-xs font-medium text-foreground">交互记忆（L1 原子事实）</p>
          <button
            onClick={() => void clearMemory()}
            className="flex items-center gap-0.5 text-[10px] text-muted-foreground hover:text-danger"
          >
            <Eraser className="h-3 w-3" aria-hidden />
            清空
          </button>
        </div>
        {overview && overview.atoms.length === 0 && (
          <p className="text-[10px] text-muted-foreground">
            暂无原子记忆——对话约 5 轮后自动抽取沉淀（{overview.scenarios.length} 个场景，画像{" "}
            {overview.persona ? "已生成" : "未生成"}）。
          </p>
        )}
        {overview?.atoms.map((a) => (
          <div key={a.id} className="mb-1.5 rounded-lg border border-border bg-surface p-2">
            <p className="text-[10px] leading-relaxed text-foreground">{a.content}</p>
            <p className="mt-0.5 text-[9px] text-muted-foreground">
              [{a.type || "fact"}
              {a.scene ? ` · ${a.scene}` : ""}]
            </p>
          </div>
        ))}
        {overview && overview.atoms.length > 0 && (
          <p className="mt-1 text-[9px] text-muted-foreground">
            （gateway 异步抽取，可能有几分钟延迟）
          </p>
        )}
      </div>

      {/* ── 场景与画像 ── */}
      {(overview?.scenarios.length ?? 0) > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-foreground">场景（L2）</p>
          <div className="space-y-1">
            {overview?.scenarios.slice(0, 6).map((s) => (
              <div key={s.name} className="rounded-lg border border-border bg-surface p-2">
                <p className="flex items-center justify-between text-[10px] font-medium text-foreground">
                  {s.name}
                  {s.heat > 0 && (
                    <span className="text-[9px] text-muted-foreground">热度 {s.heat}</span>
                  )}
                </p>
                {s.summary && (
                  <p className="text-[9px] text-muted-foreground">{s.summary}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
      {overview?.persona && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-foreground">交互画像（L3）</p>
          <p className="whitespace-pre-wrap rounded-lg border border-border bg-surface p-2 text-[10px] leading-relaxed text-foreground">
            {overview.persona.slice(0, 600)}
          </p>
        </div>
      )}

      {!overview && (
        <p className="flex items-center justify-center gap-1 py-4 text-[10px] text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
          加载记忆面板…
        </p>
      )}
    </div>
  );
}
