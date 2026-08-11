import { useEffect, useState } from "react";

import { Copy, FileText } from "lucide-react";
import { useParams } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import type { Prompt } from "@aigc/shared-types";
import { AppError, apiClient } from "@/lib/apiClient";
import { copyText } from "@/lib/clipboard";

/** 公开分享页：无需登录即可查看分享的提示词（仅 is_public 项可读）。 */
export function SharedPromptPage() {
  const { promptId } = useParams<{ promptId: string }>();
  const toast = useToast();
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!promptId) return;
    let cancelled = false;
    void (async () => {
      try {
        const data = await apiClient.get<Prompt>(`/prompts/shared/${promptId}`);
        if (!cancelled) setPrompt(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof AppError ? err.message : "提示词不存在或已设为私有");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [promptId]);

  return (
    <div className="mx-auto flex min-h-dvh max-w-2xl flex-col bg-background px-4 py-8">
      <div className="mb-6 flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-[10px] bg-gradient-to-br from-primary to-primary-hover text-sm font-extrabold text-primary-foreground">
          A
        </span>
        <span className="font-bold tracking-tight">SAIOS · 分享</span>
      </div>

      {error ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl border border-border bg-surface p-10 text-center">
          <FileText className="h-8 w-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">{error}</p>
          <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
            重试
          </Button>
        </div>
      ) : !prompt ? (
        <div className="h-40 animate-pulse rounded-2xl bg-muted" />
      ) : (
        <div className="rounded-2xl border border-border bg-surface p-6">
          <h1 className="text-xl font-semibold">{prompt.title}</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            {prompt.prompt_type} · 作者分享
          </p>
          <pre className="mt-4 whitespace-pre-wrap rounded-xl bg-muted p-4 font-mono text-sm leading-relaxed">
            {prompt.content}
          </pre>
          <div className="mt-4 flex justify-end">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void copyText(prompt.content);
                toast.success("已复制到剪贴板");
              }}
            >
              <Copy className="h-4 w-4" aria-hidden />
              复制提示词
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
