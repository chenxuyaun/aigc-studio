import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Activity,
  Check,
  ChevronDown,
  Copy,
  Download,
  Film,
  Image as ImageIcon,
  Layers,
  Music,
  Palette,
  Play,
  Radio,
  RefreshCw,
  Sparkles,
  UserRound,
  Workflow,
  Zap,
} from "lucide-react";

import { apiClient } from "@/lib/apiClient";
import { useMediaTask } from "@/hooks/useMediaTask";
import { cn } from "@/lib/cn";

/**
 * saiOS v2 P2 —— 统一 Studio 五域引擎面板（设计稿 saios_v2 (1).html 落地）。
 * 三段式驾驶舱：顶栏遥测+主题引擎 / 左参数舱 / 中央视口（HUD 渲染特效）+ 底部动作条。
 * 图像域 = 真实生成闭环（useMediaTask → hub 链）；其余域为诚实占位（迁移中引导）。
 */

type Domain = "image" | "music" | "video" | "story" | "workflow";
type ThemeName = "cyan" | "purple" | "emerald" | "mono";

const DOMAINS: { key: Domain; label: string; icon: typeof ImageIcon; hint: string; legacy: string }[] = [
  { key: "image", label: "图像&漫画", icon: ImageIcon, hint: "文生图 · hub 多链故障转移", legacy: "" },
  { key: "music", label: "音频&TTS", icon: Music, hint: "Edge-TTS 音色 · 音乐生成", legacy: "/create/audio" },
  { key: "video", label: "视频", icon: Film, hint: "视频引擎", legacy: "/create/video" },
  { key: "story", label: "角色&Story", icon: UserRound, hint: "角色卡 · 故事工坊", legacy: "/create/character-card" },
  { key: "workflow", label: "节点拓扑", icon: Workflow, hint: "工作流编排", legacy: "/workflows" },
];

const THEMES: { key: ThemeName; label: string; dot: string }[] = [
  { key: "cyan", label: "赛博冷青", dot: "#06b6d4" },
  { key: "purple", label: "量子紫罗兰", dot: "#8b5cf6" },
  { key: "emerald", label: "黑曜翡翠", dot: "#10b981" },
  { key: "mono", label: "钛银极简", dot: "#cbd5e1" },
];

/** GPT-Image2 风格库 Top 标签（awesome-gpt-image-2 export，点选注入 prompt 词缀）。 */
const STYLE_PRESETS: { tag: string; zh: string; suffix: string }[] = [
  { tag: "Realistic", zh: "写实摄影", suffix: ", ultra-realistic photography, natural lighting, 85mm lens, fine skin texture" },
  { tag: "Poster", zh: "海报排版", suffix: ", bold poster composition, strong typography, grid layout, print-quality" },
  { tag: "UI", zh: "UI 界面", suffix: ", clean modern UI design screen, crisp layout, product mockup presentation" },
  { tag: "3D", zh: "3D 渲染", suffix: ", octane 3D render, soft studio lighting, subsurface scattering, high detail" },
  { tag: "Illustration", zh: "插画艺术", suffix: ", digital illustration, vivid colors, expressive brushwork" },
  { tag: "Infographic", zh: "信息图", suffix: ", clean infographic diagram, labeled sections, flat vector style" },
  { tag: "Character", zh: "角色立绘", suffix: ", character sheet, consistent design, full body, neutral background" },
  { tag: "Brand", zh: "品牌 Logo", suffix: ", minimal logo design, vector identity, balanced negative space" },
];

const RATIOS: { label: string; w: number; h: number }[] = [
  { label: "1:1", w: 1024, h: 1024 },
  { label: "16:9", w: 1344, h: 768 },
  { label: "9:16", w: 768, h: 1344 },
  { label: "4:3", w: 1152, h: 864 },
];

interface CatalogEntry {
  id: string;
  name?: string;
  default_model?: string;
  healthy?: boolean;
}

export function StudioPage() {
  const navigate = useNavigate();
  const [domain, setDomain] = useState<Domain>("image");
  const [theme, setTheme] = useState<ThemeName>(
    () => (localStorage.getItem("saios-studio-theme") as ThemeName) || "cyan",
  );
  const [themeOpen, setThemeOpen] = useState(false);

  // ── 图像域状态 ──
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState(() => localStorage.getItem("saios-studio-image-model") || "");
  const [modelList, setModelList] = useState<CatalogEntry[]>([]);
  const [activeStyles, setActiveStyles] = useState<string[]>([]);
  const [ratio, setRatio] = useState(RATIOS[0]!);
  const imageTask = useMediaTask("/generations/image/generate");

  // 漫画任务（同一视口复用）
  const comicTask = useMediaTask("/generations/comic/generate");
  const task = domain === "image" ? imageTask : comicTask;

  // catalog 直连（图像模型）
  useEffect(() => {
    let alive = true;
    void apiClient
      .get<CatalogEntry[] | { items?: CatalogEntry[] }>("/providers/catalog")
      .then((r) => {
        if (!alive) return;
        const raw = Array.isArray(r) ? r : (r.items ?? []);
        setModelList(raw);
        setModel((cur) => {
          if (cur && raw.some((p) => (p.default_model || p.id) === cur)) return cur;
          const first = raw.find((p) => p.healthy !== false);
          const next = first?.default_model || first?.id || cur;
          localStorage.setItem("saios-studio-image-model", next);
          return next;
        });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // HUD step 文案随真实进度推进
  const hudStep = useMemo(() => {
    const p = task.progress;
    if (!task.busy) return "";
    if (p < 15) return "任务已入列 · 分配 GPU 渲染节点…";
    if (p < 55) return "扩散采样中 · Latent 空间去噪…";
    if (p < 90) return "细节重构 · VAE 解码与色彩写回…";
    return "落库中 · 写入资产中心…";
  }, [task.busy, task.progress]);

  function pickTheme(t: ThemeName) {
    setTheme(t);
    localStorage.setItem("saios-studio-theme", t);
    setThemeOpen(false);
  }

  function toggleStyle(tag: string) {
    setActiveStyles((prev) => (prev.includes(tag) ? prev.filter((x) => x !== tag) : [...prev, tag]));
  }

  async function renderImage() {
    const base = prompt.trim();
    if (!base || task.busy) return;
    const suffix = STYLE_PRESETS.filter((s) => activeStyles.includes(s.tag))
      .map((s) => s.suffix)
      .join("");
    await imageTask.run({
      model,
      prompt: base + suffix,
      width: ratio.w,
      height: ratio.h,
      num_images: 1,
    });
  }

  function renderComic() {
    const base = prompt.trim();
    if (!base || task.busy) return;
    void comicTask.run({
      prompt: base,
      style: STYLE_PRESETS.filter((s) => activeStyles.includes(s.tag))
        .map((s) => s.zh)
        .join("、") || "日式漫画",
      model: "gemini-3.1-flash-image", // hub image 链主选（chat 接口出图）
    });
  }

  function downloadResult() {
    const url = task.result?.assetUrl;
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = `saios-studio-${Date.now()}.png`;
    a.target = "_blank";
    a.rel = "noopener";
    a.click();
  }

  function copyPrompt() {
    if (prompt.trim()) void navigator.clipboard.writeText(prompt.trim());
  }

  // 推送助手：带 prompt 回调度大厅
  function pushToAssistant() {
    const t = prompt.trim();
    navigate(`/?studio_prompt=${encodeURIComponent(t)}`);
  }

  const accentVar = { color: "var(--st-accent)" };

  return (
    <div className="st-root min-h-screen bg-[#050811] text-slate-200" data-theme={theme}>
      {/* ═══ 顶栏 ═══ */}
      <header className="st-panel relative z-30 mx-3 mt-3 flex items-center justify-between px-4 py-2.5">
        <div className="flex items-center gap-3">
          <span
            className="grid h-8 w-8 place-items-center rounded-lg border text-sm font-black"
            style={{
              borderColor: "var(--st-border)",
              background: "rgba(var(--st-accent-rgb), .12)",
              color: "var(--st-accent)",
            }}
          >
            ◈
          </span>
          <div>
            <p className="font-mono text-sm font-bold tracking-widest text-white">SAIOS STUDIO</p>
            <p className="text-[10px] text-slate-500">统一创作驾驶舱 · 五域引擎</p>
          </div>
        </div>
        <div className="flex items-center gap-4 font-mono text-[11px]">
          <span className="hidden items-center gap-1.5 text-slate-500 md:flex">
            <Activity className="h-3.5 w-3.5" style={accentVar} aria-hidden />
            模型:
            <strong className="max-w-[180px] truncate text-slate-200">{model || "—"}</strong>
          </span>
          <span className="hidden items-center gap-1.5 text-slate-500 lg:flex">
            <Radio className="h-3.5 w-3.5" style={accentVar} aria-hidden />
            {task.busy ? (
              <span style={accentVar}>渲染中 {task.progress}%</span>
            ) : task.result ? (
              <span className="text-emerald-400">空闲 · 上次产出就绪</span>
            ) : (
              "待命"
            )}
          </span>
          {/* 主题选择器 */}
          <div className="relative">
            <button
              onClick={() => setThemeOpen((v) => !v)}
              className="flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] transition-colors hover:bg-white/5"
              style={{ borderColor: "var(--st-border)" }}
            >
              <Palette className="h-3.5 w-3.5" style={accentVar} aria-hidden />
              {THEMES.find((t) => t.key === theme)?.label}
              <ChevronDown className="h-3 w-3 text-slate-500" aria-hidden />
            </button>
            {themeOpen && (
              <div className="st-panel absolute right-0 top-full z-30 mt-1.5 w-44 overflow-hidden p-1">
                {THEMES.map((t) => (
                  <button
                    key={t.key}
                    onClick={() => pickTheme(t.key)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-slate-300 hover:bg-white/5",
                      theme === t.key && "st-chip-active border",
                    )}
                  >
                    <span className="h-3 w-3 rounded-full border border-white/20" style={{ background: t.dot }} />
                    {t.label}
                    {theme === t.key && <Check className="ml-auto h-3.5 w-3.5" aria-hidden />}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="mx-3 mb-3 mt-3 flex min-h-[calc(100vh-108px)] gap-3 pb-3">
        {/* ═══ 左参数舱 ═══ */}
        <aside className="st-panel hidden w-[300px] shrink-0 flex-col overflow-y-auto p-4 lg:flex">
          {/* 五域 tab（纵向） */}
          <nav className="mb-4 space-y-1">
            {DOMAINS.map((d) => (
              <button
                key={d.key}
                onClick={() => setDomain(d.key)}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left text-xs font-semibold transition-all",
                  domain === d.key ? "st-chip-active border" : "border-transparent text-slate-400 hover:bg-white/5",
                )}
              >
                <d.icon className="h-4 w-4" aria-hidden />
                {d.label}
                <span className="ml-auto text-[9px] font-normal text-slate-600">{d.hint}</span>
              </button>
            ))}
          </nav>

          {domain === "image" ? (
            <div className="space-y-4">
              {/* 模型选择 */}
              <div>
                <p className="mb-1.5 flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                  <Layers className="h-3 w-3" aria-hidden /> 引擎模型
                </p>
                <select
                  value={model}
                  onChange={(e) => {
                    setModel(e.target.value);
                    localStorage.setItem("saios-studio-image-model", e.target.value);
                  }}
                  className="w-full rounded-xl border bg-slate-950/70 px-3 py-2 font-mono text-xs text-white outline-none [&>option]:bg-slate-900"
                  style={{ borderColor: "var(--st-border)" }}
                >
                  {modelList.length === 0 && <option value={model}>{model || "加载中…"}</option>}
                  {modelList.map((m) => (
                    <option key={m.id} value={m.default_model || m.id}>
                      {(m.name || m.id) + " · " + (m.default_model || m.id)}
                    </option>
                  ))}
                </select>
              </div>

              {/* GPT-Image2 风格预设 */}
              <div>
                <p className="mb-1.5 flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                  <Sparkles className="h-3 w-3" aria-hidden /> 风格预设
                  <span className="normal-case font-normal text-slate-600">GPT-Image2 风格库</span>
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {STYLE_PRESETS.map((s) => (
                    <button
                      key={s.tag}
                      onClick={() => toggleStyle(s.tag)}
                      title={s.suffix}
                      className={cn(
                        "rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[10px] text-slate-400 transition-all hover:border-white/25",
                        activeStyles.includes(s.tag) && "st-chip-active border",
                      )}
                    >
                      {s.zh}
                    </button>
                  ))}
                </div>
              </div>

              {/* Prompt */}
              <div>
                <p className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">Prompt</p>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={5}
                  placeholder="描述你想生成的画面…可组合右侧风格预设"
                  className="w-full resize-none rounded-xl border bg-slate-950/70 px-3 py-2.5 text-xs leading-relaxed text-slate-100 outline-none placeholder:text-slate-600 focus:border-[rgba(var(--st-accent-rgb),.6)]"
                  style={{ borderColor: "var(--st-border)" }}
                />
                <p className="mt-1 text-right font-mono text-[10px] text-slate-600">{prompt.length} chars</p>
              </div>

              {/* 尺寸 */}
              <div>
                <p className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">画幅</p>
                <div className="grid grid-cols-4 gap-1.5">
                  {RATIOS.map((r) => (
                    <button
                      key={r.label}
                      onClick={() => setRatio(r)}
                      className={cn(
                        "rounded-lg border border-white/10 py-1.5 font-mono text-[10px] text-slate-400 transition-all",
                        ratio.label === r.label && "st-chip-active border",
                      )}
                    >
                      {r.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* 图像/漫画模式切换渲染 */}
              <div className="grid grid-cols-2 gap-2 pt-1">
                <button
                  onClick={() => void renderImage()}
                  disabled={!prompt.trim() || task.busy}
                  className="flex items-center justify-center gap-1.5 rounded-xl py-2.5 text-xs font-bold text-slate-950 transition-transform enabled:hover:scale-[1.02] disabled:opacity-40"
                  style={{ background: "linear-gradient(120deg, var(--st-accent), rgba(255,255,255,.82))" }}
                >
                  <Zap className="h-3.5 w-3.5" aria-hidden />
                  {imageTask.busy ? "渲染中…" : "渲染图像"}
                </button>
                <button
                  onClick={renderComic}
                  disabled={!prompt.trim() || task.busy}
                  className="rounded-xl border py-2.5 text-xs font-semibold text-slate-300 transition-colors hover:bg-white/5 disabled:opacity-40"
                  style={{ borderColor: "var(--st-border)" }}
                >
                  {comicTask.busy ? "分镜中…" : "生成漫画"}
                </button>
              </div>
            </div>
          ) : (
            /* 其余四域：诚实占位（不假执行） */
            <div className="flex flex-1 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-white/10 p-6 text-center">
              {(() => {
                const d = DOMAINS.find((x) => x.key === domain)!;
                return (
                  <>
                    <d.icon className="h-8 w-8 opacity-40" style={accentVar} aria-hidden />
                    <p className="text-xs font-semibold text-slate-300">{d.label}引擎</p>
                    <p className="text-[11px] leading-relaxed text-slate-500">
                      该域正在向统一驾驶舱迁移。完整功能当前在专页可用：
                    </p>
                    {d.legacy && (
                      <Link
                        to={d.legacy}
                        className="rounded-lg border px-3 py-1.5 text-[11px] font-semibold transition-colors hover:bg-white/5"
                        style={{ borderColor: "var(--st-border)", color: "var(--st-accent)" }}
                      >
                        前往{d.label}完整版 →
                      </Link>
                    )}
                  </>
                );
              })()}
            </div>
          )}
        </aside>

        {/* ═══ 中央视口 ═══ */}
        <main className="st-panel st-hud-corner relative flex min-w-0 flex-1 flex-col overflow-hidden">
          {/* 移动端域切换 */}
          <div className="flex gap-1.5 overflow-x-auto border-b border-white/5 p-2 lg:hidden">
            {DOMAINS.map((d) => (
              <button
                key={d.key}
                onClick={() => setDomain(d.key)}
                className={cn(
                  "shrink-0 rounded-full border border-white/10 px-3 py-1 text-[11px]",
                  domain === d.key ? "st-chip-active border" : "text-slate-400",
                )}
              >
                {d.label}
              </button>
            ))}
          </div>

          <div className="st-grid-bg relative flex flex-1 items-center justify-center overflow-hidden p-4">
            {/* 空态准星 */}
            {!task.result && !task.busy && !task.error && (
              <div className="pointer-events-none select-none text-center">
                <div className="st-node-pulse relative mx-auto mb-4 grid h-16 w-16 place-items-center rounded-full border" style={{ borderColor: "var(--st-border)" }}>
                  <Play className="h-6 w-6" style={accentVar} aria-hidden />
                </div>
                <p className="font-mono text-sm font-bold tracking-widest" style={accentVar}>
                  STUDIO VIEWPORT
                </p>
                <p className="mt-1.5 max-w-sm text-[11px] leading-relaxed text-slate-500">
                  在左侧参数舱输入 Prompt 并选择风格预设，点击「渲染图像」开始创作。
                  <br />
                  移动端请先在上方选择域。
                </p>
              </div>
            )}

            {/* 结果 */}
            {task.result?.assetUrl && !task.busy && (
              <figure className="flex max-h-full max-w-full flex-col items-center gap-2">
                <img
                  src={task.result.assetUrl}
                  alt="Studio 生成结果"
                  className="max-h-[62vh] rounded-xl border object-contain shadow-2xl"
                  style={{ borderColor: "var(--st-border)" }}
                />
                <figcaption className="flex items-center gap-2 font-mono text-[10px] text-slate-500">
                  <span style={accentVar}>{task.result.provider}</span>
                  <span>·</span>
                  <span>{ratio.label}</span>
                  {activeStyles.length > 0 && (
                    <>
                      <span>·</span>
                      <span>{activeStyles.join(" / ")}</span>
                    </>
                  )}
                </figcaption>
              </figure>
            )}

            {/* 错误 */}
            {task.error && !task.busy && (
              <div className="max-w-md rounded-xl border border-rose-500/30 bg-rose-500/5 p-4 text-center">
                <p className="text-xs font-semibold text-rose-300">渲染失败</p>
                <p className="mt-1 break-all text-[11px] leading-relaxed text-slate-400">{task.error}</p>
                <button
                  onClick={() => void renderImage()}
                  className="mt-3 inline-flex items-center gap-1 rounded-lg border border-white/15 px-3 py-1.5 text-[11px] text-slate-300 hover:bg-white/5"
                >
                  <RefreshCw className="h-3 w-3" aria-hidden /> 重试
                </button>
              </div>
            )}

            {/* HUD 渲染覆盖层（真实进度驱动） */}
            {task.busy && (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-4 overflow-hidden bg-slate-950/80 backdrop-blur-sm">
                <div className="st-scan-beam" aria-hidden />
                <p className="z-10 font-mono text-4xl font-black tabular-nums" style={accentVar}>
                  {Math.round(task.progress)}%
                </p>
                <div className="z-10 h-1.5 w-64 overflow-hidden rounded-full bg-white/10">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${task.progress}%`, background: "var(--st-accent)" }}
                  />
                </div>
                <p className="z-10 font-mono text-[11px] text-slate-400">{hudStep}</p>
                <p className="z-10 font-mono text-[10px] text-slate-600">NODE GPU-01 · SAIOS RENDER FARM</p>
              </div>
            )}
          </div>

          {/* ═══ 底部动作条 ═══ */}
          <footer className="flex items-center justify-between gap-2 border-t border-white/5 px-4 py-2.5">
            <div className="flex min-w-0 items-center gap-2 font-mono text-[10px] text-slate-600">
              <span className="truncate">{prompt.trim() ? `PROMPT: ${prompt.trim().slice(0, 48)}${prompt.trim().length > 48 ? "…" : ""}` : "IDLE"}</span>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <button
                onClick={copyPrompt}
                disabled={!prompt.trim()}
                title="复制 Prompt"
                className="flex items-center gap-1 rounded-lg border border-white/10 px-2.5 py-1.5 text-[11px] text-slate-400 transition-colors hover:bg-white/5 disabled:opacity-35"
              >
                <Copy className="h-3 w-3" aria-hidden /> 复制 Prompt
              </button>
              <button
                onClick={pushToAssistant}
                disabled={!prompt.trim()}
                title="推送调度大厅继续对话式创作"
                className="flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-[11px] transition-colors hover:bg-white/5 disabled:opacity-35"
                style={{ borderColor: "var(--st-border)", color: "var(--st-accent)" }}
              >
                <Sparkles className="h-3 w-3" aria-hidden /> 推送助手
              </button>
              <a
                href={task.result?.assetUrl ?? "#"}
                onClick={(e) => {
                  if (!task.result?.assetUrl) e.preventDefault();
                  else downloadResult();
                }}
                className={cn(
                  "flex items-center gap-1 rounded-lg border border-white/10 px-2.5 py-1.5 text-[11px] text-slate-400 transition-colors hover:bg-white/5",
                  !task.result?.assetUrl && "pointer-events-none opacity-35",
                )}
              >
                <Download className="h-3 w-3" aria-hidden /> 下载
              </a>
            </div>
          </footer>
        </main>
      </div>
    </div>
  );
}
