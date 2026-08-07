import { useEffect, useRef, useState } from "react";

import type { Agent, CatalogItem } from "@aigc/shared-types";

import { useQuery } from "@tanstack/react-query";
import { Bot, Copy, Eraser, Square, Wand2 } from "lucide-react";
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


export function AgentChatPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const [input, setInput] = useState("");
  const { messages, setMessages, clearChat: clearPersistedChat } = usePersistedChat(
    id ? `aigc-agent-chat-${id}` : "aigc-agent-chat",
  );
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fellBack, setFellBack] = useState(false);
  const [fallbackReason, setFallbackReason] = useState<string | null>(null);
  const [toolLine, setToolLine] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const agent = useQuery({
    queryKey: ["agents", id],
    queryFn: () => apiClient.get<Agent>(`/agents/${id}`),
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
  const agentModel = agent.data?.model || "";
  const model = options.some((o) => o.id === agentModel || o.default_model === agentModel)
    ? agentModel
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
    setToolLine(null);
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);
    try {
      // 工具调用需要结构化 messages（system + 历史 + 当前问题）
      const payload = {
        model,
        messages: [
          ...(agent.data?.system_prompt
            ? [{ role: "system" as const, content: agent.data.system_prompt }]
            : []),
          ...history.map((m) => ({ role: m.role, content: m.content })),
          { role: "user" as const, content: text },
        ],
      };
      await streamSse(
        "/generations/text/agent/chat",
        payload,
        (event) => {
          if (event.type === "tool") {
            // 工具调用过程展示
            setToolLine(
              event.status === "running"
                ? `🔧 正在调用 ${event.name}…`
                : `✅ ${event.name} 完成`,
            );
          } else if (event.type === "chunk" && typeof event.content === "string") {
            assistantText += event.content;
            setMessages((prev) => {
              const next = [...prev];
              next[next.length - 1] = { role: "assistant", content: assistantText };
              return next;
            });
          } else if (event.type === "done") {
            if (typeof event.error === "string" && event.error) {
              setFellBack(true);
              setFallbackReason(event.error);
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
      setToolLine(null);
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

  if (agent.isError) {
    return (
      <div className="p-6">
        <p className="text-sm text-danger">Agent 不存在或无权访问</p>
        <Button variant="outline" className="mt-3" onClick={() => navigate("/agents")}>
          返回 Agent 库
        </Button>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title={agent.data?.name ?? "运行 Agent"}
        description={agent.data?.description || "携带系统设定的多轮对话"}
        actions={
          <Button variant="outline" size="sm" onClick={() => navigate("/agents")}>
            返回 Agent 库
          </Button>
        }
      />
      <div className="grid gap-4 p-4 md:grid-cols-[340px_1fr] md:p-6">
        <div className="flex flex-col gap-4">
          <div className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
            <h3 className="flex items-center gap-2 text-sm font-medium">
              <Bot className="h-4 w-4" aria-hidden />
              {agent.data?.name}
            </h3>
            {agent.data?.system_prompt && (
              <p className="mt-2 line-clamp-6 whitespace-pre-wrap rounded-lg bg-surface-raised p-2.5 text-xs leading-relaxed text-muted-foreground">
                {agent.data.system_prompt}
              </p>
            )}
            <p className="mt-2 text-xs text-muted-foreground">
              模型：{agent.data?.model || "默认"} · 类型：{agent.data?.agent_type}
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
          {toolLine && (
            <p className="rounded-lg bg-primary/5 px-3 py-2 text-xs text-muted-foreground">
              {toolLine}
            </p>
          )}
          <Field label="输入" hint="携带 Agent 系统设定与最近 6 轮对话">
            {({ id }) => (
              <Textarea
                id={id}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                rows={5}
                placeholder="向 Agent 提问…"
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
                <Bot className="h-8 w-8" aria-hidden />
                <p className="text-sm">
                  开始与「{agent.data?.name ?? "Agent"}」对话——系统设定自动生效
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
