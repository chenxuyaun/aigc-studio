/**
 * Personal Voice Engine —— 「文风」开关与设置入口（顶栏徽标 + 下拉面板）。
 *
 * - 有档案：显示「文风·已启用」，可预览 preferred/avoid、粘贴新样本更新、停用
 * - 无档案：引导粘贴 1~3 段自己写的文字 → 存入个人语料 → 自动提取 Voice DNA
 * - 已启用时可进入编辑态：直接手改 Voice DNA 六维 + 偏爱/忌讳词（PUT /voice/profile）
 *
 * 注入是后端 agent_chat 自动完成的（有档案即注入 system），本组件只负责
 * 用户感知与控制。
 */

import { useEffect, useRef, useState } from "react";

import {
  Feather,
  Loader2,
  Pencil,
  PenLine,
  Plus,
  Save,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";

interface VoiceProfile {
  id?: string;
  name?: string;
  source?: "manual" | "auto";
  voice_dna?: {
    sentence_length?: string;
    vocabulary?: string;
    formality?: string;
    emotion?: string;
    humor?: string;
    opinion_strength?: string;
    preferred?: string[];
    avoid?: string[];
    [k: string]: unknown;
  };
  samples?: { title?: string; text?: string }[];
}

type DnaKey = keyof NonNullable<VoiceProfile["voice_dna"]>;

// 六项可选项（与后端 _DNA_DEFAULTS 注释一致）
const DNA_OPTIONS: { key: DnaKey; label: string; options: string[] }[] = [
  { key: "sentence_length", label: "句式", options: ["short", "medium", "long", "mixed"] },
  { key: "vocabulary", label: "用词", options: ["simple", "medium", "rich"] },
  { key: "formality", label: "正式度", options: ["casual", "medium", "formal"] },
  { key: "emotion", label: "情绪", options: ["restrained", "warm", "expressive"] },
  { key: "humor", label: "幽默", options: ["none", "dry", "witty"] },
  { key: "opinion_strength", label: "观点强度", options: ["low", "medium", "high"] },
];

function ChipEditor({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (v: string[]) => void;
}) {
  const [input, setInput] = useState("");
  const add = () => {
    const v = input.trim();
    if (!v || values.includes(v)) return;
    onChange([...values, v]);
    setInput("");
  };
  return (
    <div>
      <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <div className="flex flex-wrap gap-1">
        {values.map((v) => (
          <span
            key={v}
            className="group flex items-center gap-1 rounded-md bg-primary/15 px-1.5 py-0.5 text-[10px] text-primary-text"
          >
            {v}
            <button
              type="button"
              onClick={() => onChange(values.filter((x) => x !== v))}
              className="text-primary-text/60 hover:text-destructive"
              aria-label={`删除 ${v}`}
            >
              <X className="h-2.5 w-2.5" />
            </button>
          </span>
        ))}
        <span className="flex items-center gap-0.5">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
            placeholder="+添加"
            className="w-16 rounded-md border border-border bg-background/70 px-1.5 py-0.5 text-[10px] text-foreground outline-none placeholder:text-muted-foreground/50 focus:border-primary/50"
          />
          <button
            type="button"
            onClick={add}
            className="rounded-md p-0.5 text-muted-foreground hover:text-primary-text"
            aria-label={`添加 ${label}`}
          >
            <Plus className="h-3 w-3" />
          </button>
        </span>
      </div>
    </div>
  );
}

export function VoiceBadge({ className }: { className?: string }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [exists, setExists] = useState(false);
  const [profile, setProfile] = useState<VoiceProfile | null>(null);
  const [sample, setSample] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<NonNullable<VoiceProfile["voice_dna"]>>({});
  const boxRef = useRef<HTMLDivElement | null>(null);

  async function load() {
    setLoading(true);
    try {
      const r = await apiClient.get<{ exists: boolean; profile?: VoiceProfile }>(
        "/voice/profile",
      );
      setExists(!!r.exists);
      setProfile(r.profile ?? null);
    } catch {
      setExists(false);
      setProfile(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // 点外部关闭
    function onClick(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  function startEdit() {
    setDraft({ ...(profile?.voice_dna ?? {}) });
    setEditing(true);
  }

  /** 标题进入可编辑态时不打断手势的辅助：面板关闭时清除编辑态 */
  function closePanel() {
    setOpen(false);
    setEditing(false);
  }

  async function saveDna() {
    setBusy(true);
    try {
      await apiClient.put("/voice/profile", { voice_dna: draft });
      toast.success("已保存文风档案");
      setEditing(false);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function addSampleAndExtract() {
    const text = sample.trim();
    if (text.length < 8) {
      toast.error("样本太短，至少 8 个字");
      return;
    }
    setBusy(true);
    try {
      // ① 入个人语料（写文字 → 提取文风的素材）
      const c = await apiClient.post<{ ok: boolean; reason?: string }>("/voice/corpus", {
        kind: "note",
        text,
      });
      if (!c.ok) throw new Error(c.reason || "样本入库失败");
      // ② 自动提取 Voice DNA（后端 LLM 提炼，manual 档案不会被覆盖）
      const r = await apiClient.post<{ ok: boolean; reason?: string }>(
        "/voice/profile/extract",
      );
      if (!r.ok) throw new Error(r.reason || "暂无法提炼，请再多提供几段样本");
      toast.success("已用你的样本更新文风");
      setSample("");
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function disableVoice() {
    setBusy(true);
    try {
      await apiClient.del("/voice/profile");
      setExists(false);
      setProfile(null);
      setEditing(false);
      toast.success("已停用文风，对话恢复默认语气");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "停用失败");
    } finally {
      setBusy(false);
    }
  }

  const preferred = profile?.voice_dna?.preferred ?? [];
  const avoid = profile?.voice_dna?.avoid ?? [];
  const sourceLabel = profile?.source === "manual" ? "手动" : "自动";

  return (
    <div ref={boxRef} className={cn("relative", className)}>
      <button
        onClick={() => {
          setOpen((v) => !v);
          if (!open) void load();
        }}
        title="文风：让 AI 用你习惯的方式表达（去 AI 味）"
        className={cn(
          "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] transition-colors",
          exists
            ? "border-primary/40 bg-primary/15 text-primary-text hover:bg-primary/25"
            : "border-border bg-surface-raised/60 text-muted-foreground hover:border-primary/30 hover:text-primary-text",
        )}
      >
        <Feather className="h-3.5 w-3.5" aria-hidden />
        <span className="hidden font-medium sm:inline">
          {loading ? "文风…" : exists ? `文风·${sourceLabel}` : "文风"}
        </span>
        {exists && <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden />}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-[22rem] max-w-[92vw] rounded-2xl border border-border bg-surface-raised p-4 shadow-2xl backdrop-blur-xl">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
              <Feather className="h-3.5 w-3.5 text-primary-text" aria-hidden />
              文风档案（去 AI 味）
            </h3>
            <button
              onClick={closePanel}
              className="rounded-md p-1 text-muted-foreground hover:bg-foreground/10 hover:text-foreground"
              aria-label="关闭"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          {exists && profile ? (
            editing ? (
              /* ---- 可编辑表单态（§12-5）：直接手改 Voice DNA ---- */
              <div className="space-y-3 text-xs">
                {DNA_OPTIONS.map(({ key: k, label, options }) => (
                  <label key={k} className="flex items-center justify-between gap-3">
                    <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
                      {label}
                    </span>
                    <select
                      value={String(draft[k] ?? "")}
                      onChange={(e) =>
                        setDraft((d) => ({ ...d, [k]: e.target.value as string }))
                      }
                      className="rounded-lg border border-border bg-background/70 px-2 py-1 text-[11px] text-foreground outline-none focus:border-primary/50"
                    >
                      <option value="">（跟随提取）</option>
                      {options.map((o) => (
                        <option key={o} value={o}>
                          {o}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
                <ChipEditor
                  label="偏爱表达"
                  values={draft.preferred ?? []}
                  onChange={(v) => setDraft((d) => ({ ...d, preferred: v }))}
                />
                <ChipEditor
                  label="忌讳的腔调"
                  values={draft.avoid ?? []}
                  onChange={(v) => setDraft((d) => ({ ...d, avoid: v }))}
                />
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={saveDna}
                    disabled={busy}
                    className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-primary px-2 py-1.5 text-[11px] font-medium text-white transition-colors hover:opacity-90 disabled:opacity-50"
                  >
                    {busy ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <Save className="h-3 w-3" />
                    )}
                    保存档案
                  </button>
                  <button
                    onClick={() => setEditing(false)}
                    disabled={busy}
                    className="rounded-lg border border-border px-2 py-1.5 text-[11px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
                  >
                    取消
                  </button>
                </div>
              </div>
            ) : (
              /* ---- 只读预览态 ---- */
              <div className="space-y-3 text-xs">
                <p className="text-muted-foreground">
                  AI 会模仿你习惯的表达方式写作，而不是通用 AI 腔。
                </p>
                {preferred.length > 0 && (
                  <div>
                    <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                      你的表达习惯
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {preferred.map((p) => (
                        <span
                          key={p}
                          className="rounded-md bg-primary/15 px-1.5 py-0.5 text-[10px] text-primary-text"
                        >
                          {p}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {avoid.length > 0 && (
                  <div>
                    <p className="mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                      忌讳的腔调
                    </p>
                    <div className="flex flex-wrap gap-1">
                      {avoid.map((a) => (
                        <span
                          key={a}
                          className="rounded-md bg-destructive/10 px-1.5 py-0.5 text-[10px] text-destructive"
                        >
                          {a}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
                  {DNA_OPTIONS.map(({ key: k, label, options }) => {
                    const v = profile.voice_dna?.[k];
                    const readable = v && options.includes(String(v)) ? String(v) : undefined;
                    return (
                      <span key={k} className="flex items-center justify-between gap-2">
                        <span>{label}</span>
                        <span className="text-foreground/80">{readable ?? "—"}</span>
                      </span>
                    );
                  })}
                </div>
                <label className="block">
                  <span className="mb-1 flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                    <Plus className="h-3 w-3" aria-hidden /> 贴新样本（自动更新文风）
                  </span>
                  <textarea
                    value={sample}
                    onChange={(e) => setSample(e.target.value)}
                    rows={3}
                    placeholder="写几段自己的话：朋友圈、聊天、文章片段都行…"
                    className="w-full resize-none rounded-xl border border-border bg-background/70 px-2.5 py-2 text-xs text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary/50"
                  />
                </label>
                <div className="flex gap-2">
                  <button
                    onClick={addSampleAndExtract}
                    disabled={busy}
                    className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-primary px-2 py-1.5 text-[11px] font-medium text-white transition-colors hover:opacity-90 disabled:opacity-50"
                  >
                    {busy ? (
                      <Loader2 className="h-3 w-3 animate-spin" />
                    ) : (
                      <PenLine className="h-3 w-3" />
                    )}
                    更新文风
                  </button>
                  <button
                    onClick={startEdit}
                    disabled={busy}
                    className="flex items-center gap-1 rounded-lg border border-border px-2 py-1.5 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary-text disabled:opacity-50"
                  >
                    <Pencil className="h-3 w-3" /> 编辑
                  </button>
                  <button
                    onClick={disableVoice}
                    disabled={busy}
                    className="flex items-center gap-1 rounded-lg border border-border px-2 py-1.5 text-[11px] text-muted-foreground transition-colors hover:border-destructive/40 hover:text-destructive disabled:opacity-50"
                  >
                    <Trash2 className="h-3 w-3" /> 停用
                  </button>
                </div>
              </div>
            )
          ) : (
            <div className="space-y-3 text-xs">
              <p className="text-muted-foreground">
                让 AI 用你习惯的方式表达，而不是通用 AI 腔。提供几段你自己写的文字，
                我们会提炼你的「文风档案」。
              </p>
              <textarea
                value={sample}
                onChange={(e) => setSample(e.target.value)}
                rows={4}
                placeholder="粘贴 1~3 段你自己写过的文字（聊天、朋友圈、文章…）"
                className="w-full resize-none rounded-xl border border-border bg-background/70 px-2.5 py-2 text-xs text-foreground outline-none placeholder:text-muted-foreground/60 focus:border-primary/50"
              />
              <button
                onClick={addSampleAndExtract}
                disabled={busy || sample.trim().length < 8}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-[11px] font-medium text-white transition-colors hover:opacity-90 disabled:opacity-50"
              >
                {busy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
                提取我的文风
              </button>
              <p className="text-[10px] leading-relaxed text-muted-foreground/70">
                提示：也可先和 AI 多聊几轮，系统会从你的对话与文档里自动学习文风。
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}