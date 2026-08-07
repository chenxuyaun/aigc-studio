import { useEffect, useRef, useState } from "react";

import type { CatalogItem, Skill } from "@aigc/shared-types";

import { useQuery } from "@tanstack/react-query";
import { Copy, Eraser, Square, Wand2, Wrench } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { MarkdownContent } from "@/components/ui/MarkdownContent";
import { PageHeader } from "@/components/layout/PageHeader";
import { useToast } from "@/components/ui/Toast";
import { usePersistedChat } from "@/hooks/usePersistedChat";
import { AppError, apiClient, streamSse } from "@/lib/apiClient";
import { copyText } from "@/lib/clipboard";
import { cn } from "@/lib/cn";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

const HISTORY_LIMIT = 6;

/** 技能指令 + 最近 N 轮历史 + 当前问题 拼接为单条 prompt。 */
function buildPrompt(instructions: string, messages: ChatMessage[], question: string): string {
  const parts: string[] = [];
  if (instructions.trim()) {
    parts.push(`【技能指令】\n${instructions.trim()}`);
  }
  const recent = messages.slice(-HISTORY_LIMIT * 2);
  if (recent.length > 0) {
    parts.push(
      `【对话历史】\n${recent.map((m) => `${m.role === "user" ? "用户" : "助手"}：${m.content}`).join("\n")}`,
    );
  }
  parts.push(`【任务】\n${question}`);
  return parts.join("\n\n");
}

export function SkillChatPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const [input, setInput] = useState("");
  const { messages, setMessages, clearChat: clearPersistedChat } = usePersistedChat(
    id ? `aigc-skill-chat-${id}` : "aigc-skill-chat",
  );
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fellBack, setFellBack] = useState(false);
  const [fallbackReason, setFallbackReason] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const skill = useQuery({
    queryKey: ["skills", id],
    queryFn: () => apiClient.get<Skill>(`/skills/${id}`),
    enabled: Boolean(id),
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
  const options: CatalogItem[] = catalog.data ?? [];
  const skillModel = skill.data?.model || "";
  const model = options.some((o) => o.id === skillModel || o.default_model === skillModel)
    ? skillModel
    : "";

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text || streaming) return;
    setError(null);
    setFellBack(false);
    setFallbackReason(null);

    const history = messages;
    setMessages([...history, { role: "user", content: text }]);
    setInput("");
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    let assistantText = "";
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
    try {
      const payload = buildPrompt(skill.data?.instructions ?? "", history, text);
      await streamSse(
        "/generations/text/generate",
        { model, prompt: payload, stream: true },
        (event) => {
          if (event.type === "chunk" && typeof event.content === "string") {
            assistantText += event.content;
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = { role: "assistant", content: assistantText };
              return next;
            });
          } else if (event.type === "done") {
            if (event.fallback === true) setFellBack(true);
            if (typeof event.fallbackReason === "string" && event.fallbackReason) {
              setFallbackReason(event.fallbackReason);
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
    clearPersistedChat();
    setError(null);
    setFellBack(false);
  }

  if (skill.isError) {
    return (
      <div className="p-6">
        <p className="text-sm text-danger">技能不存在或无权访问</p>
        <Button variant="outline" className="mt-3" onClick={() => navigate("/skills")}>
          返回技能库
        </Button>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={skill.data?.name ?? "运行技能"}
        description={skill.data?.description || "携带技能指令的多轮对话"}
        actions={
          <Button variant="outline" size="sm" onClick={() => navigate("/skills")}>
            返回技能库
          </Button>
        }
      />
      <div className="grid gap-4 p-4 md:grid-cols-[340px_1fr] md:p-6">
        <div className="flex flex-col gap-4">
          <div className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
            <h3 className="flex items-center gap-2 text-sm font-medium">
              <Wrench className="h-4 w-4" aria-hidden />
              {skill.data?.name}
            </h3>
            {skill.data?.instructions && (
              <p className="mt-2 line-clamp-6 whitespace-pre-wrap rounded-lg bg-surface-raised p-2.5 text-xs leading-relaxed text-muted-foreground">
                {skill.data.instructions}
              </p>
            )}
            <p className="mt-2 text-xs text-muted-foreground">
              类型：{skill.data?.skill_type}
            </p>
          </div>
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
          <Field label="输入" hint="携带技能指令与最近 6 轮对话">
            {({ id }) => (
              <Textarea
                id={id}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                rows={5}
                placeholder="交给技能处理的任务…"
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
              执行
            </Button>
            {streaming && (
              <Button variant="outline" onClick={stop}>
                <Square className="h-4 w-4" aria-hidden />
                停止
              </Button>
            )}
            {messages.length > 0 && (
              <Button variant="ghost" size="sm" onClick={clearChat}>
                <Eraser className="h-4 w-4" aria-hidden />
                清空
              </Button>
            )}
          </div>
        </div>

        <div className="flex min-h-[420px] flex-col rounded-[var(--radius-card)] border border-border bg-surface">
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-muted-foreground">
                <Wrench className="h-8 w-8" aria-hidden />
                <p className="text-sm">
                  开始使用「{skill.data?.name ?? "技能"}」——技能指令自动生效
                </p>
              </div>
            ) : (
              messages.map((m, i) => (
                <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
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
              <div className="flex justify-end">
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
