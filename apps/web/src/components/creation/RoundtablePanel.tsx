import { useEffect, useRef, useState } from "react";

import { Check, ClipboardCopy, UsersRound } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { streamSse } from "@/lib/apiClient";

interface CastMember {
  name: string;
  field: string;
  persona: string;
  icon: string;
  order: number;
  finalizer: boolean;
}

interface PanelFinal {
  title?: string;
  content?: string;
  style?: string;
}

interface Props {
  domain: string;
  themeLabel?: string;
  themePlaceholder?: string;
  extraLabel?: string;
  extraPlaceholder?: string;
  /** 定稿产出后回调（可回填生成表单） */
  onFinal?: (final: PanelFinal) => void;
}

/** 通用创作圆桌：定制阵容 → 逐轮真讨论 → 主编把关定稿（任意内容创作领域）。 */
export function RoundtablePanel({
  domain,
  themeLabel = "创作需求",
  themePlaceholder = "一句话说清你想创作什么…",
  extraLabel = "附加要求（可选）",
  extraPlaceholder = "风格/受众/约束等…",
  onFinal,
}: Props) {
  const [theme, setTheme] = useState("");
  const [extra, setExtra] = useState("");
  const [quick, setQuick] = useState(false);
  const [useWeb, setUseWeb] = useState(false); // 知识库不足时联网搜索兜底
  const [busy, setBusy] = useState(false);
  const [rounds, setRounds] = useState<{ speaker: string; content: string }[]>([]);
  const [speaking, setSpeaking] = useState("");
  const [cast, setCast] = useState<CastMember[]>([]);
  const [final, setFinal] = useState<PanelFinal | null>(null);
  const [error, setError] = useState("");
  const [kbTitles, setKbTitles] = useState<string[]>([]); // 已参考知识库素材
  const [copied, setCopied] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [rounds, speaking]);

  async function start() {
    if (!theme.trim() || busy) return;
    setBusy(true);
    setRounds([]);
    setSpeaking("");
    setCast([]);
    setFinal(null);
    setError("");
    const abort = new AbortController();
    abortRef.current = abort;
    try {
      await streamSse(
        "/roundtable/stream",
        { domain, theme: theme.trim(), extra: extra.trim(), quick, use_web: useWeb },
        (ev) => {
          if (ev.type === "domain" && Array.isArray(ev.materials)) {
            setKbTitles(ev.materials as string[]);
          } else if (ev.type === "cast" && Array.isArray(ev.cast)) {
            setCast(ev.cast as CastMember[]);
          } else if (ev.type === "round_start" && typeof ev.speaker === "string") {
            setSpeaking(ev.speaker);
          } else if (
            ev.type === "round" &&
            typeof ev.speaker === "string" &&
            typeof ev.content === "string"
          ) {
            setSpeaking("");
            setRounds((prev) => [
              ...prev,
              { speaker: ev.speaker as string, content: ev.content as string },
            ]);
          } else if (ev.type === "final" && ev.final) {
            setSpeaking("");
            const f = ev.final as PanelFinal;
            setFinal(f);
            onFinal?.(f);
          } else if (ev.type === "error" && typeof ev.error === "string") {
            setError(ev.error);
          }
        },
        abort.signal,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "圆桌会议失败");
    } finally {
      setBusy(false);
      setSpeaking("");
    }
  }

  const metaFor = (speaker: string): { icon: string; cls: string } => {
    const c = cast.find((x) => x.name === speaker);
    return c
      ? { icon: c.icon || "🎙️", cls: "bg-primary/10 text-primary-text" }
      : { icon: "🎙️", cls: "bg-muted text-muted-foreground" };
  };

  async function copyResult(label: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(label);
      setTimeout(() => setCopied(""), 2000);
    } catch {
      /* 忽略 */
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
      {/* 侧栏 */}
      <div className="flex flex-col gap-4">
        <Field label={themeLabel} required hint="给个想法就行，剩下的交给他们讨论">
          {({ id }) => (
            <Textarea
              id={id}
              value={theme}
              onChange={(e) => setTheme(e.target.value)}
              rows={4}
              placeholder={themePlaceholder}
            />
          )}
        </Field>
        <Field label={extraLabel}>
          {({ id }) => (
            <Textarea
              id={id}
              value={extra}
              onChange={(e) => setExtra(e.target.value)}
              rows={2}
              placeholder={extraPlaceholder}
            />
          )}
        </Field>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={quick}
            onChange={(e) => setQuick(e.target.checked)}
            className="h-3.5 w-3.5 accent-[var(--primary)]"
          />
          ⚡ 快速模式（3 轮迷你讨论）
        </label>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={useWeb}
            onChange={(e) => setUseWeb(e.target.checked)}
            className="h-3.5 w-3.5 accent-[var(--primary)]"
          />
          🌐 知识库不足时联网搜索（先提炼后注入）
        </label>
        <Button onClick={start} loading={busy} disabled={!theme.trim()}>
          <UsersRound className="h-4 w-4" aria-hidden />
          开圆桌会议
        </Button>
        {busy && (
          <p className="text-xs text-muted-foreground">
            {quick ? "快速讨论中，约 25-40 秒…" : "创作团队讨论中，约 40-90 秒…"}
          </p>
        )}
        <div className="rounded-lg bg-muted/40 p-3 text-xs leading-relaxed text-muted-foreground">
          <p className="mb-1 font-semibold text-foreground">🎙️ 会议规则</p>
          <p>· 阵容按需求定制，每人实时生成</p>
          <p>· 评审挑刺必须给替代方向</p>
          <p>· 修正必须换全新方案</p>
          <p>· 定稿由主理人主编把关</p>
        </div>
      </div>

      {/* 会议区 */}
      <div className="flex min-h-[480px] flex-col rounded-[var(--radius-card)] border border-border bg-surface">
        <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
          <span className="flex items-center gap-2 text-sm font-semibold">
            <UsersRound className="h-4 w-4 text-primary-text" aria-hidden />
            创作圆桌
          </span>
        </div>
        <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
          {error && (
            <p className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
              {error}
            </p>
          )}
          {kbTitles.length > 0 && (
            <p className="rounded-lg bg-sky-500/5 border border-sky-500/25 px-3 py-2 text-xs text-sky-600">
              📚 已参考素材：{kbTitles.join("、")}
            </p>
          )}
          {cast.length > 0 && (
            <div className="flex flex-col gap-2 rounded-lg border border-border bg-muted/20 p-3">
              <p className="text-xs font-semibold text-muted-foreground">
                🎬 本场会议阵容（按需求定制）
              </p>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {cast.map((c) => (
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
          <div className="flex flex-col gap-2.5">
            {rounds.map((r, i) => {
              const meta = metaFor(r.speaker);
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
            {speaking && (
              <div className="flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-primary-text">
                <span className="h-3 w-3 animate-pulse rounded-full bg-primary" />
                {speaking} 正在思考发言…（每句都是实时生成的）
              </div>
            )}
            {busy && !speaking && rounds.length === 0 && !cast.length && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                会议筹备中…
              </div>
            )}
          </div>

          {/* 定稿 */}
          {final && !final.title && !final.content && !(final as { error?: string }).error && null}
          {final && ((final as { error?: string }).error || final.title || final.content) && (
            <div className="mt-2 flex flex-col gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
              <div className="flex items-start justify-between gap-2">
                <p className="font-bold">🎬 定稿{final.title ? `《${final.title}》` : ""}</p>
                {final.content && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => copyResult("final", `${final.title ?? ""}\n\n${final.content ?? ""}\n\n${final.style ?? ""}`)}
                  >
                    {copied === "final" ? (
                      <>
                        <Check className="h-3.5 w-3.5" aria-hidden /> 已复制
                      </>
                    ) : (
                      <>
                        <ClipboardCopy className="h-3.5 w-3.5" aria-hidden /> 复制定稿
                      </>
                    )}
                  </Button>
                )}
              </div>
              {(final as { error?: string }).error ? (
                <p className="rounded-lg bg-destructive/5 border border-destructive/40 p-3 text-xs text-destructive">
                  {(final as { error?: string }).error}
                </p>
              ) : (
                <>
                  <div className="rounded-lg bg-muted/40 p-3">
                    <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{final.content ?? ""}</pre>
                  </div>
                  {final.style && <p className="text-xs text-muted-foreground">🎨 {final.style}</p>}
                </>
              )}
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
