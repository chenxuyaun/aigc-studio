import { useMemo, useState } from "react";


import { AudioLines, Wand2 } from "lucide-react";
import { useLocation } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { PageHeader } from "@/components/layout/PageHeader";
import { useMediaTask } from "@/hooks/useMediaTask";

export function AudioGenPage() {
  const location = useLocation();
  const handoff =
    (location.state as { prompt?: string; text?: string; voice?: string } | null) ?? null;
  const [text, setText] = useState(handoff?.text ?? handoff?.prompt ?? "");
  const [voice, setVoice] = useState(handoff?.voice ?? "default");
  const [speed, setSpeed] = useState(1);
  const [model, setModel] = useState("edge_tts");
  const task = useMediaTask("/generations/audio/generate");

  // 语音只支持内置 provider（edge_tts 免费真实 TTS / HF 需外网）：
  // 不展示文本类 DB Provider（Grok/cpa 无语音端点）。
  const MODEL_OPTS = useMemo(
    () => [
      { v: "edge_tts", label: "Edge TTS（微软免费）" },
      { v: "huggingface", label: "HuggingFace mms-tts（需外网）" },
    ],
    [],
  );

  function generate() {
    if (!text.trim() || task.busy) return;
    void task.run({ model, text, voice, speed });
  }

  return (
    <div>
      <PageHeader title="语音生成" description="Edge TTS 免费真实合成；HuggingFace 需外网（mms-tts）" />
      <div className="grid gap-4 p-4 md:grid-cols-[360px_1fr] md:p-6">
        <div className="flex flex-col gap-4">
          <Field label="模型 / Provider" hint="Edge TTS 免费；HuggingFace 需外网">
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
          <Field label="文本内容" required>
            {({ id }) => (
              <Textarea
                id={id}
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={7}
                placeholder="输入需要转成语音的文本…"
              />
            )}
          </Field>
          <Field label="发音人">
            {({ id }) => (
              <select
                id={id}
                value={voice}
                onChange={(e) => setVoice(e.target.value)}
                className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm"
              >
                <option value="default">默认</option>
                <option value="female">女声</option>
                <option value="male">男声</option>
                <option value="child">童声</option>
              </select>
            )}
          </Field>
          <Field label={`语速 ${speed.toFixed(1)}x`}>
            {({ id }) => (
              <input
                id={id}
                type="range"
                min={0.5}
                max={2}
                step={0.1}
                value={speed}
                onChange={(e) => setSpeed(Number(e.target.value))}
                className="w-full accent-primary"
              />
            )}
          </Field>
          <Button onClick={generate} loading={task.busy} disabled={!text.trim()}>
            <Wand2 className="h-4 w-4" aria-hidden />
            生成语音
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
              <div className="grid h-20 w-20 place-items-center rounded-full bg-primary/12 text-primary">
                <AudioLines className="h-9 w-9" aria-hidden />
              </div>
              <audio controls src={task.result.assetUrl} className="w-full max-w-md">
                你的浏览器不支持音频播放。
              </audio>
              <p className="font-mono-ui text-xs text-muted-foreground">
                Edge TTS / HuggingFace 合成真实语音
              </p>
            </>
          ) : (
            <div className="flex flex-col items-center gap-2 text-muted-foreground">
              <AudioLines className="h-8 w-8" aria-hidden />
              <p className="text-sm">生成的语音会显示在这里</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
