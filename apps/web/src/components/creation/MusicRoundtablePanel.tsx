import { useEffect, useRef, useState } from "react";

import { Check, ClipboardCopy, Send, UsersRound } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { streamSse } from "@/lib/apiClient";
import { shareUrl } from "@/lib/share";

// ---------- 类型（原 MusicGenPage 内联） ----------

export interface RoundtableCast {
  name: string;
  field: string;
  persona: string;
  icon: string;
  order: number;
  finalizer: boolean;
}

export interface RoundtableResult {
  title?: string;
  style_zh?: string;
  style_en?: string;
  lyrics?: string;
  chords?: string;
  arrangement?: string;
  error?: string;
  final?: RoundtableResult;
}

const STYLES = ["流行", "古风", "中国风", "民谣", "R&B", "电子", "摇滚", "爵士", "嘻哈", "治愈系"];

const SPEAKER_META: Record<string, { icon: string; cls: string }> = {
  作词人: { icon: "✍️", cls: "bg-sky-500/10 text-sky-600" },
  作曲家: { icon: "🎼", cls: "bg-violet-500/10 text-violet-600" },
  制作人: { icon: "🎧", cls: "bg-emerald-500/10 text-emerald-600" },
  乐评人: { icon: "👀", cls: "bg-rose-500/10 text-rose-600" },
};

// 歌词朗读（Web Speech，零后端）+ 下载
function speakLyrics(text: string) {
  try {
    const u = new SpeechSynthesisUtterance(text.replace(/【[^】]*】/g, "").replace(/\n+/g, "，"));
    u.lang = "zh-CN";
    u.rate = 0.85;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  } catch {
    /* 浏览器不支持时忽略 */
  }
}

function stopSpeak() {
  try {
    window.speechSynthesis.cancel();
  } catch {
    /* 忽略 */
  }
}

function downloadTxt(filename: string, text: string) {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

interface Props {
  /** 定稿后「送 1对1 讨论室打磨」（父组件切 tab 并带定稿上下文）。 */
  onSendToDiscuss?: (title: string, lyrics: string, arrangement: string) => void;
  /** 外部预填风格（如 compose 结果「送圆桌开会」）；变化时同步到风格选择。 */
  incomingStyle?: string;
  /** 外部预填主题（同上）。 */
  incomingTheme?: string;
}

/**
 * 音乐创作圆桌（多角色真讨论 + 定稿 + 追问 + 自动入库）。
 * 从 MusicGenPage 内联实现抽取：自持全部会议状态，父组件只负责挂载与联动。
 */
export function MusicRoundtablePanel({ onSendToDiscuss, incomingStyle, incomingTheme }: Props) {
  const [rtTheme, setRtTheme] = useState("");
  const [rtStyle, setRtStyle] = useState("");
  const [rtQuick, setRtQuick] = useState(false); // 快速模式：3 轮迷你讨论
  const [rtUseWeb, setRtUseWeb] = useState(false); // 知识库不足时联网搜索兜底
  const [rtBusy, setRtBusy] = useState(false);
  const [rtRounds, setRtRounds] = useState<{ speaker: string; content: string }[]>([]);
  const [rtSpeaking, setRtSpeaking] = useState(""); // 正在发言的角色
  const [rtFinal, setRtFinal] = useState<RoundtableResult | null>(null);
  const [rtCast, setRtCast] = useState<RoundtableCast[]>([]); // 按主题定制的阵容
  const [rtChecks, setRtChecks] = useState<string[]>([]); // 定稿自检警告
  const [rtWorkId, setRtWorkId] = useState(""); // 已保存作品 id
  const [rtKbTitles, setRtKbTitles] = useState<string[]>([]); // 已参考素材
  const [rtError, setRtError] = useState("");
  const [rtQuestion, setRtQuestion] = useState(""); // 定稿后追问
  const [copied, setCopied] = useState("");
  const rtAbortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  // 外部预填主题/风格（compose 结果「送圆桌开会」）
  useEffect(() => {
    if (incomingTheme) setRtTheme(incomingTheme);
  }, [incomingTheme]);
  useEffect(() => {
    if (incomingStyle) setRtStyle(incomingStyle);
  }, [incomingStyle]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [rtRounds, rtSpeaking]);

  async function roundtable() {
    if (!rtTheme.trim() || rtBusy) return;
    setRtBusy(true);
    setRtRounds([]);
    setRtSpeaking("");
    setRtFinal(null);
    setRtCast([]);
    setRtChecks([]);
    setRtWorkId("");
    setRtError("");
    const abort = new AbortController();
    rtAbortRef.current = abort;
    try {
      await streamSse(
        "/generations/music/roundtable/stream",
        { theme: rtTheme.trim(), style: rtStyle, quick: rtQuick, use_web: rtUseWeb },
        (ev) => {
          if (ev.type === "materials" && Array.isArray(ev.titles)) {
            setRtKbTitles(ev.titles as string[]);
          } else if (ev.type === "cast" && Array.isArray(ev.cast)) {
            setRtCast(ev.cast as RoundtableCast[]);
          } else if (ev.type === "round_start" && typeof ev.speaker === "string") {
            setRtSpeaking(ev.speaker);
          } else if (
            ev.type === "round" &&
            typeof ev.speaker === "string" &&
            typeof ev.content === "string"
          ) {
            setRtSpeaking("");
            setRtRounds((prev) => [
              ...prev,
              { speaker: ev.speaker as string, content: ev.content as string },
            ]);
          } else if (ev.type === "final_start") {
            setRtSpeaking("");
          } else if (ev.type === "final" && ev.final) {
            setRtSpeaking("");
            setRtFinal(ev.final as RoundtableResult);
            if (Array.isArray(ev.checks)) setRtChecks(ev.checks as string[]);
            if (typeof ev.work_id === "string") setRtWorkId(ev.work_id);
          } else if (ev.type === "error" && typeof ev.error === "string") {
            setRtError(ev.error);
          }
        },
        abort.signal,
      );
    } catch (e) {
      setRtError(e instanceof Error ? e.message : "圆桌会议失败");
    } finally {
      setRtBusy(false);
      setRtSpeaking("");
    }
  }

  // 定稿后追问：全员基于讨论+定稿回应，产出新定稿
  async function followup() {
    const q = rtQuestion.trim();
    if (!q || rtBusy || !rtFinal || !rtCast.length) return;
    setRtBusy(true);
    setRtQuestion("");
    setRtChecks([]);
    setRtWorkId("");
    setRtError("");
    const abort = new AbortController();
    rtAbortRef.current = abort;
    try {
      await streamSse(
        "/generations/music/roundtable/followup",
        {
          theme: rtTheme.trim(),
          style: rtStyle,
          cast: rtCast,
          rounds: rtRounds,
          final: rtFinal,
          question: q,
          use_web: rtUseWeb,
        },
        (ev) => {
          if (ev.type === "round_start" && typeof ev.speaker === "string") {
            setRtSpeaking(ev.speaker);
          } else if (
            ev.type === "round" &&
            typeof ev.speaker === "string" &&
            typeof ev.content === "string"
          ) {
            setRtSpeaking("");
            setRtRounds((prev) => [
              ...prev,
              { speaker: ev.speaker as string, content: ev.content as string },
            ]);
          } else if (ev.type === "final" && ev.final) {
            setRtSpeaking("");
            setRtFinal(ev.final as RoundtableResult);
            if (Array.isArray(ev.checks)) setRtChecks(ev.checks as string[]);
            if (typeof ev.work_id === "string") setRtWorkId(ev.work_id);
          } else if (ev.type === "error" && typeof ev.error === "string") {
            setRtError(ev.error);
          }
        },
        abort.signal,
      );
    } catch (e) {
      setRtError(e instanceof Error ? e.message : "追问失败");
    } finally {
      setRtBusy(false);
      setRtSpeaking("");
    }
  }

  const rtMetaFor = (speaker: string): { icon: string; cls: string } => {
    const c = rtCast.find((x) => x.name === speaker);
    if (c) {
      return { icon: c.icon || "🎙️", cls: "bg-primary/10 text-primary-text" };
    }
    return SPEAKER_META[speaker] ?? { icon: "🎙️", cls: "bg-muted text-muted-foreground" };
  };

  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      setTimeout(() => setCopied(""), 2000);
    } catch {
      /* 剪贴板不可用时忽略 */
    }
  }

  return (
    <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-[280px_1fr]">
      {/* 圆桌侧栏 */}
      <div className="flex flex-col gap-4">
        <Field label="创作主题" required hint="给个想法就行，剩下的交给他们讨论">
          {({ id }) => (
            <Textarea
              id={id}
              value={rtTheme}
              onChange={(e) => setRtTheme(e.target.value)}
              rows={4}
              placeholder="例如：写给在外打拼的人，想家但还在坚持…"
            />
          )}
        </Field>
        <Field label="风格基调（可选）">
          {({ id }) => (
            <select
              id={id}
              value={rtStyle}
              onChange={(e) => setRtStyle(e.target.value)}
              className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm"
            >
              <option value="">自由（由讨论决定）</option>
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
            checked={rtQuick}
            onChange={(e) => setRtQuick(e.target.checked)}
            className="h-3.5 w-3.5 accent-[var(--primary)]"
          />
          ⚡ 快速模式（3 轮迷你讨论，约 25 秒；完整模式约 60 秒）
        </label>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={rtUseWeb}
            onChange={(e) => setRtUseWeb(e.target.checked)}
            className="h-3.5 w-3.5 accent-[var(--primary)]"
          />
          🌐 知识库不足时联网搜索（新鲜题材，先提炼后注入）
        </label>
        <Button onClick={roundtable} loading={rtBusy} disabled={!rtTheme.trim()}>
          <UsersRound className="h-4 w-4" aria-hidden />
          开圆桌会议
        </Button>
        {rtBusy && (
          <p className="text-xs text-muted-foreground">
            {rtQuick ? "快速讨论中，约 25 秒…" : "四位创作者讨论中：交锋约 20-60 秒…"}
          </p>
        )}
        <div className="rounded-lg bg-muted/40 p-3 text-xs leading-relaxed text-muted-foreground">
          <p className="mb-1 font-semibold text-foreground">🎙️ 会议规则</p>
          <p>· 阵容按主题定制，每人实时生成</p>
          <p>· 评审挑刺必须给替代方向</p>
          <p>· 修正必须换全新意象</p>
          <p>· 定稿自动存入「我的创作」</p>
          <p className="mt-1">你只给主题，他们吵完出定稿</p>
        </div>
      </div>

      {/* 圆桌会议区 */}
      <div className="flex min-h-[480px] flex-col rounded-[var(--radius-card)] border border-border bg-surface">
        <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
          <span className="flex items-center gap-2 text-sm font-semibold">
            <UsersRound className="h-4 w-4 text-primary-text" aria-hidden />
            创作圆桌
            {rtStyle && (
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary-text">
                {rtStyle}
              </span>
            )}
          </span>
        </div>

        <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
          {rtRounds.length === 0 && !rtSpeaking && !rtFinal && !rtError && !rtBusy ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 text-muted-foreground">
              <UsersRound className="h-8 w-8" aria-hidden />
              <p className="text-sm">给个主题，四位创作者会围坐讨论，吵出定稿</p>
            </div>
          ) : rtError && rtRounds.length === 0 ? (
            <p className="rounded-lg bg-destructive/5 border border-destructive/40 p-3 text-sm text-destructive">
              {rtError}
            </p>
          ) : (
            <>
              {rtError && (
                <p className="rounded-lg bg-destructive/5 border border-destructive/40 p-3 text-sm text-destructive">
                  {rtError}
                </p>
              )}
              {rtKbTitles.length > 0 && (
                <p className="rounded-lg bg-sky-500/5 border border-sky-500/25 px-3 py-2 text-xs text-sky-600">
                  📚 已参考素材：{rtKbTitles.join("、")}
                </p>
              )}
              {/* 定制阵容：按主题选出的 4 位专业角色 */}
              {rtCast.length > 0 && (
                <div className="flex flex-col gap-2 rounded-lg border border-border bg-muted/20 p-3">
                  <p className="text-xs font-semibold text-muted-foreground">
                    🎬 本场会议阵容（按主题定制）
                  </p>
                  <div className="grid gap-1.5 sm:grid-cols-2">
                    {rtCast.map((c) => (
                      <div key={c.name} className="flex items-start gap-2 rounded-md bg-surface px-2.5 py-1.5 text-xs">
                        <span className="text-sm">{c.icon}</span>
                        <div className="min-w-0">
                          <p className="font-semibold">
                            {c.name}
                            <span className="ml-1.5 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary-text">
                              {c.field}
                            </span>
                            {c.finalizer && (
                              <span className="ml-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] text-amber-600">
                                主理人
                              </span>
                            )}
                          </p>
                          {c.persona && (
                            <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{c.persona}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {/* 讨论轮次 */}
              <div className="flex flex-col gap-2.5">
                {rtRounds.map((r, i) => {
                  const meta = rtMetaFor(r.speaker);
                  return (
                    <div key={i} className="flex items-start gap-2">
                      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-muted text-sm">
                        {meta.icon}
                      </span>
                      <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-muted px-3.5 py-2 text-sm leading-relaxed">
                        <span className={`mr-2 rounded px-1.5 py-0.5 text-[10px] font-semibold ${meta.cls}`}>
                          {r.speaker}
                        </span>
                        {r.content}
                      </div>
                    </div>
                  );
                })}
                {rtSpeaking && (
                  <div className="flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-primary-text">
                    <span className="h-3 w-3 animate-pulse rounded-full bg-primary" />
                    {rtSpeaking} 正在思考发言…（每句都是实时生成的）
                  </div>
                )}
                {rtBusy && !rtSpeaking && rtRounds.length === 0 && !rtCast.length && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                    会议筹备中…
                  </div>
                )}
              </div>

              {/* 定稿：讨论全部结束后出炉 */}
              {rtFinal && (
                <div className="mt-2 flex flex-col gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-bold">
                      🎬 定稿《{rtFinal.title ?? "未命名"}》
                    </p>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        copy(
                          `${rtFinal?.style_en ?? ""}\n\n${rtFinal?.lyrics ?? ""}\n\n${rtFinal?.arrangement ?? ""}`,
                          "rt",
                        )
                      }
                    >
                      {copied === "rt" ? (
                        <>
                          <Check className="h-3.5 w-3.5" aria-hidden /> 已复制
                        </>
                      ) : (
                        <>
                          <ClipboardCopy className="h-3.5 w-3.5" aria-hidden /> 复制定稿
                        </>
                      )}
                    </Button>
                  </div>
                  <div className="rounded-lg bg-muted/40 p-3">
                    <p className="mb-1 text-xs font-semibold">🎤 歌词</p>
                    <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                      {rtFinal.lyrics ?? ""}
                    </pre>
                  </div>
                  {rtFinal.chords && (
                    <div className="rounded-lg bg-muted/40 p-3">
                      <p className="mb-1 text-xs font-semibold">🎸 和弦谱（弹唱/Suno 直接用）</p>
                      <pre className="whitespace-pre-wrap font-mono text-sm leading-relaxed">
                        {rtFinal.chords}
                      </pre>
                    </div>
                  )}
                  {/* 工具行：朗读 / 下载 / 分享 */}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        if (rtFinal?.lyrics) {
                          speakLyrics(rtFinal.lyrics);
                          setCopied("speak");
                        }
                      }}
                    >
                      🔊 朗读歌词
                    </Button>
                    <Button size="sm" variant="ghost" onClick={stopSpeak}>
                      ⏹ 停止
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        downloadTxt(
                          `${rtFinal?.title ?? "song"}.txt`,
                          `${rtFinal?.style_en ?? ""}\n\n${rtFinal?.lyrics ?? ""}\n\n${rtFinal?.chords ?? ""}\n\n${rtFinal?.arrangement ?? ""}`,
                        )
                      }
                    >
                      ⬇️ 下载 .txt
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={async () => {
                        if (!rtWorkId) return;
                        try {
                          await navigator.clipboard.writeText(shareUrl("music", rtWorkId));
                          setCopied("share");
                        } catch {
                          /* 忽略 */
                        }
                      }}
                    >
                      {copied === "share" ? (
                        <>
                          <Check className="h-3.5 w-3.5" aria-hidden /> 已复制分享链接
                        </>
                      ) : (
                        <>🔗 复制分享链接</>
                      )}
                    </Button>
                  </div>
                  {rtFinal.arrangement && (
                    <div className="rounded-lg bg-muted/40 p-3">
                      <p className="mb-1 text-xs font-semibold">🎧 编曲思路</p>
                      <p className="text-sm">{rtFinal.arrangement}</p>
                    </div>
                  )}
                  {rtFinal.style_en && (
                    <p className="text-xs text-muted-foreground">
                      🎼 Suno 风格：{rtFinal.style_en}
                    </p>
                  )}
                  {/* 保存状态 */}
                  {rtWorkId ? (
                    <p className="rounded-lg bg-emerald-500/10 px-3 py-2 text-xs text-emerald-600">
                      ✅ 已自动存入「我的创作」（/works）
                    </p>
                  ) : (
                    <p className="rounded-lg bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                      定稿会自动存入「我的创作」
                    </p>
                  )}
                  {/* 送 1对1 讨论室打磨 */}
                  <Button
                    size="sm"
                    variant="ghost"
                    title="把定稿带进 1对1 讨论室，和 AI 单独打磨细节"
                    onClick={() => {
                      onSendToDiscuss?.(
                        rtFinal?.title ?? "未命名",
                        rtFinal?.lyrics ?? "",
                        rtFinal?.arrangement ?? "",
                      );
                    }}
                  >
                    💬 送 1对1 打磨
                  </Button>
                  {/* 定稿自检警告 */}
                  {rtChecks.length > 0 && (
                    <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-600">
                      <p className="font-semibold">⚠️ 定稿自检</p>
                      <ul className="mt-0.5 list-disc pl-4">
                        {rtChecks.map((c, i) => (
                          <li key={i}>{c}</li>
                        ))}
                      </ul>
                      <p className="mt-1">在下面追问一句，让创作团队补齐</p>
                    </div>
                  )}
                  {/* 定稿后追问：全员再回应一轮 */}
                  <div className="flex items-end gap-2 border-t border-border pt-3">
                    <Textarea
                      value={rtQuestion}
                      onChange={(e) => setRtQuestion(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          void followup();
                        }
                      }}
                      rows={2}
                      placeholder="对定稿还不满意？追问一句（如：副歌再燃一点 / 桥段太满 / 换种情绪），全员会再讨论一版…"
                      aria-label="定稿追问"
                    />
                    <Button
                      onClick={followup}
                      loading={rtBusy}
                      disabled={!rtQuestion.trim()}
                    >
                      <Send className="h-4 w-4" aria-hidden />
                      追问
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
