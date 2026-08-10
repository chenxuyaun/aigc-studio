import { useState } from "react";

import { Clapperboard, Wand2 } from "lucide-react";
import { useLocation } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { PageHeader } from "@/components/layout/PageHeader";
import { RoundtablePanel } from "@/components/creation/RoundtablePanel";
import { useMediaTask } from "@/hooks/useMediaTask";
import { cn } from "@/lib/cn";

/** 视频 Provider 选项：grok 走 grok2api /videos/generations。 */
const MODEL_OPTS = [
  { v: "grok", label: "Grok（grok2api 视频）" },
];

export function VideoGenPage() {
  const location = useLocation();
  const handoff = (location.state as { prompt?: string; duration?: number } | null) ?? null;
  const [genMode, setGenMode] = useState<"single" | "roundtable">("single");
  const [prompt, setPrompt] = useState(handoff?.prompt ?? "");
  const [duration, setDuration] = useState(handoff?.duration ?? 5);
  const [model, setModel] = useState("grok");
  const task = useMediaTask("/generations/video/generate");

  function generate() {
    if (!prompt.trim() || task.busy) return;
    void task.run({ model, prompt, duration });
  }

  const isVideo = (task.result?.mime ?? "").startsWith("video/");

  return (
    <div>
      <PageHeader
        title="视频生成"
        description={
          "Grok 视频生成（grok2api）；上游不可用时明确报错，不产生占位结果"
        }
      />
      {/* 模式切换：直接生成 / 创作圆桌 */}
      <div className="flex gap-1 border-b border-border px-4 pt-2 md:px-6" role="tablist">
        {(
          [
            { key: "single", label: "⚡ 直接生成" },
            { key: "roundtable", label: "🎙️ 创作圆桌（多角色讨论分镜方案）" },
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
            domain="video"
            themeLabel="视频需求"
            themePlaceholder="例如：深夜便利店门口，猫和守夜人的 15 秒故事…"
            extraLabel="附加要求（可选）"
            extraPlaceholder="时长 / 平台（抖音/B站）/ 风格…"
            onFinal={(f) => {
              if (f.content) {
                setPrompt(f.content);
                setGenMode("single");
              }
            }}
          />
        </div>
      ) : (
      <div className="grid gap-4 p-4 md:grid-cols-[360px_1fr] md:p-6">
        <div className="flex flex-col gap-4">
          <Field label="模型 / Provider">
            {({ id }) => (
              <select
                id={id}
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {MODEL_OPTS.map((o) => (
                  <option key={o.v} value={o.v}>
                    {o.label}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="提示词" required>
            {({ id }) => (
              <Textarea
                id={id}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={6}
                placeholder="例如：一只猫在雪地里奔跑，电影感镜头"
              />
            )}
          </Field>
          <Field label="时长（秒）">
            {({ id }) => (
              <input
                id={id}
                type="range"
                min={3}
                max={15}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="w-full accent-primary"
              />
            )}
          </Field>
          <span className="-mt-2 font-mono-ui text-xs text-muted-foreground">{duration} 秒</span>
          <Button onClick={generate} loading={task.busy} disabled={!prompt.trim()}>
            <Wand2 className="h-4 w-4" aria-hidden />
            生成视频
          </Button>
          {task.busy && <ProgressBar progress={task.progress} status={task.status} />}
          {task.error && (
            <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
              {task.error}
            </p>
          )}
          {task.result && task.result.fallbackReason && (
            <p className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning">
              生成失败：{task.result.fallbackReason}
            </p>
          )}
        </div>

        <div
          className={cn(
            "flex min-h-80 flex-col items-center justify-center gap-3 rounded-[var(--radius-card)] border border-border bg-surface p-4",
          )}
        >
          {task.result ? (
            <>
              {isVideo ? (
                <video
                  src={task.result.assetUrl}
                  controls
                  autoPlay
                  loop
                  className="max-h-[64dvh] max-w-full rounded-lg"
                />
              ) : (
                <img
                  src={task.result.assetUrl}
                  alt={`视频封面：${prompt}`}
                  className="max-h-[64dvh] max-w-full rounded-lg"
                />
              )}
              <p className="font-mono-ui text-xs text-muted-foreground">
                {isVideo ? "真实视频" : "生成结果"} ·{" "}
                {task.result.mime}
              </p>
            </>
          ) : (
            <div className="flex flex-col items-center gap-2 text-muted-foreground">
              <Clapperboard className="h-8 w-8" aria-hidden />
              <p className="text-sm">生成的视频会显示在这里</p>
            </div>
          )}
        </div>
      </div>
      )}
    </div>
  );
}
