import { useRef, useState } from "react";

import type { CatalogItem } from "@aigc/shared-types";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, FileUp, MessageSquareText, Plus, Trash2 } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { MarkdownContent } from "@/components/ui/MarkdownContent";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";

interface KnowledgeDoc {
  id: string;
  title: string;
  char_count: number;
  created_at: string;
  updated_at: string;
}

interface AskResult {
  answer: string;
  model: string;
  source: string;
  error?: string | null;
  sources: Array<{ doc_id: string; title: string; snippet: string }>;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function KnowledgePage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [question, setQuestion] = useState("");
  const [model, setModel] = useState("");
  const [askResult, setAskResult] = useState<AskResult | null>(null);
  const [askLoading, setAskLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const docs = useQuery({
    queryKey: ["knowledge", "documents"],
    queryFn: () => apiClient.get<KnowledgeDoc[]>("/knowledge/documents"),
  });

  const catalog = useQuery({
    queryKey: ["providers", "catalog"],
    queryFn: async () => {
      try {
        return await apiClient.get<CatalogItem[]>("/providers/catalog");
      } catch {
        return await apiClient.get<CatalogItem[]>("/providers/");
      }
    },
    staleTime: 30_000,
  });
  const modelOptions: CatalogItem[] = catalog.data ?? [];

  const createDoc = useMutation({
    mutationFn: async () =>
      apiClient.post<KnowledgeDoc>("/knowledge/documents", {
        title: title.trim(),
        content: content.trim(),
      }),
    onSuccess: () => {
      toast.success("文档已保存");
      setTitle("");
      setContent("");
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "documents"] });
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "保存失败，请重试"),
  });

  const deleteDoc = useMutation({
    mutationFn: (id: string) => apiClient.del<{ success: boolean }>(`/knowledge/documents/${id}`),
    onSuccess: () => {
      toast.success("文档已删除");
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "documents"] });
    },
    onError: (err) =>
      toast.error(err instanceof Error ? err.message : "删除失败，请重试"),
  });

  async function handleUpload(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    if (!/\.(txt|md|markdown)$/i.test(file.name)) {
      toast.error("仅支持 .txt / .md / .markdown 文件");
      return;
    }
    if (file.size > 500 * 1024) {
      toast.error("文件超过 500KB 限制");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    try {
      await apiClient.postForm<KnowledgeDoc>("/knowledge/upload", form);
      toast.success(`已上传「${file.name}」`);
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "documents"] });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "上传失败，请重试");
    }
    if (fileRef.current) fileRef.current.value = "";
  }

  async function ask() {
    const q = question.trim();
    if (!q || askLoading) return;
    setAskLoading(true);
    setAskResult(null);
    try {
      const res = await apiClient.post<{ data: AskResult }>("/knowledge/ask", {
        question: q,
        model,
      });
      setAskResult(res.data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "提问失败，请重试");
    } finally {
      setAskLoading(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="知识库"
        description="上传/粘贴文档，基于本地关键词检索进行问答（RAG 最小版）"
      />
      <div className="grid gap-4 p-4 md:grid-cols-[360px_1fr] md:p-6">
        {/* 左列：文档管理 */}
        <div className="flex flex-col gap-4">
          <div className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium">
              <Plus className="h-4 w-4" aria-hidden />
              新建文档
            </h3>
            <div className="flex flex-col gap-3">
              <Field label="标题">
                {({ id }) => (
                  <Input
                    id={id}
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="如：产品说明 V2"
                    maxLength={200}
                  />
                )}
              </Field>
              <Field label="内容" hint="支持粘贴文本，检索按关键词切块">
                {({ id }) => (
                  <Textarea
                    id={id}
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    rows={6}
                    placeholder="粘贴文档内容…"
                  />
                )}
              </Field>
              <div className="flex gap-2">
                <Button
                  onClick={() => createDoc.mutate()}
                  loading={createDoc.isPending}
                  disabled={!title.trim() || !content.trim()}
                >
                  保存
                </Button>
                <Button variant="outline" onClick={() => fileRef.current?.click()}>
                  <FileUp className="h-4 w-4" aria-hidden />
                  上传文件
                </Button>
                <input
                  ref={fileRef}
                  type="file"
                  accept=".txt,.md,.markdown"
                  className="hidden"
                  onChange={(e) => void handleUpload(e.target.files)}
                />
              </div>
            </div>
          </div>

          <div className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-medium">
              <BookOpen className="h-4 w-4" aria-hidden />
              文档列表（{docs.data?.length ?? 0}）
            </h3>
            {docs.isLoading ? (
              <p className="py-4 text-center text-sm text-muted-foreground">加载中…</p>
            ) : !docs.data?.length ? (
              <p className="py-4 text-center text-sm text-muted-foreground">
                还没有文档，先新建或上传一个
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {docs.data.map((doc) => (
                  <li key={doc.id} className="rounded-lg border border-border">
                    <div className="flex items-center gap-2 px-3 py-2">
                      <button
                        type="button"
                        className="min-w-0 flex-1 text-left text-sm hover:text-primary"
                        onClick={() =>
                          setExpandedId((prev) => (prev === doc.id ? null : doc.id))
                        }
                      >
                        <span className="block truncate font-medium">{doc.title}</span>
                        <span className="block text-xs text-muted-foreground">
                          {doc.char_count} 字 · {formatDate(doc.updated_at)}
                        </span>
                      </button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`删除 ${doc.title}`}
                        onClick={() => {
                          if (window.confirm(`确认删除「${doc.title}」？`)) {
                            deleteDoc.mutate(doc.id);
                          }
                        }}
                      >
                        <Trash2 className="h-4 w-4 text-danger" aria-hidden />
                      </Button>
                    </div>
                    {expandedId === doc.id && <DocPreview docId={doc.id} />}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* 右列：知识问答 */}
        <div className="flex min-h-[420px] flex-col rounded-[var(--radius-card)] border border-border bg-surface p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-medium">
            <MessageSquareText className="h-4 w-4" aria-hidden />
            向知识库提问
          </h3>
          <div className="flex flex-col gap-3">
            <Field label="模型">
              {({ id }) => (
                <select
                  id={id}
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {modelOptions.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name}
                      {m.source === "env" ? "（env）" : ""}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="问题" hint="自动检索全部个人文档中最相关的片段">
              {({ id }) => (
                <Textarea
                  id={id}
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  rows={4}
                  placeholder="针对文档内容提问，如：部署步骤是什么？"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      void ask();
                    }
                  }}
                />
              )}
            </Field>
            <div>
              <Button onClick={() => void ask()} loading={askLoading} disabled={!question.trim()}>
                提问
              </Button>
            </div>
          </div>

          {askResult && (
            <div className="mt-4 flex flex-1 flex-col gap-3 overflow-y-auto">
              {askResult.sources.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {askResult.sources.map((s) => (
                    <span
                      key={s.doc_id}
                      title={s.snippet}
                      className="max-w-full truncate rounded-full border border-border bg-surface-raised px-2.5 py-1 text-xs text-muted-foreground"
                    >
                      参考 · {s.title}
                    </span>
                  ))}
                </div>
              )}
              <div
                className={cn(
                  "rounded-xl border p-3.5 text-sm leading-relaxed",
                  askResult.error
                    ? "border-warning/30 bg-warning/10 text-warning"
                    : "border-border bg-surface-raised",
                )}
              >
                {askResult.answer ? (
                  <MarkdownContent content={askResult.answer} />
                ) : (
                  "（无回答）"
                )}
              </div>
              {askResult.error && (
                <p className="text-xs text-muted-foreground">{askResult.error}</p>
              )}
              {!askResult.error && (
                <p className="text-xs text-muted-foreground">来源：{askResult.source}</p>
              )}
            </div>
          )}
          {!askResult && (
            <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
              回答会显示在这里，并标注命中的参考资料
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function DocPreview({ docId }: { docId: string }) {
  const detail = useQuery({
    queryKey: ["knowledge", "document", docId],
    queryFn: () =>
      apiClient.get<KnowledgeDoc & { content: string }>(`/knowledge/documents/${docId}`),
  });
  if (detail.isLoading) return <p className="px-3 pb-2 text-xs text-muted-foreground">加载中…</p>;
  return (
    <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap border-t border-border px-3 py-2 text-xs leading-relaxed text-muted-foreground">
      {detail.data?.content || "（内容为空）"}
    </pre>
  );
}
