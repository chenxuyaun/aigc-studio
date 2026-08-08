import { useMemo, useState } from "react";

import { Music, Wand2 } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { PageHeader } from "@/components/layout/PageHeader";
import { useMediaTask } from "@/hooks/useMediaTask";

export function MusicGenPage() {
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState("facebook/musicgen-small");
  const [duration, setDuration] = useState(30);
  const task = useMediaTask("/generations/music/generate");

  // 音乐生成使用 HuggingFace MusicGen（需 HUGGINGFACE_TOKEN + 外网）
  const MODEL_OPTS = useMemo(
    () => [
      { v: "facebook/musicgen-small", label: "MusicGen Small（快，~30s）" },
      { v: "facebook/musicgen-medium", label: "MusicGen Medium（质量更好）" },
      { v: "facebook/musicgen-large", label: "MusicGen Large（最慢）" },
    ],
    [],
  );

  function generate() {
    if (!prompt.trim() || task.busy) return;
    void task.run({ model, prompt, duration_seconds: duration });
  }

  return (
    <div>
      <PageHeader
        title="音乐生成"
        description="MusicGen（HuggingFace）—— 用自然语言描述风格/情绪/乐器生成音乐"
      />
      <div className="grid gap-4 p-4 md:grid-cols-[360px_1fr] md:p-6">
        <div className="flex flex-col gap-4">
          <Field label="模型 / Provider" hint="HuggingFace MusicGen（需有效 HUGGINGFACE_TOKEN）">
            {({ id }) => (
              <select
                id={id}
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm"
              >
                {MODEL_OPTS.map((o) => (
                  <option key={o.v} value={o.v}>
                    {o.label}
                  </option>
                ))}
                {!MODEL_OPTS.some((o) => o.v === model) && (
                  <option value={model}>{model}</option>
                )}
              </select>
            )}
          </Field>
          <Field label="音乐描述" required hint="风格 / 情绪 / 乐器 / 速度，越具体越好">
            {({ id }) => (
              <Textarea
                id={id}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={6}
                placeholder="例如：温暖的钢琴与轻快吉他，民谣风格，黄昏的咖啡馆氛围，中速…"
              />
            )}
          </Field>
          <Field label={`目标时长 ${duration}s`} hint="MusicGen 由 token 预算控制，实际时长可能略短">
            {({ id }) => (
              <input
                id={id}
                type="range"
                min={5}
                max={120}
                step={5}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="w-full accent-primary"
              />
            )}
          </Field>
          <Button onClick={generate} loading={task.busy} disabled={!prompt.trim()}>
            <Wand2 className="h-4 w-4" aria-hidden />
            生成音乐
          </Button>
          {task.busy && <ProgressBar progress={task.progress} status={task.status} />}
          {task.error && (
            <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
              {task.error}
            </p>
          )}
        </div>

        <div className="flex min-h-80 flex-col items-center justify-center gap-4 rounded-[var(--radius-card)] border border-border bg-surface p-4">
          {task.result ? (
            <>
              <div className="grid h-20 w-20 place-items-center rounded-full bg-primary/12 text-primary-text">
                <Music className="h-9 w-9" aria-hidden />
              </div>
              <audio controls src={task.result.assetUrl} className="w-full max-w-md">
                你的浏览器不支持音频播放。
              </audio>
              <p className="font-mono-ui text-xs text-muted-foreground">
                MusicGen 生成的音乐已存入素材库
              </p>
            </>
          ) : (
            <div className="flex flex-col items-center gap-2 text-muted-foreground">
              <Music className="h-8 w-8" aria-hidden />
              <p className="text-sm">生成的音乐会显示在这里</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
