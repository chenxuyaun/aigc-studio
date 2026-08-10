import { useEffect, useRef, useState } from "react";

import {
  Check,
  ClipboardCopy,
  Eraser,
  MessagesSquare,
  Music,
  Send,
  Wand2,
} from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { PageHeader } from "@/components/layout/PageHeader";
import { apiClient } from "@/lib/apiClient";
import { MusicRoundtablePanel } from "@/components/creation/MusicRoundtablePanel";
import { cn } from "@/lib/cn";

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

interface DiscussMsg {
  role: "user" | "assistant";
  content: string;
}

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

interface DiscussMsg {
  role: "user" | "assistant";
  content: string;
}

const STYLES = ["流行", "古风", "中国风", "民谣", "R&B", "电子", "摇滚", "爵士", "嘻哈", "治愈系"];
const MOODS = ["治愈", "开心", "伤感", "热血", "浪漫", "思念", "励志", "安静"];

type Mode = "compose" | "discuss" | "roundtable";

export function MusicGenPage() {
  const [mode, setMode] = useState<Mode>("compose");

  // ---- AI 写歌（单次） ----
  const [theme, setTheme] = useState("");
  const [style, setStyle] = useState("流行");
  const [mood, setMood] = useState("治愈");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ComposeResult | null>(null);
  const [copied, setCopied] = useState("");

  // ---- 音乐讨论室（多轮对话） ----
  const [dStyle, setDStyle] = useState("");
  const [dUseWeb, setDUseWeb] = useState(false); // 首轮注入联网素材
  const [rtIncoming, setRtIncoming] = useState(""); // 「送圆桌开会」预填风格
  const [rtIncomingTheme, setRtIncomingTheme] = useState(""); // 「送圆桌开会」预填主题
  const [messages, setMessages] = useState<DiscussMsg[]>([]);
  const [dInput, setDInput] = useState("");
  const [dBusy, setDBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, dBusy]);

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

  async function discuss() {
    const text = dInput.trim();
    if (!text || dBusy) return;
    const history: DiscussMsg[] = [...messages, { role: "user", content: text }];
    setMessages(history);
    setDInput("");
    setDBusy(true);
    try {
      const res = await apiClient.post<{ reply: string; provider?: string }>(
        "/generations/music/discuss",
        { messages: history, style: dStyle, use_web: dUseWeb },
      );
      setMessages((prev) => [...prev, { role: "assistant", content: res.reply }]);
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `⚠️ ${e instanceof Error ? e.message : "讨论失败，请重试"}` },
      ]);
    } finally {
      setDBusy(false);
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
        description="AI 写歌（免费）：单次生成歌词 / 与 AI 讨论词曲与编曲 → 复制到 Suno / 网易天音生成音乐"
      />

      {/* 模式切换 */}
      <div className="flex gap-1 border-b border-border px-4 pt-2 md:px-6" role="tablist">
        {(
          [
            { key: "compose", label: "🎵 AI 写歌（单次生成）" },
            { key: "discuss", label: "💬 音乐讨论室（1对1）" },
            { key: "roundtable", label: "🎙️ 多角色圆桌（4人讨论）" },
          ] as { key: Mode; label: string }[]
        ).map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={mode === t.key}
            onClick={() => setMode(t.key)}
            className={cn(
              "rounded-t-lg border-b-2 px-4 py-2 text-sm font-medium transition-colors",
              mode === t.key
                ? "border-primary text-primary-text"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {mode === "compose" ? (
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
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="ghost" onClick={() => copy(sunoPrompt, "suno")}>
                      {copied === "suno" ? (
                        <Check className="h-3.5 w-3.5" aria-hidden />
                      ) : (
                        <ClipboardCopy className="h-3.5 w-3.5" aria-hidden />
                      )}
                      {copied === "suno" ? "已复制" : "复制 Suno 粘贴包"}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      title="把这首的灵感送进多角色圆桌，让创作团队再吵出一版"
                      onClick={() => {
                        setMode("roundtable");
                        setRtIncomingTheme(theme.trim());
                        if (style) setRtIncoming(style);
                      }}
                    >
                      🎙️ 送圆桌开会
                    </Button>
                  </div>
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
      ) : mode === "discuss" ? (
        <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-[280px_1fr]">
          {/* 讨论室侧栏 */}
          <div className="flex flex-col gap-4">
            <Field label="固定风格（可选）" hint="锁定风格后，讨论与修改都贴合该风格">
              {({ id }) => (
                <select
                  id={id}
                  value={dStyle}
                  onChange={(e) => setDStyle(e.target.value)}
                  className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm"
                >
                  <option value="">不固定（自由讨论）</option>
                  {STYLES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={dUseWeb}
                onChange={(e) => setDUseWeb(e.target.checked)}
                className="h-3.5 w-3.5 accent-[var(--primary)]"
              />
              🌐 开场注入素材（知识库 + 联网新鲜题材）
            </label>
            <Button
              variant="ghost"
              onClick={() => {
                setMessages([]);
                setDInput("");
              }}
              disabled={messages.length === 0}
            >
              <Eraser className="h-4 w-4" aria-hidden />
              清空讨论
            </Button>
            <div className="rounded-lg bg-muted/40 p-3 text-xs leading-relaxed text-muted-foreground">
              <p className="mb-1 font-semibold text-foreground">💬 可以这样聊</p>
              <p>· “想写一首给深夜下班的人的歌” → 先聊方向</p>
              <p>· “选第 2 个方向” / “直接写” → 马上出完整歌词</p>
              <p>· “副歌 hook 再简洁一点，像自言自语”</p>
              <p>· “换成古风重写主歌，但保留副歌”</p>
              <p>· “这首歌用 C 大调 84 BPM 怎么编？”</p>
            </div>
          </div>

          {/* 聊天区 */}
          <div className="flex min-h-[480px] flex-col rounded-[var(--radius-card)] border border-border bg-surface">
            <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
              <span className="flex items-center gap-2 text-sm font-semibold">
                <MessagesSquare className="h-4 w-4 text-primary-text" aria-hidden />
                音乐讨论室
                {dStyle && (
                  <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary-text">
                    {dStyle}
                  </span>
                )}
              </span>
              {messages.length > 0 && (
                <button
                  onClick={() => {
                    setMessages([]);
                    setDInput("");
                  }}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  清空
                </button>
              )}
            </div>

            <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
              {messages.length === 0 ? (
                <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
                  <Music className="h-8 w-8" aria-hidden />
                  <p className="text-sm">和 AI 聊聊你的音乐想法，从一首歌的灵感聊到编曲细节</p>
                </div>
              ) : (
                messages.map((m, i) => (
                  <div
                    key={i}
                    className={cn(
                      "flex flex-col gap-1",
                      m.role === "user" ? "items-end" : "items-start",
                    )}
                  >
                    <div
                      className={cn(
                        "max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed",
                        m.role === "user"
                          ? "rounded-br-sm bg-primary text-primary-foreground"
                          : "rounded-bl-sm bg-muted",
                      )}
                    >
                      {m.content}
                    </div>
                    {m.role === "assistant" && (
                      <button
                        onClick={() => copy(m.content, `msg-${i}`)}
                        className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
                      >
                        {copied === `msg-${i}` ? (
                          <>
                            <Check className="h-3 w-3" aria-hidden /> 已复制
                          </>
                        ) : (
                          <>
                            <ClipboardCopy className="h-3 w-3" aria-hidden /> 复制
                          </>
                        )}
                      </button>
                    )}
                  </div>
                ))
              )}
              {dBusy && (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                  创作伙伴思考中…
                </div>
              )}
              <div ref={bottomRef} />
            </div>

            <div className="flex items-end gap-2 border-t border-border p-3">
              <Textarea
                value={dInput}
                onChange={(e) => setDInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void discuss();
                  }
                }}
                rows={2}
                placeholder="聊聊你的音乐想法…（Enter 发送，Shift+Enter 换行）"
                aria-label="音乐讨论输入"
              />
              <Button onClick={discuss} loading={dBusy} disabled={!dInput.trim()}>
                <Send className="h-4 w-4" aria-hidden />
                发送
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <MusicRoundtablePanel
          incomingTheme={rtIncomingTheme}
          incomingStyle={rtIncoming}
          onSendToDiscuss={(title, lyrics, arrangement) => {
            setMode("discuss");
            setMessages([
              {
                role: "user",
                content: `这是我刚生成的定稿《${title}》，想和你打磨细节：

【定稿《${title}》】
${lyrics}${arrangement ? `
🎧 ${arrangement}` : ""}`,
              },
            ]);
          }}
        />
      )}
    </div>
  );
}
