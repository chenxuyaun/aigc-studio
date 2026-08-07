import { useEffect, useRef, useState } from "react";

import type { CatalogItem } from "@aigc/shared-types";

import { useQuery } from "@tanstack/react-query";
import { Copy, Eraser, Plus, Square, Wand2, X } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { PageHeader } from "@/components/layout/PageHeader";
import { MarkdownContent } from "@/components/ui/MarkdownContent";
import { useToast } from "@/components/ui/Toast";
import { useChatSessions } from "@/hooks/useChatSessions";
import { AppError, apiClient, streamSse } from "@/lib/apiClient";
import { copyText } from "@/lib/clipboard";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/stores/auth";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface KnowledgeSource {
  doc_id: string;
  title: string;
}

interface KnowledgeDoc {
  id: string;
  title: string;
  char_count: number;
}

// 上下文携带最近 N 轮，防止对话过长爆 token
const HISTORY_LIMIT = 6;

function buildContextPrompt(messages: ChatMessage[]): string {
  const recent = messages.slice(-HISTORY_LIMIT * 2);
  if (recent.length === 0) return "";
  const lines = recent.map((m) => `${m.role === "user" ? "用户" : "助手"}：${m.content}`);
  return `以下是对话历史：\n${lines.join("\n")}\n`;
}

export function TextGenPage() {
  const toast = useToast();
  const location = useLocation();
  const handoff = (location.state as { prompt?: string } | null)?.prompt ?? "";
  const isAdmin = useAuthStore((s) => s.user?.role === "admin");
  const [input, setInput] = useState(handoff);
  const [model, setModel] = useState("");
  const {
    sessions,
    currentId,
    messages,
    createSession,
    switchSession,
    deleteSession,
    setCurrentMessages,
    ensureSession,
  } = useChatSessions();
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fellBack, setFellBack] = useState(false);
  const [fallbackReason, setFallbackReason] = useState<string | null>(null);
  const [usedSource, setUsedSource] = useState<string>("");
  const [knowledgeDocIds, setKnowledgeDocIds] = useState<string[]>([]);
  const [knowledgeSources, setKnowledgeSources] = useState<KnowledgeSource[] | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  // 首次进入：无会话时自动创建一个
  useEffect(() => {
    ensureSession();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const knowledgeDocs = useQuery({
    queryKey: ["knowledge", "documents"],
    queryFn: () => apiClient.get<KnowledgeDoc[]>("/knowledge/documents"),
    staleTime: 30_000,
  });

  const options: CatalogItem[] = catalog.data ?? [];

  useEffect(() => {
    if (!options.some((o) => o.id === model || o.default_model === model)) {
      setModel(options[0]?.id ?? "");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog.data]);

  // 新消息时滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text || streaming) return;
    setError(null);
    setFellBack(false);
    setFallbackReason(null);
    setUsedSource("");
    setKnowledgeSources(null);

    const history = messages;
    const userMsg: ChatMessage = { role: "user", content: text };
    setCurrentMessages([...history, userMsg]);
    setInput("");
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const selected = options.find((o) => o.id === model || o.default_model === model);
    const requestModel = selected?.id ?? model;

    let assistantText = "";
    // 先占位一条空回复，流式往里追加
    setCurrentMessages([...history, userMsg, { role: "assistant", content: "" }]);
    try {
      const context = buildContextPrompt(history);
      const payload = context ? `${context}\n用户：${text}` : text;
      await streamSse(
        "/generations/text/generate",
        {
          model: requestModel,
          prompt: payload,
          stream: true,
          knowledge_doc_ids: knowledgeDocIds.length ? knowledgeDocIds : undefined,
        },
        (event) => {
          if (event.type === "chunk" && typeof event.content === "string") {
            assistantText += event.content;
            setCurrentMessages([
              ...history,
              userMsg,
              { role: "assistant", content: assistantText },
            ]);
          } else if (event.type === "done") {
            if (event.fallback === true) setFellBack(true);
            if (typeof event.fallbackReason === "string" && event.fallbackReason) {
              setFallbackReason(event.fallbackReason);
            }
            if (typeof event.source === "string") setUsedSource(event.source);
            if (Array.isArray(event.knowledgeSources) && event.knowledgeSources.length) {
              setKnowledgeSources(event.knowledgeSources as KnowledgeSource[]);
            }
          }
        },
        controller.signal,
      );
    } catch (err) {
      if (!controller.signal.aborted) {
        setError(err instanceof AppError ? err.message : "生成失败，请重试");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  function stop() {
    abortRef.current?.abort();
    setStreaming(false);
  }

  function clearChat() {
    abortRef.current?.abort();
    if (currentId) deleteSession(currentId);
    setError(null);
    setFellBack(false);
  }

  return (
    <div>
      <PageHeader
        title="文本生成"
        description="多轮会话：上下文自动携带最近 6 轮对话"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {messages.length > 0 && (
              <Button variant="outline" size="sm" onClick={clearChat}>
                <Eraser className="h-4 w-4" aria-hidden />
                清空会话
              </Button>
            )}
            {isAdmin ? (
              <Link to="/settings/providers" className="text-sm text-primary-text hover:underline">
                配置模型
              </Link>
            ) : undefined}
          </div>
        }
      />
      <div className="grid gap-4 p-4 md:grid-cols-[340px_1fr] md:p-6">
        <div className="flex flex-col gap-4">
          <div className="rounded-[var(--radius-card)] border border-border bg-surface p-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-xs font-medium text-muted-foreground">
                会话（{sessions.length}）
              </p>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => createSession()}
                title="新建会话"
              >
                <Plus className="h-4 w-4" aria-hidden />
                新建
              </Button>
            </div>
            {sessions.length === 0 ? (
              <p className="py-2 text-center text-xs text-muted-foreground">
                暂无会话，点「新建」开始
              </p>
            ) : (
              <div className="flex max-h-40 flex-col gap-1 overflow-y-auto">
                {[...sessions].reverse().map((s) => (
                  <div
                    key={s.id}
                    className={cn(
                      "group flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs",
                      s.id === currentId
                        ? "bg-primary/12 font-medium text-primary-text"
                        : "text-muted-foreground hover:bg-surface-raised hover:text-foreground",
                    )}
                  >
                    <button
                      type="button"
                      className="min-w-0 flex-1 truncate text-left"
                      onClick={() => {
                        abortRef.current?.abort();
                        setStreaming(false);
                        switchSession(s.id);
                      }}
                    >
                      {s.name}
                    </button>
                    <button
                      type="button"
                      aria-label={`删除会话 ${s.name}`}
                      className="hidden opacity-0 transition-opacity group-hover:opacity-100 hover:text-danger"
                      onClick={() => {
                        abortRef.current?.abort();
                        setStreaming(false);
                        deleteSession(s.id);
                      }}
                    >
                      <X className="h-3.5 w-3.5" aria-hidden />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
          <Field label="模型">
            {({ id }) => (
              <select
                id={id}
                value={model}
                onChange={(e) => setModel(e.target.value)}
                disabled={streaming}
                className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
              >
                {options.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                    {m.default_model && m.default_model !== m.name
                      ? ` · ${m.default_model}`
                      : ""}
                    {m.source === "env" ? "（env）" : ""}
                  </option>
                ))}
              </select>
            )}
          </Field>
          {error && (
            <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
              {error}
            </p>
          )}
          {fellBack && (
            <div className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning">
              <p>生成未完成（模型不可用或上游错误）。</p>
              {fallbackReason && (
                <p className="mt-1 break-all font-mono text-xs opacity-80" title={fallbackReason}>
                  {fallbackReason}
                </p>
              )}
            </div>
          )}
          {usedSource && !fellBack && (
            <p className="text-xs text-muted-foreground">来源：{usedSource}</p>
          )}
          {knowledgeDocs.data && knowledgeDocs.data.length > 0 && (
            <Field
              label="参考知识库"
              hint={knowledgeDocIds.length ? `已选 ${knowledgeDocIds.length} 篇，命中片段自动注入` : "可选，按内容检索注入上下文"}
            >
              {() => (
                <div className="max-h-36 overflow-y-auto rounded-lg border border-input bg-surface p-2">
                  {knowledgeDocs.data.map((doc) => (
                    <label
                      key={doc.id}
                      className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface-raised"
                    >
                      <input
                        type="checkbox"
                        checked={knowledgeDocIds.includes(doc.id)}
                        disabled={streaming}
                        onChange={(e) =>
                          setKnowledgeDocIds((prev) =>
                            e.target.checked
                              ? [...prev, doc.id]
                              : prev.filter((d) => d !== doc.id),
                          )
                        }
                        className="accent-primary"
                      />
                      <span className="min-w-0 flex-1 truncate">{doc.title}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {doc.char_count}字
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </Field>
          )}
          <Field label="输入">
            {({ id }) => (
              <Textarea
                id={id}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                rows={5}
                placeholder="输入你的问题或创作需求，回车发送（Shift+Enter 换行）…"
                disabled={streaming}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
              />
            )}
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void send()} loading={streaming} disabled={!input.trim()}>
              <Wand2 className="h-4 w-4" aria-hidden />
              发送
            </Button>
            {streaming && (
              <Button variant="outline" onClick={stop}>
                <Square className="h-4 w-4" aria-hidden />
                停止
              </Button>
            )}
          </div>
        </div>

        <div className="flex min-h-[420px] flex-col rounded-[var(--radius-card)] border border-border bg-surface">
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground">
                <Wand2 className="h-8 w-8" aria-hidden />
                <p className="text-sm">开始对话——支持连续多轮，上下文自动携带</p>
              </div>
            ) : (
              messages.map((m, i) => (
                <div
                  key={i}
                  className={cn(
                    "flex",
                    m.role === "user" ? "justify-end" : "justify-start",
                  )}
                >
                  <div
                    className={cn(
                      "max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
                      m.role === "user"
                        ? "bg-primary/12 text-foreground"
                        : "border border-border bg-surface-raised",
                    )}
                  >
                    {m.role === "assistant" && m.content ? (
                      <MarkdownContent content={m.content} />
                    ) : (
                      <span className="whitespace-pre-wrap">{m.content || "…"}</span>
                    )}
                  </div>
                </div>
              ))
            )}
            {messages.length > 0 && messages[messages.length - 1]?.role === "assistant" && (
              <div className="flex items-center justify-end gap-2">
                {knowledgeSources && knowledgeSources.length > 0 && (
                  <div className="flex flex-wrap justify-end gap-1.5">
                    {knowledgeSources.map((s) => (
                      <span
                        key={s.doc_id}
                        className="rounded-full border border-border bg-surface-raised px-2 py-0.5 text-xs text-muted-foreground"
                      >
                        参考 · {s.title}
                      </span>
                    ))}
                  </div>
                )}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    const last = messages[messages.length - 1];
                    if (last) {
                      void copyText(last.content);
                      toast.success("已复制到剪贴板");
                    }
                  }}
                >
                  <Copy className="h-4 w-4" aria-hidden />
                  复制回复
                </Button>
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>
      </div>
    </div>
  );
}
