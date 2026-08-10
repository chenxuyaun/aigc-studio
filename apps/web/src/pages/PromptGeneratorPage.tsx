import { useState } from "react";

import { Check, ChevronDown, Copy, Save, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { PageHeader } from "@/components/layout/PageHeader";
import { RoundtablePanel } from "@/components/creation/RoundtablePanel";
import { AppError, apiClient } from "@/lib/apiClient";
import { copyText } from "@/lib/clipboard";
import { cn } from "@/lib/cn";

interface StructuredPrompt {
  role: string;
  background: string;
  goal: string;
  input: string;
  steps: string[];
  output_format: string;
  constraints: string;
  quality_check: string;
  full_prompt: string;
}

const MODELS = [
  { v: "llm", label: "通用大语言模型" },
  { v: "image", label: "图片生成模型" },
  { v: "video", label: "视频生成模型" },
  { v: "speech", label: "语音生成模型" },
  { v: "code", label: "编程模型" },
];

export function PromptGeneratorPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    idea: "",
    scene: "",
    target_model: "llm",
    audience: "",
    style: "",
    tone: "",
    output_format: "",
    constraints: "",
  });
  const [advanced, setAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [genMode, setGenMode] = useState<"single" | "roundtable">("single");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<StructuredPrompt | null>(null);
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);

  function set<K extends keyof typeof form>(k: K, v: string) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  async function generate() {
    if (!form.idea.trim() || busy) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const res = await apiClient.post<StructuredPrompt>("/generations/prompt/generate", form);
      setResult(res);
    } catch (err) {
      setError(err instanceof AppError ? err.message : "生成失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!result) return;
    try {
      await apiClient.post("/prompts/", {
        title: (form.idea || "生成的提示词").slice(0, 60),
        content: result.full_prompt,
        prompt_type: form.target_model === "image" ? "image" : "text",
        is_public: false,
      });
      setSaved(true);
    } catch {
      setError("保存失败");
    }
  }

  return (
    <div>
      <PageHeader title="提示词生成器" description="填写想法，生成结构化提示词" />
      {/* 模式切换：单次生成 / 创作圆桌 */}
      <div className="flex gap-1 border-b border-border px-4 pt-2 md:px-6" role="tablist">
        {(
          [
            { key: "single", label: "⚡ 单次生成" },
            { key: "roundtable", label: "🎙️ 创作圆桌（多角色讨论定稿）" },
          ] as { key: "single" | "roundtable"; label: string }[]
        ).map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={genMode === t.key}
            onClick={() => setGenMode(t.key)}
            className={cn(
              "rounded-t-lg border-b-2 px-4 py-2 text-sm font-medium transition-colors",
              genMode === t.key
                ? "border-primary text-primary-text"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {genMode === "roundtable" ? (
        <div className="p-4 md:p-6">
          <RoundtablePanel
            domain="prompt"
            themeLabel="提示词目标"
            themePlaceholder="例如：给一家精品咖啡店写一条小红书种草文案的提示词…"
            extraLabel="附加要求（可选）"
            extraPlaceholder="目标模型（图片/视频/LLM）/ 输出格式 / 约束…"
          />
        </div>
      ) : (
      <div className="grid gap-4 p-4 md:grid-cols-2 md:p-6">
        {/* 表单 */}
        <div className="flex flex-col gap-4">
          <Field label="你的想法 / 目标" required hint="用一句话描述你想要什么">
            {({ id }) => (
              <Textarea
                id={id}
                value={form.idea}
                onChange={(e) => set("idea", e.target.value)}
                rows={3}
                placeholder="例如：给一家精品咖啡店写一条小红书种草文案"
              />
            )}
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="使用场景">
              {({ id }) => (
                <Input id={id} value={form.scene} onChange={(e) => set("scene", e.target.value)} placeholder="商品文案" />
              )}
            </Field>
            <Field label="目标模型">
              {({ id }) => (
                <select
                  id={id}
                  value={form.target_model}
                  onChange={(e) => set("target_model", e.target.value)}
                  className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {MODELS.map((m) => (
                    <option key={m.v} value={m.v}>
                      {m.label}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          </div>
          <Field label="目标受众">
            {({ id }) => (
              <Input id={id} value={form.audience} onChange={(e) => set("audience", e.target.value)} placeholder="年轻上班族" />
            )}
          </Field>

          <button
            onClick={() => setAdvanced((a) => !a)}
            className="flex items-center gap-1 self-start text-sm text-muted-foreground hover:text-foreground"
          >
            <ChevronDown className={`h-4 w-4 transition-transform ${advanced ? "rotate-180" : ""}`} />
            高级设置（风格 · 语气 · 格式 · 约束）
          </button>
          {advanced && (
            <div className="grid gap-3 rounded-xl border border-border bg-surface p-3">
              <div className="grid grid-cols-2 gap-3">
                <Field label="风格">
                  {({ id }) => <Input id={id} value={form.style} onChange={(e) => set("style", e.target.value)} />}
                </Field>
                <Field label="语气">
                  {({ id }) => <Input id={id} value={form.tone} onChange={(e) => set("tone", e.target.value)} />}
                </Field>
              </div>
              <Field label="期望输出格式">
                {({ id }) => <Input id={id} value={form.output_format} onChange={(e) => set("output_format", e.target.value)} placeholder="分段 / 列表 / JSON…" />}
              </Field>
              <Field label="约束条件">
                {({ id }) => <Textarea id={id} rows={2} value={form.constraints} onChange={(e) => set("constraints", e.target.value)} />}
              </Field>
            </div>
          )}

          <Button onClick={generate} loading={busy} disabled={!form.idea.trim()}>
            <Sparkles className="h-4 w-4" aria-hidden />
            生成提示词
          </Button>
          {error && (
            <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
              {error}
            </p>
          )}
        </div>

        {/* 结果 */}
        <div className="flex flex-col gap-3">
          {result ? (
            <>
              <Card className="p-4">
                <div className="mb-2 flex items-center justify-between">
                  <span className="font-mono-ui text-xs uppercase tracking-[0.14em] text-muted-foreground">
                    完整提示词
                  </span>
                  <div className="flex gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={async () => {
                        await copyText(result.full_prompt);
                        setCopied(true);
                        setTimeout(() => setCopied(false), 1500);
                      }}
                    >
                      {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                      {copied ? "已复制" : "复制"}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => void save()}>
                      <Save className="h-4 w-4" />
                      {saved ? "已保存" : "存到库"}
                    </Button>
                  </div>
                </div>
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono-ui text-[13px] leading-relaxed text-foreground">
                  {result.full_prompt}
                </pre>
              </Card>
              <div className="flex gap-2">
                <Button
                  className="flex-1"
                  variant="outline"
                  onClick={() => navigate("/create/image", { state: { prompt: result.full_prompt } })}
                >
                  <Sparkles className="h-4 w-4" aria-hidden />
                  用于图片生成
                </Button>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                <Part label="角色" text={result.role} />
                <Part label="目标" text={result.goal} />
                <Part label="输出格式" text={result.output_format} />
                <Part label="约束条件" text={result.constraints} />
              </div>
            </>
          ) : (
            <div className="flex min-h-72 items-center justify-center rounded-[var(--radius-card)] border border-dashed border-border text-sm text-muted-foreground">
              填写左侧想法，生成的结构化提示词会显示在这里
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  );
}

function Part({ label, text }: { label: string; text: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-3">
      <p className="font-mono-ui text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-sm text-foreground">{text}</p>
    </div>
  );
}
