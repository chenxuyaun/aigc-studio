import { useState } from "react";

import { Check, Copy, Wand2 } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field, Textarea } from "@/components/ui/Field";
import { PageHeader } from "@/components/layout/PageHeader";
import { AppError, apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";
import { copyText } from "@/lib/clipboard";

interface DiagnosisItem {
  dimension: string;
  score: number;
  level: string;
  note: string;
}
interface OptimizeResult {
  score_before: number;
  score_after: number;
  diagnosis: DiagnosisItem[];
  suggestions: string[];
  concise: string;
  standard: string;
  professional: string;
}

const VERSIONS = [
  { key: "concise", label: "精简版" },
  { key: "standard", label: "标准版" },
  { key: "professional", label: "专业版" },
] as const;

function levelColor(level: string): string {
  if (level === "优秀") return "text-success";
  if (level === "一般") return "text-warning";
  return "text-danger";
}
function barColor(level: string): string {
  if (level === "优秀") return "bg-success";
  if (level === "一般") return "bg-warning";
  return "bg-danger";
}

export function PromptOptimizerPage() {
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<OptimizeResult | null>(null);
  const [version, setVersion] = useState<(typeof VERSIONS)[number]["key"]>("standard");
  const [copied, setCopied] = useState(false);

  async function optimize() {
    if (!prompt.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await apiClient.post<OptimizeResult>("/generations/prompt/optimize", { prompt });
      setResult(res);
    } catch (err) {
      setError(err instanceof AppError ? err.message : "优化失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  const optimizedText = result ? result[version] : "";

  return (
    <div>
      <PageHeader title="提示词优化器" description="粘贴已有提示词，诊断并优化" />
      <div className="grid gap-4 p-4 md:grid-cols-2 md:p-6">
        <div className="flex flex-col gap-4">
          <Field label="原始提示词" required>
            {({ id }) => (
              <Textarea
                id={id}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={10}
                className="min-h-52"
                placeholder="把你现有的提示词粘贴到这里…"
              />
            )}
          </Field>
          <Button onClick={optimize} loading={busy} disabled={!prompt.trim()}>
            <Wand2 className="h-4 w-4" aria-hidden />
            诊断并优化
          </Button>
          {error && (
            <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
              {error}
            </p>
          )}

          {result && (
            <Card className="p-4">
              <div className="mb-3 flex items-center justify-between text-sm">
                <span className="text-muted-foreground">综合评分</span>
                <span className="font-mono-ui tabular-nums">
                  <span className="text-muted-foreground">{result.score_before}</span>
                  <span className="mx-1.5 text-muted-foreground">→</span>
                  <span className="text-lg font-bold text-success">{result.score_after}</span>
                </span>
              </div>
              <div className="space-y-2.5">
                {result.diagnosis.map((d) => (
                  <div key={d.dimension}>
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-foreground">{d.dimension}</span>
                      <span className={cn("font-mono-ui tabular-nums", levelColor(d.level))}>
                        {d.score} · {d.level}
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn("h-full", barColor(d.level))}
                        style={{ width: `${d.score}%` }}
                      />
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">{d.note}</p>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>

        <div className="flex flex-col gap-3">
          {result ? (
            <>
              <div>
                <p className="mb-2 font-mono-ui text-xs uppercase tracking-[0.14em] text-muted-foreground">
                  优化建议
                </p>
                <ul className="space-y-1.5">
                  {result.suggestions.map((s, i) => (
                    <li key={i} className="flex gap-2 text-sm text-foreground">
                      <span className="mt-1.5 h-1.5 w-1.5 flex-none rounded-full bg-primary" />
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
              <Card className="flex min-h-0 flex-1 flex-col p-0">
                <div className="flex items-center justify-between border-b border-border p-2 pl-3">
                  <div className="flex gap-1">
                    {VERSIONS.map((v) => (
                      <button
                        key={v.key}
                        onClick={() => setVersion(v.key)}
                        className={cn(
                          "rounded-lg px-3 py-1.5 text-sm transition-colors",
                          version === v.key
                            ? "bg-secondary font-medium text-foreground"
                            : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {v.label}
                      </button>
                    ))}
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={async () => {
                      await copyText(optimizedText);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 1500);
                    }}
                  >
                    {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                    {copied ? "已复制" : "复制"}
                  </Button>
                </div>
                <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words p-3 font-mono-ui text-[13px] leading-relaxed text-foreground">
                  {optimizedText}
                </pre>
              </Card>
            </>
          ) : (
            <div className="flex min-h-72 items-center justify-center rounded-[var(--radius-card)] border border-dashed border-border text-sm text-muted-foreground">
              诊断结果与优化版本会显示在这里
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
