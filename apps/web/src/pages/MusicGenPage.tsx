import { useState } from "react";

import { Check, ClipboardCopy, Music, Wand2 } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { PageHeader } from "@/components/layout/PageHeader";
import { apiClient } from "@/lib/apiClient";

interface ComposeResult {
  title?: string;
  style_zh?: string;
  style_en?: string;
  lyrics?: string;
  tips?: string;
  provider?: string;
  error?: string;
  raw?: string;
}

const STYLES = ["流行", "古风", "中国风", "民谣", "R&B", "电子", "摇滚", "爵士", "嘻哈", "治愈系"];
const MOODS = ["治愈", "开心", "伤感", "热血", "浪漫", "思念", "励志", "安静"];

export function MusicGenPage() {
  const [theme, setTheme] = useState("");
  const [style, setStyle] = useState("流行");
  const [mood, setMood] = useState("治愈");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ComposeResult | null>(null);
  const [copied, setCopied] = useState("");

  async function compose() {
    if (!theme.trim() || busy) return;
    setBusy(true);
    setResult(null);
    try {
      const res = await apiClient.post<ComposeResult>("/generations/music/compose", {
        theme: theme.trim(),
        style,
        mood,
      });
      setResult(res);
    } catch (e) {
      setResult({ error: e instanceof Error ? e.message : "生成失败" });
    } finally {
      setBusy(false);
    }
  }

  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      setTimeout(() => setCopied(""), 2000);
    } catch {
      /* 剪贴板不可用时忽略 */
    }
  }

  const sunoPrompt = result
    ? `${result.style_en ?? ""}\n\n${result.lyrics ?? ""}`
    : "";

  return (
    <div>
      <PageHeader
        title="音乐创作助手"
        description="AI 写歌（免费）：输入主题 → 原创歌词 + 风格描述 → 复制到 Suno / 网易天音生成音乐"
      />
      <div className="grid gap-4 p-4 md:grid-cols-[360px_1fr] md:p-6">
        <div className="flex flex-col gap-4">
          <Field label="歌曲主题" required hint="一句话说清你想写什么歌">
            {({ id }) => (
              <Textarea
                id={id}
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
                rows={4}
                placeholder="例如：写给在远方打拼的恋人，我们隔着城市看同一片月亮…"
              />
            )}
          </Field>
          <Field label="风格">
            {({ id }) => (
              <select
                id={id}
                value={style}
                onChange={(e) => setStyle(e.target.value)}
                className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm"
              >
                {STYLES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="情绪">
            {({ id }) => (
              <select
                id={id}
                value={mood}
                onChange={(e) => setMood(e.target.value)}
                className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm"
              >
                {MOODS.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Button onClick={compose} loading={busy} disabled={!theme.trim()}>
            <Wand2 className="h-4 w-4" aria-hidden />
            AI 写歌（免费）
          </Button>
          {busy && <p className="text-xs text-muted-foreground">AI 创作中，约 10-30 秒…</p>}
          {result?.error && (
            <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
              {result.error}
            </p>
          )}
          <div className="rounded-lg bg-muted/40 p-3 text-xs leading-relaxed text-muted-foreground">
            <p className="mb-1 font-semibold text-foreground">💡 怎么出歌（全免费）</p>
            <p>1. 点「AI 写歌」拿到歌词和风格</p>
            <p>2. 复制「Suno 粘贴包」</p>
            <p>3. 打开 <span className="font-mono">suno.com</span>（注册送免费额度）或网易云「天音 AI」</p>
            <p>4. 粘贴 → 选风格 → 生成 🎵</p>
          </div>
        </div>

        <div className="flex min-h-80 flex-col gap-3 rounded-[var(--radius-card)] border border-border bg-surface p-4">
          {result ? (
            <>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h2 className="font-display text-lg font-semibold">{result.title ?? "无标题"}</h2>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {result.style_zh ?? ""} · 生成模型：{result.provider ?? ""}
                  </p>
                </div>
                <Button size="sm" variant="ghost" onClick={() => copy(sunoPrompt, "suno")}>
                  {copied === "suno" ? (
                    <Check className="h-3.5 w-3.5" aria-hidden />
                  ) : (
                    <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
                  )}
                  {copied === "suno" ? "已复制" : "复制 Suno 粘贴包"}
                </Button>
              </div>

              <div className="rounded-lg bg-muted/40 p-3">
                <p className="mb-1 text-xs font-semibold text-foreground">🎤 歌词</p>
                <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-foreground">
                  {result.lyrics ?? ""}
                </pre>
              </div>

              <div className="rounded-lg bg-muted/40 p-3">
                <p className="mb-1 text-xs font-semibold text-foreground">🎧 风格（英文，Suno 用）</p>
                <p className="text-sm">{result.style_en ?? ""}</p>
              </div>

              {result.tips && (
                <p className="text-xs text-muted-foreground">💡 {result.tips}</p>
              )}
            </>
          ) : (
            <div className="flex flex-col items-center gap-2 text-muted-foreground">
              <Music className="h-8 w-8" aria-hidden />
              <p className="text-sm">输入主题，AI 为你写一首原创歌</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
