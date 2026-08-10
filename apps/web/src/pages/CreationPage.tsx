import { useState } from "react";

import { ArrowRight, BookOpen, Check, ClipboardCopy, RefreshCw, Sparkles, Theater, Users } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Field, Textarea } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

interface CastCharacter {
  name: string;
  role: string;
  description: string;
  personality: string;
  first_mes: string;
  asset_id?: string;
  reused?: boolean;
}

interface CreationPlan {
  group_name?: string;
  genre?: string;
  logline?: string;
  characters?: CastCharacter[];
  provider?: string;
  materials_hits?: boolean;
  error?: string;
  raw?: string;
}

interface ScriptScene {
  scene_no: number;
  location: string;
  characters: string;
  beat: string;
  dialogue_hint: string;
}

interface ScriptAct {
  act_no: number;
  act_title: string;
  act_summary: string;
  scenes: ScriptScene[];
}

interface ScriptPlan {
  title?: string;
  genre?: string;
  logline?: string;
  acts?: ScriptAct[];
  finale_hint?: string;
  provider?: string;
  error?: string;
  raw?: string;
}

interface ReviewResult {
  score?: number;
  strengths?: string[];
  weaknesses?: string[];
  suggestions?: string[];
  provider?: string;
  error?: string;
  raw?: string;
}

function scriptToMarkdown(s: ScriptPlan): string {
  const lines: string[] = [];
  lines.push(`《${s.title ?? "未命名"}》${s.genre ? `（${s.genre}）` : ""}`);
  if (s.logline) lines.push(`\n${s.logline}`);
  for (const a of s.acts ?? []) {
    lines.push(`\n## 第${a.act_no}幕《${a.act_title}》`);
    if (a.act_summary) lines.push(a.act_summary);
    for (const sc of a.scenes ?? []) {
      lines.push(`\n【第${sc.scene_no}场】${sc.location}`);
      if (sc.characters) lines.push(`出场：${sc.characters}`);
      if (sc.beat) lines.push(`节拍：${sc.beat}`);
      if (sc.dialogue_hint) lines.push(`台词提示：${sc.dialogue_hint}`);
    }
  }
  if (s.finale_hint) lines.push(`\n结局走向：${s.finale_hint}`);
  return lines.join("\n");
}

const THEME_IDEAS = [
  "深夜食堂式的都市温情故事，一位女店主和她的常客们",
  "民国上海滩：落魄侦探追查一起歌女失踪案",
  "太空科考站遭遇未知信号，六名船员各怀心事",
  "江南小镇的梨园班主，收留了一位失忆的神秘客人",
];

export function CreationPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [theme, setTheme] = useState("");
  const [busy, setBusy] = useState(false);
  const [setupBusy, setSetupBusy] = useState(false);
  const [plan, setPlan] = useState<CreationPlan | null>(null);
  const [script, setScript] = useState<ScriptPlan | null>(null);
  const [scriptVariants, setScriptVariants] = useState<ScriptPlan[] | null>(null);
  const [variantIdx, setVariantIdx] = useState(0);
  const [scriptBusy, setScriptBusy] = useState(false);
  const [review, setReview] = useState<ReviewResult | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [copied, setCopied] = useState("");

  async function cast() {
    if (!theme.trim() || busy) return;
    setBusy(true);
    setPlan(null);
    setScript(null);
    try {
      const res = await apiClient.post<CreationPlan>("/creation/plan", {
        theme: theme.trim(),
      });
      if (res.error) {
        setPlan(res);
        return;
      }
      setPlan(res);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "AI 选角失败");
    } finally {
      setBusy(false);
    }
  }

  async function genScript(variants = 1) {
    if (!plan || scriptBusy || !plan.characters?.length) return;
    setScriptBusy(true);
    setScript(null);
    setScriptVariants(null);
    setReview(null);
    try {
      const res = await apiClient.post<ScriptPlan | { variants: ScriptPlan[] }>(
        "/creation/script",
        { theme: theme.trim(), plan, variants },
      );
      if ("variants" in res && Array.isArray(res.variants)) {
        setScriptVariants(res.variants);
        setVariantIdx(0);
        const first = res.variants[0];
        if (first?.error) {
          setScript(first);
        }
      } else {
        const single = res as ScriptPlan;
        if (single.error) {
          setScript(single);
          return;
        }
        setScript(single);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "剧本生成失败");
    } finally {
      setScriptBusy(false);
    }
  }

  const activeScript: ScriptPlan | null = scriptVariants
    ? (scriptVariants[variantIdx] ?? null)
    : script;

  async function reviewScript() {
    if (!activeScript || reviewBusy || activeScript.error) return;
    setReviewBusy(true);
    setReview(null);
    try {
      const res = await apiClient.post<ReviewResult>("/creation/review", {
        theme: theme.trim(),
        plan,
        script: activeScript,
      });
      if (res.error) {
        setReview(res);
        return;
      }
      setReview(res);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "评审失败");
    } finally {
      setReviewBusy(false);
    }
  }

  async function copyScript() {
    if (!script) return;
    try {
      await navigator.clipboard.writeText(scriptToMarkdown(script));
      setCopied("script");
      setTimeout(() => setCopied(""), 2000);
    } catch {
      /* 剪贴板不可用时忽略 */
    }
  }

  async function setup() {
    if (!plan || setupBusy || !plan.characters?.length) return;
    setSetupBusy(true);
    try {
      const res = await apiClient.post<{
        chat_id: string;
        group_name: string;
        reused_count?: number;
      }>("/creation/setup", { theme: theme.trim(), plan });
      const reused = res.reused_count ?? 0;
      const reusedHint =
        reused > 0 ? `，复用已有角色 ${reused} 个（未重复创建）` : "";
      toast.success(`群「${res.group_name}」已建好，共 ${plan.characters?.length ?? 0} 位角色入群${reusedHint}，开始共创吧！`);
      navigate(`/roleplay?chat=${res.chat_id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "建组失败");
    } finally {
      setSetupBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="AI 导演工作室"
        description="给一个主题 → AI 选角 → 自动建群 → 群内分角色共创，一步步完成作品"
      />
      <div className="grid gap-4 p-4 md:grid-cols-[360px_1fr] md:p-6">
        {/* 左栏：主题输入 */}
        <div className="flex flex-col gap-4">
          <Field label="创作主题" required hint="一句话说清你想创作什么故事">
            {({ id }) => (
              <Textarea
                id={id}
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
                rows={5}
                placeholder="例如：深夜食堂式的都市温情故事，一位女店主和她的常客们…"
              />
            )}
          </Field>
          <div className="flex flex-wrap gap-2">
            {THEME_IDEAS.map((t) => (
              <button
                key={t}
                onClick={() => setTheme(t)}
                className="rounded-full border border-border bg-surface px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-primary-text"
              >
                {t.slice(0, 14)}…
              </button>
            ))}
          </div>
          <Button onClick={cast} loading={busy} disabled={!theme.trim()}>
            <Sparkles className="h-4 w-4" aria-hidden />
            AI 选角（生成角色方案）
          </Button>
          {busy && (
            <p className="text-xs text-muted-foreground">导演思考中：分析主题、设计角色，约 15-40 秒…</p>
          )}
          {plan?.error && (
            <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
              AI 输出解析失败，请换一种主题描述重试。
              {plan.raw && <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap">{plan.raw}</pre>}
            </div>
          )}
        </div>

        {/* 右栏：方案预览 */}
        <div className="flex flex-col gap-4">
          {!plan ? (
            <div className="flex min-h-[420px] flex-col items-center justify-center gap-3 rounded-[var(--radius-card)] border border-dashed border-border bg-surface/50 p-6 text-center">
              <Theater className="h-10 w-10 text-muted-foreground/50" aria-hidden />
              <p className="text-sm text-muted-foreground">
                输入主题，点击「AI 选角」，
                <br />
                导演会给出群名、故事梗概和角色阵容
              </p>
            </div>
          ) : plan.error ? (
            <div className="flex min-h-[420px] items-center justify-center rounded-[var(--radius-card)] border border-dashed border-border bg-surface/50 p-6 text-center text-sm text-muted-foreground">
              方案解析失败，请重试
            </div>
          ) : (
            <div className="flex flex-col gap-4">
              {/* 项目头 */}
              <div className="rounded-[var(--radius-card)] border border-border bg-surface p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-bold">{plan.group_name}</h2>
                      {plan.genre && (
                        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary-text">
                          {plan.genre}
                        </span>
                      )}
                    </div>
                    <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                      {plan.logline}
                    </p>
                    {plan.provider && (
                      <p className="mt-2 text-[11px] text-muted-foreground/60">
                        导演模型：{plan.provider}
                        {plan.materials_hits && (
                          <span
                            className="ml-2 rounded-full bg-sky-500/10 px-2 py-0.5 text-sky-600"
                            title="选角前检索了你的知识库文档，角色设定基于资料生成"
                          >
                            📚 已参考知识库资料
                          </span>
                        )}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <Button variant="ghost" size="sm" onClick={cast} loading={busy} title="重新选角">
                      <RefreshCw className="h-4 w-4" aria-hidden />
                      重选
                    </Button>
                  </div>
                </div>
              </div>

              {/* 角色阵容 */}
              <div className="grid gap-3 sm:grid-cols-2">
                {(plan.characters ?? []).map((c, i) => (
                  <div
                    key={`${c.name}-${i}`}
                    className="flex flex-col gap-2 rounded-[var(--radius-card)] border border-border bg-surface p-4"
                  >
                    <div className="flex items-center gap-2">
                      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary/12 text-sm font-bold text-primary-text">
                        {c.name?.slice(0, 1) ?? "?"}
                      </span>
                      <span className="font-semibold">{c.name}</span>
                      {c.reused && (
                        <span
                          className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-600"
                          title="已有同名角色卡，直接复用未重复创建"
                        >
                          已有·复用
                        </span>
                      )}
                      {!c.reused && c.asset_id && (
                        <span
                          className="rounded-full bg-violet-500/10 px-2 py-0.5 text-[11px] text-violet-600"
                          title="AI 从你的演员库（已有角色卡）中选中，建组时直接复用"
                        >
                          🎭 演员库
                        </span>
                      )}
                      <span className="ml-auto rounded-full bg-secondary px-2 py-0.5 text-[11px] text-secondary-foreground">
                        {c.role}
                      </span>
                    </div>
                    <p className="text-xs leading-relaxed text-muted-foreground">{c.description}</p>
                    <p className="text-xs text-primary-text/80">性格：{c.personality}</p>
                    <p className="rounded-lg bg-muted px-3 py-2 text-xs italic leading-relaxed">
                      “{c.first_mes}”
                    </p>
                  </div>
                ))}
              </div>

              {/* 剧本初稿 */}
              <div className="flex flex-col gap-3 rounded-[var(--radius-card)] border border-border bg-surface p-5">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="flex items-center gap-2 text-sm font-semibold">
                    <BookOpen className="h-4 w-4 text-primary-text" aria-hidden />
                    剧本初稿 · 分幕大纲
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {scriptVariants && (
                      <div
                        className="flex items-center rounded-lg border border-border p-0.5 text-xs"
                        role="tablist"
                        aria-label="大纲版本切换"
                      >
                        {scriptVariants.map((v, i) => (
                          <button
                            key={i}
                            role="tab"
                            aria-selected={variantIdx === i}
                            onClick={() => setVariantIdx(i)}
                            className={`rounded-md px-2 py-1 ${
                              variantIdx === i
                                ? "bg-primary/12 text-primary-text"
                                : "text-muted-foreground hover:text-foreground"
                            }`}
                          >
                            {v.error ? "版失败" : `版 ${i + 1}${v.title ? `·${v.title}` : ""}`}
                          </button>
                        ))}
                      </div>
                    )}
                    {activeScript && !activeScript.error && (
                      <>
                        <Button size="sm" variant="ghost" onClick={copyScript}>
                          {copied === "script" ? (
                            <>
                              <Check className="h-3.5 w-3.5" aria-hidden /> 已复制
                            </>
                          ) : (
                            <>
                              <ClipboardCopy className="h-3.5 w-3.5" aria-hidden /> 复制大纲
                            </>
                          )}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={reviewScript} loading={reviewBusy}>
                          评审
                        </Button>
                      </>
                    )}
                    <Button
                      size="sm"
                      onClick={() => void genScript(scriptVariants ? 3 : 1)}
                      loading={scriptBusy}
                    >
                      {scriptVariants ? "三版重生成" : "生成剧本初稿"}
                    </Button>
                    {!scriptVariants && (
                      <Button size="sm" variant="outline" onClick={() => void genScript(3)} disabled={scriptBusy}>
                        三版对比
                      </Button>
                    )}
                  </div>
                </div>

                {!scriptVariants && !script && !scriptBusy && (
                  <p className="text-xs text-muted-foreground">
                    按当前角色阵容生成 3 幕分幕大纲（每场含冲突节拍与台词提示），可直接在群聊里照着演；「三版对比」并行出 3 版供挑选
                  </p>
                )}
                {scriptBusy && (
                  <p className="text-xs text-muted-foreground">编剧构思中：搭结构、埋伏笔，约 20-50 秒…</p>
                )}
                {scriptVariants?.length === 0 && (
                  <p className="rounded-lg bg-destructive/5 border border-destructive/40 p-3 text-xs text-destructive">
                    三版都生成失败，请重试。
                  </p>
                )}
                {activeScript?.error && (
                  <p className="rounded-lg bg-destructive/5 border border-destructive/40 p-3 text-xs text-destructive">
                    AI 输出解析失败，请重试。
                    {activeScript.raw && (
                      <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap">{activeScript.raw}</pre>
                    )}
                  </p>
                )}
                {activeScript && !activeScript.error && (
                  <div className="flex flex-col gap-3">
                    <div>
                      <h4 className="font-bold">
                        《{activeScript.title ?? "未命名"}》
                        {activeScript.genre && (
                          <span className="ml-2 rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary-text">
                            {activeScript.genre}
                          </span>
                        )}
                      </h4>
                      {activeScript.logline && (
                        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{activeScript.logline}</p>
                      )}
                      {activeScript.provider && (
                        <p className="mt-1 text-[11px] text-muted-foreground/60">编剧模型：{activeScript.provider}</p>
                      )}
                    </div>

                    {(activeScript.acts ?? []).map((a) => (
                      <div key={a.act_no} className="rounded-lg border border-border bg-muted/30 p-3">
                        <p className="text-sm font-semibold">
                          第{a.act_no}幕《{a.act_title}》
                        </p>
                        {a.act_summary && (
                          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{a.act_summary}</p>
                        )}
                        <div className="mt-2 flex flex-col gap-2">
                          {(a.scenes ?? []).map((sc) => (
                            <div key={sc.scene_no} className="rounded-md bg-surface p-2.5 text-xs">
                              <p className="font-semibold text-primary-text">
                                第{sc.scene_no}场 · {sc.location}
                                {sc.characters && (
                                  <span className="ml-2 font-normal text-muted-foreground">
                                    出场：{sc.characters}
                                  </span>
                                )}
                              </p>
                              {sc.beat && <p className="mt-1 leading-relaxed">{sc.beat}</p>}
                              {sc.dialogue_hint && (
                                <p className="mt-1 italic text-muted-foreground">💬 {sc.dialogue_hint}</p>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}

                    {activeScript.finale_hint && (
                      <p className="rounded-lg bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
                        结局走向：{activeScript.finale_hint}
                      </p>
                    )}
                  </div>
                )}

                {/* AI 评审 */}
                {review && !review.error && (
                  <div className="flex flex-col gap-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                    <p className="flex items-center gap-2 text-sm font-semibold">
                      🎬 制片人评审
                      {typeof review.score === "number" && (
                        <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs">
                          {review.score}/10
                        </span>
                      )}
                    </p>
                    {review.strengths?.length ? (
                      <div className="text-xs">
                        <p className="font-semibold text-emerald-600">✅ 亮点</p>
                        <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-muted-foreground">
                          {review.strengths.map((s, i) => (
                            <li key={i}>{s}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    {review.weaknesses?.length ? (
                      <div className="text-xs">
                        <p className="font-semibold text-danger">⚠️ 弱点</p>
                        <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-muted-foreground">
                          {review.weaknesses.map((w, i) => (
                            <li key={i}>{w}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    {review.suggestions?.length ? (
                      <div className="text-xs">
                        <p className="font-semibold text-primary-text">💡 改进建议</p>
                        <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-muted-foreground">
                          {review.suggestions.map((s, i) => (
                            <li key={i}>{s}</li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </div>
                )}
                {review?.error && (
                  <p className="rounded-lg bg-destructive/5 border border-destructive/40 p-3 text-xs text-destructive">
                    评审解析失败：{review.error}
                  </p>
                )}
                {reviewBusy && (
                  <p className="text-xs text-muted-foreground">制片人审稿中，约 10-30 秒…</p>
                )}
              </div>

              <Button onClick={setup} loading={setupBusy} disabled={!plan.characters?.length} size="lg">
                <Users className="h-4 w-4" aria-hidden />
                一键建组开演
                <ArrowRight className="h-4 w-4" aria-hidden />
              </Button>
              <p className="text-center text-xs text-muted-foreground">
                创建 {plan.characters?.length ?? 0} 张角色卡 + 自动建群，然后进入群聊分角色共创
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
