import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  Check,
  ChevronDown,
  Copy,
  Download,
  Film,
  Image as ImageIcon,
  Layers,
  Mic,
  Music,
  Palette,
  Pause,
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
import { useThemeStore, type SkinName } from "@/stores/theme";
import { cn } from "@/lib/cn";

/**
 * saiOS v2 P2 —— 统一 Studio 五域引擎面板（设计稿 saios_v2 (1).html 落地）。
 * 三段式驾驶舱：顶栏遥测+主题引擎 / 左参数舱 / 中央视口（HUD 渲染特效）+ 底部动作条。
 * 图像域 = 真实生成闭环（hub 三候选链）；音频&TTS 域 = Edge-TTS 音色舱 + 音乐直出 +
 * Web Audio 实时频谱；其余域为诚实占位（迁移中引导）。
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

/** 角色&Story / Workflow 域的子能力导航（迁移期：直达完整版专页）。 */
const DOMAIN_LINKS: Partial<Record<Domain, { label: string; desc: string; to: string }[]>> = {
  story: [
    { label: "角色捏卡", desc: "世界书 · 头像 · SillyTavern 导出", to: "/create/character-card" },
    { label: "角色扮演", desc: "长期记忆陪伴对话", to: "/roleplay" },
    { label: "故事工作室", desc: "AI 剧本工坊连载创作", to: "/story" },
    { label: "SillyTavern", desc: "专业前端直连管理", to: "/sillytavern" },
  ],
  workflow: [
    { label: "节点编排", desc: "xyflow 可视化工作流画布", to: "/workflows" },
    { label: "Agent 库", desc: "智能体配置与技能绑定", to: "/agents" },
    { label: "MCP 技能", desc: "工具能力清单与调试", to: "/skills" },
    { label: "AI 导演", desc: "选角建组群聊共创", to: "/create/studio" },
  ],
};

const THEMES: { key: ThemeName; label: string; dot: string; rgb: string }[] = [
  { key: "cyan", label: "赛博冷青", dot: "#06b6d4", rgb: "6,182,212" },
  { key: "purple", label: "量子紫罗兰", dot: "#8b5cf6", rgb: "139,92,246" },
  { key: "emerald", label: "黑曜翡翠", dot: "#10b981", rgb: "16,185,129" },
  { key: "mono", label: "钛银极简", dot: "#cbd5e1", rgb: "203,213,225" },
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

/** Edge-TTS 真实音色表（与 AudioGenPage 一致）。 */
const VOICES: { value: string; label: string }[] = [
  { value: "default", label: "晓晓（自动·女声）" },
  { value: "XiaoxiaoNeural", label: "晓晓 · 温暖女声" },
  { value: "XiaoyiNeural", label: "晓伊 · 活泼女声" },
  { value: "YunxiNeural", label: "云希 · 年轻男声" },
  { value: "YunjianNeural", label: "云健 · 磁性男声" },
  { value: "YunyangNeural", label: "云扬 · 新闻男声" },
  { value: "liaoning-XiaobeiNeural", label: "晓北 · 东北方言" },
  { value: "zh-TW-HsiaoChenNeural", label: "小陈 · 台湾腔" },
  { value: "en-US-JennyNeural", label: "Jenny · English F" },
  { value: "en-US-GuyNeural", label: "Guy · English M" },
];

interface CatalogEntry {
  id: string;
  name?: string;
  default_model?: string;
  healthy?: boolean;
}

type TaskState = ReturnType<typeof useMediaTask>;

export function StudioPage() {
  const navigate = useNavigate();
  const [domain, setDomain] = useState<Domain>("image");
  // v2 P3：皮肤接入全局主题引擎（与 AppShell 顶栏选择器同源，全站一致）
  const skin = useThemeStore((s) => s.skin);
  const setSkin = useThemeStore((s) => s.setSkin);
  const theme: SkinName = skin;
  const [themeOpen, setThemeOpen] = useState(false);

  // ── 图像域 ──
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState(() => localStorage.getItem("saios-studio-image-model") || "");
  const [modelList, setModelList] = useState<CatalogEntry[]>([]);
  const [activeStyles, setActiveStyles] = useState<string[]>([]);
  const [ratio, setRatio] = useState(RATIOS[0]!);
  const imageTask = useMediaTask("/generations/image/generate");
  const comicTask = useMediaTask("/generations/comic/generate");

  // ── 音频&TTS 域 ──
  const [audioMode, setAudioMode] = useState<"tts" | "song">("tts");
  const [voice, setVoice] = useState("default");
  const [speed, setSpeed] = useState(1);
  const [ttsText, setTtsText] = useState("");
  const [songDesc, setSongDesc] = useState("");
  const [duration, setDuration] = useState(30);
  const ttsTask = useMediaTask("/generations/audio/generate");
  const songTask = useMediaTask("/generations/music/generate");

  // ── 视频域 ──
  const [videoDesc, setVideoDesc] = useState("");
  const [videoDuration, setVideoDuration] = useState(5);
  const videoTask = useMediaTask("/generations/video/generate");

  // 反向克隆提示条
  const [rehydrated, setRehydrated] = useState("");

  // 视口展示策略：正在生成的优先，其次最近有结果的
  const tasks: Record<string, TaskState> = {
    image: imageTask,
    comic: comicTask,
    tts: ttsTask,
    song: songTask,
    video: videoTask,
  };
  const shownKey = useMemo(() => {
    const order = ["tts", "song", "video", "comic", "image"];
    return order.find((k) => tasks[k]!.busy) ?? order.find((k) => tasks[k]!.result) ?? "image";
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageTask, comicTask, ttsTask, songTask, videoTask]);
  const task = tasks[shownKey]!;
  const isAudioResult = Boolean(task.result?.assetUrl && (task.result.mime ?? "").startsWith("audio"));
  const isVideoResult = Boolean(task.result?.assetUrl && (task.result.mime ?? "").startsWith("video"));
  const accentRgb = THEMES.find((t) => t.key === theme)?.rgb ?? "6,182,212";

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

  // HUD step 文案随真实进度推进（按媒体类型分文案）
  const hudStep = useMemo(() => {
    const p = task.progress;
    if (!task.busy) return "";
    if (shownKey === "video") {
      if (p < 30) return "视频引擎排队 · 分配渲染节点…";
      if (p < 85) return "逐帧合成中 · 关键帧扩散采样…";
      return "编码封装 · H.264 写回资产库…";
    }
    if (isAudioShown()) {
      if (p < 30) return "合成队列 · 分配语音引擎…";
      if (p < 80) return isSongShown() ? "MusicGen 采样中 · 生成波形…" : "TTS 合成中 · 声学模型推理…";
      return "转码落库 · 写入资产中心…";
    }
    if (p < 15) return "任务已入列 · 分配 GPU 渲染节点…";
    if (p < 55) return "扩散采样中 · Latent 空间去噪…";
    if (p < 90) return "细节重构 · VAE 解码与色彩写回…";
    return "落库中 · 写入资产中心…";
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [task.busy, task.progress, shownKey]);

  function isSongShown(): boolean {
    return shownKey === "song";
  }
  function isAudioShown(): boolean {
    return shownKey === "tts" || shownKey === "song";
  }

  // ── 反向克隆 Re-hydrate：/studio?rehydrate=<taskId> 带参回填再创作 ──
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    // 灵感画廊「在 Studio 打开」：?prompt=<文本> 直接回填图像域
    const direct = searchParams.get("prompt");
    if (direct) {
      setDomain("image");
      setPrompt(direct);
      setRehydrated("已从灵感画廊带入 prompt，可编辑后渲染");
      setSearchParams({}, { replace: true });
      return;
    }
    const rid = searchParams.get("rehydrate");
    if (!rid) return;
    void (async () => {
      try {
        const t = await apiClient.get<{ id: string; task_type: string; params: string }>(`/tasks/${rid}`);
        const p = JSON.parse(t.params || "{}") as Record<string, unknown>;
        const s = (k: string) => (typeof p[k] === "string" ? (p[k] as string) : "");
        switch (t.task_type) {
          case "audio":
            setDomain("music");
            setAudioMode("tts");
            setTtsText(s("text") || s("prompt"));
            if (typeof p.voice === "string") setVoice(p.voice);
            break;
          case "music":
            setDomain("music");
            setAudioMode("song");
            setSongDesc(s("prompt"));
            if (typeof p.duration_seconds === "number") setDuration(p.duration_seconds);
            break;
          case "video":
            setDomain("video");
            setVideoDesc(s("prompt"));
            if (typeof p.duration === "number") setVideoDuration(p.duration);
            break;
          default: // image / comic
            setDomain("image");
            setPrompt(s("prompt") || s("text"));
            const w = typeof p.width === "number" ? p.width : 0;
            const h = typeof p.height === "number" ? p.height : 0;
            const hit = RATIOS.find((r) => r.w === w && r.h === h);
            if (hit) setRatio(hit);
            break;
        }
        setRehydrated(`已从任务 ${rid.slice(0, 8)} 回填参数，可调整后再次渲染`);
      } catch {
        /* 任务不存在/无权限：静默保持空参数 */
      } finally {
        setSearchParams({}, { replace: true });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  function pickTheme(t: SkinName) {
    setSkin(t);
    setThemeOpen(false);
  }

  function toggleStyle(tag: string) {
    setActiveStyles((prev) => (prev.includes(tag) ? prev.filter((x) => x !== tag) : [...prev, tag]));
  }

  async function renderImage() {
    const base = prompt.trim();
    if (!base || imageTask.busy) return;
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
    if (!base || comicTask.busy) return;
    void comicTask.run({
      prompt: base,
      style: STYLE_PRESETS.filter((s) => activeStyles.includes(s.tag))
        .map((s) => s.zh)
        .join("、") || "日式漫画",
      model: "gemini-3.1-flash-image", // hub image 链主选（chat 接口出图）
    });
  }

  async function renderTts() {
    if (!ttsText.trim() || ttsTask.busy) return;
    await ttsTask.run({ text: ttsText.trim(), voice, speed });
  }

  function renderSong() {
    if (!songDesc.trim() || songTask.busy) return;
    void songTask.run({ prompt: songDesc.trim(), duration_seconds: duration });
  }

  function renderVideo() {
    if (!videoDesc.trim() || videoTask.busy) return;
    void videoTask.run({ prompt: videoDesc.trim(), duration: videoDuration });
  }

  function retryShown() {
    if (shownKey === "image") void renderImage();
    else if (shownKey === "comic") renderComic();
    else if (shownKey === "tts") void renderTts();
    else if (shownKey === "video") renderVideo();
    else renderSong();
  }

  /** 当前视口任务对应的提示词文本（复制/推送/状态条共用）。 */
  function activePrompt(): string {
    if (shownKey === "tts") return ttsText.trim();
    if (shownKey === "song") return songDesc.trim();
    if (shownKey === "video") return videoDesc.trim();
    return prompt.trim();
  }

  function copyPrompt() {
    const t = activePrompt();
    if (t) void navigator.clipboard.writeText(t);
  }

  // 推送助手：带 prompt 回调度大厅
  function pushToAssistant() {
    navigate(`/?studio_prompt=${encodeURIComponent(activePrompt())}`);
  }

  const extFromMime = (m?: string) =>
    m?.includes("wav") ? "wav" : m?.includes("ogg") ? "ogg" : m?.includes("mp4") ? "m4a" : "mp3";

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
            引擎:
            <strong className="max-w-[180px] truncate text-slate-200">
              {shownKey === "tts"
                ? voice
                : shownKey === "song"
                  ? `MusicGen ${duration}s`
                  : shownKey === "video"
                    ? `Video ${videoDuration}s`
                    : model || "—"}
            </strong>
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
        {/* 反向克隆提示条 */}
        {rehydrated && (
          <div
            className="fixed bottom-5 left-1/2 z-40 -translate-x-1/2 rounded-xl border px-4 py-2.5 font-mono text-[11px] shadow-2xl backdrop-blur"
            style={{ borderColor: "var(--st-border)", background: "rgba(var(--st-accent-rgb), .12)", color: "var(--st-accent)" }}
          >
            {rehydrated}
            <button onClick={() => setRehydrated("")} className="ml-3 text-slate-500 hover:text-slate-300" aria-label="关闭">
              ✕
            </button>
          </div>
        )}

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
                  disabled={!prompt.trim() || imageTask.busy}
                  className="flex items-center justify-center gap-1.5 rounded-xl py-2.5 text-xs font-bold text-slate-950 transition-transform enabled:hover:scale-[1.02] disabled:opacity-40"
                  style={{ background: "linear-gradient(120deg, var(--st-accent), rgba(255,255,255,.82))" }}
                >
                  <Zap className="h-3.5 w-3.5" aria-hidden />
                  {imageTask.busy ? "渲染中…" : "渲染图像"}
                </button>
                <button
                  onClick={renderComic}
                  disabled={!prompt.trim() || comicTask.busy}
                  className="rounded-xl border py-2.5 text-xs font-semibold text-slate-300 transition-colors hover:bg-white/5 disabled:opacity-40"
                  style={{ borderColor: "var(--st-border)" }}
                >
                  {comicTask.busy ? "分镜中…" : "生成漫画"}
                </button>
              </div>
            </div>
          ) : domain === "music" ? (
            /* ═══ 音频&TTS 域参数舱 ═══ */
            <div className="space-y-4">
              {/* 子模式 */}
              <div className="grid grid-cols-2 gap-1.5">
                {(["tts", "song"] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => setAudioMode(m)}
                    className={cn(
                      "rounded-lg border border-white/10 py-2 text-[11px] font-semibold text-slate-400 transition-all",
                      audioMode === m && "st-chip-active border",
                    )}
                  >
                    {m === "tts" ? "🎙 语音合成 TTS" : "🎵 音乐生成"}
                  </button>
                ))}
              </div>

              {audioMode === "tts" ? (
                <>
                  <div>
                    <p className="mb-1.5 flex items-center gap-1 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                      <Mic className="h-3 w-3" aria-hidden /> 发音人（Edge-TTS）
                    </p>
                    <select
                      value={voice}
                      onChange={(e) => setVoice(e.target.value)}
                      className="w-full rounded-xl border bg-slate-950/70 px-3 py-2 text-xs text-white outline-none [&>option]:bg-slate-900"
                      style={{ borderColor: "var(--st-border)" }}
                    >
                      {VOICES.map((v) => (
                        <option key={v.value} value={v.value}>
                          {v.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <p className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">
                      朗读文本 <span className="font-mono normal-case text-slate-600">{ttsText.length}/2000</span>
                    </p>
                    <textarea
                      value={ttsText}
                      onChange={(e) => setTtsText(e.target.value.slice(0, 2000))}
                      rows={6}
                      placeholder="输入要合成为语音的文字…"
                      className="w-full resize-none rounded-xl border bg-slate-950/70 px-3 py-2.5 text-xs leading-relaxed text-slate-100 outline-none placeholder:text-slate-600"
                      style={{ borderColor: "var(--st-border)" }}
                    />
                  </div>
                  <div>
                    <p className="mb-1 flex justify-between text-[10px] font-bold uppercase tracking-widest text-slate-500">
                      <span>语速</span>
                      <span className="font-mono text-slate-300">{speed.toFixed(1)}×</span>
                    </p>
                    <input
                      type="range"
                      min={0.5}
                      max={2}
                      step={0.1}
                      value={speed}
                      onChange={(e) => setSpeed(Number(e.target.value))}
                      className="w-full accent-cyan-400"
                      style={{ accentColor: "var(--st-accent)" }}
                    />
                  </div>
                  <button
                    onClick={() => void renderTts()}
                    disabled={!ttsText.trim() || ttsTask.busy}
                    className="flex w-full items-center justify-center gap-1.5 rounded-xl py-2.5 text-xs font-bold text-slate-950 transition-transform enabled:hover:scale-[1.02] disabled:opacity-40"
                    style={{ background: "linear-gradient(120deg, var(--st-accent), rgba(255,255,255,.82))" }}
                  >
                    <Zap className="h-3.5 w-3.5" aria-hidden />
                    {ttsTask.busy ? "合成中…" : "合成语音"}
                  </button>
                </>
              ) : (
                <>
                  <div>
                    <p className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">音乐描述</p>
                    <textarea
                      value={songDesc}
                      onChange={(e) => setSongDesc(e.target.value.slice(0, 1000))}
                      rows={5}
                      placeholder="描述风格/情绪/乐器…例：轻快的夏日民谣，木吉他为主，海边日落氛围"
                      className="w-full resize-none rounded-xl border bg-slate-950/70 px-3 py-2.5 text-xs leading-relaxed text-slate-100 outline-none placeholder:text-slate-600"
                      style={{ borderColor: "var(--st-border)" }}
                    />
                  </div>
                  <div>
                    <p className="mb-1 flex justify-between text-[10px] font-bold uppercase tracking-widest text-slate-500">
                      <span>时长</span>
                      <span className="font-mono text-slate-300">{duration}s</span>
                    </p>
                    <input
                      type="range"
                      min={5}
                      max={120}
                      step={5}
                      value={duration}
                      onChange={(e) => setDuration(Number(e.target.value))}
                      className="w-full"
                      style={{ accentColor: "var(--st-accent)" }}
                    />
                  </div>
                  <button
                    onClick={renderSong}
                    disabled={!songDesc.trim() || songTask.busy}
                    className="flex w-full items-center justify-center gap-1.5 rounded-xl py-2.5 text-xs font-bold text-slate-950 transition-transform enabled:hover:scale-[1.02] disabled:opacity-40"
                    style={{ background: "linear-gradient(120deg, var(--st-accent), rgba(255,255,255,.82))" }}
                  >
                    <Zap className="h-3.5 w-3.5" aria-hidden />
                    {songTask.busy ? `生成中 ${songTask.progress}%` : "生成音乐"}
                  </button>
                </>
              )}
            </div>
          ) : domain === "video" ? (
            /* ═══ 视频域参数舱 ═══ */
            <div className="space-y-4">
              <div>
                <p className="mb-1.5 text-[10px] font-bold uppercase tracking-widest text-slate-500">画面描述</p>
                <textarea
                  value={videoDesc}
                  onChange={(e) => setVideoDesc(e.target.value.slice(0, 2000))}
                  rows={6}
                  placeholder="描述视频画面与镜头运动…例：无人机掠过霓虹雨夜的都市天际线，缓慢推进"
                  className="w-full resize-none rounded-xl border bg-slate-950/70 px-3 py-2.5 text-xs leading-relaxed text-slate-100 outline-none placeholder:text-slate-600"
                  style={{ borderColor: "var(--st-border)" }}
                />
              </div>
              <div>
                <p className="mb-1 flex justify-between text-[10px] font-bold uppercase tracking-widest text-slate-500">
                  <span>时长</span>
                  <span className="font-mono text-slate-300">{videoDuration}s</span>
                </p>
                <input
                  type="range"
                  min={1}
                  max={60}
                  step={1}
                  value={videoDuration}
                  onChange={(e) => setVideoDuration(Number(e.target.value))}
                  className="w-full"
                  style={{ accentColor: "var(--st-accent)" }}
                />
                <p className="mt-2 rounded-lg border border-dashed border-white/10 px-3 py-2 text-[10px] leading-relaxed text-slate-500">
                  提示：视频引擎需在模型中心配置 video 槽位；未配置时提交会明确报错，不会假装成功。
                </p>
              </div>
              <button
                onClick={renderVideo}
                disabled={!videoDesc.trim() || videoTask.busy}
                className="flex w-full items-center justify-center gap-1.5 rounded-xl py-2.5 text-xs font-bold text-slate-950 transition-transform enabled:hover:scale-[1.02] disabled:opacity-40"
                style={{ background: "linear-gradient(120deg, var(--st-accent), rgba(255,255,255,.82))" }}
              >
                <Zap className="h-3.5 w-3.5" aria-hidden />
                {videoTask.busy ? `生成中 ${videoTask.progress}%` : "生成视频"}
              </button>
            </div>
          ) : domain === "story" || domain === "workflow" ? (
            /* ═══ 角色&Story / 节点拓扑：子能力导航卡 ═══ */
            <div className="space-y-2">
              {(DOMAIN_LINKS[domain] ?? []).map((l) => (
                <Link
                  key={l.to}
                  to={l.to}
                  className="group flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-3 transition-all hover:border-[rgba(var(--st-accent-rgb),.5)] hover:bg-white/[0.06]"
                >
                  <span
                    className="grid h-9 w-9 shrink-0 place-items-center rounded-lg border"
                    style={{ borderColor: "var(--st-border)", color: "var(--st-accent)" }}
                  >
                    {domain === "story" ? <UserRound className="h-4 w-4" aria-hidden /> : <Workflow className="h-4 w-4" aria-hidden />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-xs font-semibold text-slate-200">{l.label}</span>
                    <span className="block truncate text-[10px] text-slate-500">{l.desc}</span>
                  </span>
                  <ArrowRight className="h-4 w-4 shrink-0 text-slate-600 transition-transform group-hover:translate-x-0.5" style={{ color: "var(--st-accent)" }} aria-hidden />
                </Link>
              ))}
            </div>
          ) : (
            /* 兜底占位（不应到达） */
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
                <div
                  className="st-node-pulse relative mx-auto mb-4 grid h-16 w-16 place-items-center rounded-full border"
                  style={{ borderColor: "var(--st-border)" }}
                >
                  <Play className="h-6 w-6" style={accentVar} aria-hidden />
                </div>
                <p className="font-mono text-sm font-bold tracking-widest" style={accentVar}>
                  STUDIO VIEWPORT
                </p>
                <p className="mt-1.5 max-w-sm text-[11px] leading-relaxed text-slate-500">
                  {domain === "music"
                    ? "左侧选择「语音合成」或「音乐生成」，输入内容后开始创作。产出将在视口内以实时频谱回放。"
                    : "在左侧参数舱输入 Prompt 并选择风格预设，点击「渲染图像」开始创作。移动端请先在上方选择域。"}
                </p>
              </div>
            )}

            {/* 音频结果：频谱 + 播放器 */}
            {isAudioResult && task.result?.assetUrl && !task.busy && (
              <AudioStage
                src={task.result.assetUrl}
                accentRgb={accentRgb}
                title={shownKey === "tts" ? `TTS · ${VOICES.find((v) => v.value === voice)?.label ?? voice}` : `MusicGen · ${duration}s`}
              />
            )}

            {/* 视频结果 */}
            {isVideoResult && task.result?.assetUrl && !task.busy && (
              <figure className="flex max-h-full max-w-full flex-col items-center gap-2">
                <video
                  src={task.result.assetUrl}
                  controls
                  autoPlay
                  loop
                  className="max-h-[62vh] rounded-xl border shadow-2xl"
                  style={{ borderColor: "var(--st-border)" }}
                />
                <figcaption className="flex items-center gap-2 font-mono text-[10px] text-slate-500">
                  <span style={accentVar}>{task.result.provider}</span>
                  <span>·</span>
                  <span>{videoDuration}s</span>
                </figcaption>
              </figure>
            )}

            {/* 图片结果 */}
            {!isAudioResult && !isVideoResult && task.result?.assetUrl && !task.busy && (
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
                  onClick={retryShown}
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
              <span className="truncate">{(() => {
                const t = activePrompt();
                return t ? `${t.slice(0, 48)}${t.length > 48 ? "…" : ""}` : "IDLE";
              })()}</span>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <button
                onClick={copyPrompt}
                disabled={!activePrompt()}
                title="复制 Prompt"
                className="flex items-center gap-1 rounded-lg border border-white/10 px-2.5 py-1.5 text-[11px] text-slate-400 transition-colors hover:bg-white/5 disabled:opacity-35"
              >
                <Copy className="h-3 w-3" aria-hidden /> 复制 Prompt
              </button>
              <button
                onClick={pushToAssistant}
                title="推送调度大厅继续对话式创作"
                className="flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-[11px] transition-colors hover:bg-white/5"
                style={{ borderColor: "var(--st-border)", color: "var(--st-accent)" }}
              >
                <Sparkles className="h-3 w-3" aria-hidden /> 推送助手
              </button>
              <a
                href={task.result?.assetUrl ?? "#"}
                download={`saios-studio-${Date.now()}${isAudioResult ? "." + extFromMime(task.result?.mime) : ".png"}`}
                onClick={(e) => {
                  if (!task.result?.assetUrl) e.preventDefault();
                }}
                target={isAudioResult ? undefined : "_blank"}
                rel="noopener"
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

/* ══════════ 音频回放舞台：Web Audio 实时频谱 + 播放控制 ══════════ */
function AudioStage({ src, accentRgb, title }: { src: string; accentRgb: string; title: string }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const graphRef = useRef<{ ac: AudioContext; an: AnalyserNode } | null>(null);
  const rafRef = useRef(0);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState({ cur: 0, dur: 0 });

  function ensureGraph(): boolean {
    const el = audioRef.current;
    if (!el || graphRef.current) return true;
    try {
      const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ac = new AC();
      const source = ac.createMediaElementSource(el);
      const an = ac.createAnalyser();
      an.fftSize = 256;
      an.smoothingTimeConstant = 0.82;
      source.connect(an);
      an.connect(ac.destination);
      graphRef.current = { ac, an };
      return true;
    } catch {
      return false; // 频谱失败不影响播放
    }
  }

  function drawFrame() {
    const cv = canvasRef.current;
    const c2 = cv?.getContext("2d");
    if (!cv || !c2) return;
    const W = (cv.width = cv.clientWidth * 2);
    const H = (cv.height = cv.clientHeight * 2);
    c2.clearRect(0, 0, W, H);
    const bars = 56;
    const gap = 4;
    const bw = (W - gap * (bars - 1)) / bars;
    const g = graphRef.current;
    let data: Uint8Array | null = null;
    if (g) {
      data = new Uint8Array(g.an.frequencyBinCount);
      g.an.getByteFrequencyData(data);
    }
    for (let i = 0; i < bars; i++) {
      const v = data ? data[Math.floor((i * data.length) / bars)]! / 255 : 0.03;
      const h = Math.max(6, v * H * 0.82);
      const x = i * (bw + gap);
      c2.fillStyle = `rgba(${accentRgb},${0.28 + v * 0.72})`;
      c2.beginPath();
      c2.roundRect(x, H - h, bw, h, bw / 2);
      c2.fill();
    }
    if (playing) rafRef.current = requestAnimationFrame(drawFrame);
  }

  useEffect(() => {
    if (playing) {
      rafRef.current = requestAnimationFrame(drawFrame);
    } else {
      cancelAnimationFrame(rafRef.current);
      // 停止时画一次静态低幅
      requestAnimationFrame(drawFrame);
    }
    return () => cancelAnimationFrame(rafRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, accentRgb]);

  async function togglePlay() {
    const el = audioRef.current;
    if (!el) return;
    if (el.paused) {
      ensureGraph();
      await graphRef.current?.ac.resume().catch(() => {});
      await el.play().then(() => setPlaying(true)).catch(() => {});
    } else {
      el.pause();
      setPlaying(false);
    }
  }

  const fmt = (s: number) =>
    `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const pct = time.dur > 0 ? (time.cur / time.dur) * 100 : 0;

  return (
    <div className="w-full max-w-xl">
      <p className="mb-3 flex items-center justify-between font-mono text-[10px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <Music className="h-3.5 w-3.5" style={{ color: `rgb(${accentRgb})` }} aria-hidden />
          {title}
        </span>
        <span className="tabular-nums">
          {fmt(time.cur)} / {fmt(time.dur)}
        </span>
      </p>
      <canvas ref={canvasRef} className="h-40 w-full rounded-xl border" style={{ borderColor: "var(--st-border)", background: "rgba(2,6,17,.55)" }} />
      <div className="mt-3 flex items-center gap-3">
        <button
          onClick={() => void togglePlay()}
          className="grid h-12 w-12 shrink-0 place-items-center rounded-full text-slate-950 shadow-lg transition-transform hover:scale-105"
          style={{ background: "linear-gradient(135deg, var(--st-accent), rgba(255,255,255,.85))" }}
          aria-label={playing ? "暂停" : "播放"}
        >
          {playing ? <Pause className="h-5 w-5" aria-hidden /> : <Play className="ml-0.5 h-5 w-5" aria-hidden />}
        </button>
        <div
          className="group relative h-2 flex-1 cursor-pointer rounded-full bg-white/10"
          onClick={(e) => {
            const el = audioRef.current;
            if (!el || !time.dur) return;
            const rect = e.currentTarget.getBoundingClientRect();
            el.currentTime = ((e.clientX - rect.left) / rect.width) * time.dur;
          }}
        >
          <div
            className="pointer-events-none absolute inset-y-0 left-0 rounded-full"
            style={{ width: `${pct}%`, background: "var(--st-accent)" }}
          />
        </div>
      </div>
      <audio
        ref={audioRef}
        src={src}
        onLoadedMetadata={(e) => setTime({ cur: 0, dur: e.currentTarget.duration || 0 })}
        onTimeUpdate={(e) => setTime((p) => ({ ...p, cur: e.currentTarget.currentTime }))}
        onEnded={() => setPlaying(false)}
        preload="metadata"
      />
    </div>
  );
}
