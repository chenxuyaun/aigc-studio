import { useEffect, useState, type FormEvent } from "react";

import { useNavigate } from "react-router-dom";

import type { User } from "@aigc/shared-types";

import { AppError, apiClient } from "@/lib/apiClient";
import { useAuthStore } from "@/stores/auth";

interface TokenResponse {
  access_token: string;
  refresh_token: string;
}

// 真实作品墙：你 R2 图床上由 AI 生成的作品（登录页左墙展示真实的个人创作）
const R2 = "https://pub-54e40727ca014de0a7fecf608f7b0412.r2.dev/images/originals";
const COLLAGE = [14798, 14657, 25960, 19660, 14385, 16163, 16814, 14513, 15908];

// 能力巡览（登录页品牌区底部标签，映射真实 MCP 创作能力）
const CAPS = [
  { icon: "🖼️", label: "神经网络生图", cls: "text-cyan-300 border-cyan-500/30", iconCls: "text-cyan-400" },
  { icon: "✍️", label: "沉浸式长文精修", cls: "text-purple-300 border-purple-500/30", iconCls: "text-purple-400" },
  { icon: "🎵", label: "AI 编曲写歌", cls: "text-emerald-300 border-emerald-500/30", iconCls: "text-emerald-400" },
  { icon: "🔊", label: "语音合成 TTS", cls: "text-rose-300 border-rose-500/30", iconCls: "text-rose-400" },
  { icon: "🎴", label: "漫画分镜绘制", cls: "text-amber-300 border-amber-500/30", iconCls: "text-amber-400" },
  { icon: "🎭", label: "拟真人设演练", cls: "text-indigo-300 border-indigo-500/30", iconCls: "text-indigo-400" },
];

export function LoginPage() {
  const navigate = useNavigate();
  const [formError, setFormError] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<{ username?: string; password?: string }>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  // 个人服务器免登录：进入登录页先静默尝试 /auth/auto-login（nginx 注入密钥头）
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const tokens = await apiClient.post<TokenResponse>("/auth/auto-login", {});
        if (cancelled) return;
        const me = await apiClient.get<User>("/auth/me");
        if (cancelled) return;
        useAuthStore.getState().setAuth(me, tokens.access_token, tokens.refresh_token);
        navigate("/", { replace: true });
      } catch {
        // 未开启自动登录 → 正常显示登录表单
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  // 背景粒子（轻量）
  useEffect(() => {
    const cv = document.getElementById("saios-bg-canvas") as HTMLCanvasElement | null;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    let w = (cv.width = window.innerWidth);
    let h = (cv.height = window.innerHeight);
    const onResize = () => {
      w = cv.width = window.innerWidth;
      h = cv.height = window.innerHeight;
    };
    window.addEventListener("resize", onResize);
    type P = { x: number; y: number; vx: number; vy: number; r: number; a: number };
    const parts: P[] = Array.from({ length: 42 }, (): P => ({
      x: Math.random() * w,
      y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.25,
      vy: (Math.random() - 0.5) * 0.25,
      r: Math.random() * 1.5 + 0.5,
      a: Math.random() * 0.5 + 0.15,
    }));
    let raf = 0;
    const step = () => {
      ctx.clearRect(0, 0, w, h);
      parts.forEach((p) => {
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0) p.x = w;
        if (p.x > w) p.x = 0;
        if (p.y < 0) p.y = h;
        if (p.y > h) p.y = 0;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(0,242,254,${p.a})`;
        ctx.fill();
      });
      for (let i = 0; i < parts.length; i++) {
        const pi = parts[i]!;
        for (let j = i + 1; j < parts.length; j++) {
          const pj = parts[j]!;
          const dx = pi.x - pj.x;
          const dy = pi.y - pj.y;
          const d = Math.sqrt(dx * dx + dy * dy);
          if (d < 110) {
            ctx.beginPath();
            ctx.moveTo(pi.x, pi.y);
            ctx.lineTo(pj.x, pj.y);
            ctx.strokeStyle = `rgba(0,242,254,${0.1 * (1 - d / 110)})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }
      raf = requestAnimationFrame(step);
    };
    step();
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  function validate(): boolean {
    const next: { username?: string; password?: string } = {};
    if (!username.trim()) next.username = "请输入用户名或邮箱";
    if (!password) next.password = "请输入密码";
    setFieldErrors(next);
    return Object.keys(next).length === 0;
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!validate()) return;
    setIsSubmitting(true);
    try {
      const tokens = await apiClient.post<TokenResponse>("/auth/login", {
        username: username.trim(),
        password,
      });
      useAuthStore.setState({
        accessToken: tokens.access_token,
        refreshToken: tokens.refresh_token,
      });
      const me = await apiClient.get<User>("/auth/me");
      useAuthStore.getState().setAuth(me, tokens.access_token, tokens.refresh_token);
      navigate("/", { replace: true });
    } catch (err) {
      useAuthStore.getState().logout();
      setFormError(err instanceof AppError ? err.message : "登录失败，请稍后重试");
    } finally {
      setIsSubmitting(false);
    }
  }

  const inputBase =
    "w-full rounded-xl border bg-white/[0.04] py-3 pl-10 pr-4 text-sm text-slate-100 placeholder:text-slate-500 outline-none transition-all" +
    " border-white/10 focus:border-cyan-400/70 focus:bg-white/[0.06] focus:shadow-[0_0_18px_rgba(0,242,254,0.2)]";

  return (
    <div
      className="relative flex min-h-dvh w-full overflow-hidden bg-[#05070c]"
      style={{ color: "#f1f5f9" }}
    >
      {/* 背景粒子 + 光晕 */}
      <canvas
        id="saios-bg-canvas"
        className="pointer-events-none fixed inset-0 z-0 opacity-40"
        aria-hidden
      />
      <div
        className="pointer-events-none absolute -left-20 -top-20 z-0 h-[550px] w-[550px] rounded-full animate-pulse"
        style={{ background: "radial-gradient(circle, rgba(0,242,254,0.15) 0%, transparent 70%)" }}
      />
      <div
        className="pointer-events-none absolute -bottom-24 -right-24 z-0 h-[650px] w-[650px] rounded-full animate-pulse"
        style={{ background: "radial-gradient(circle, rgba(157,78,221,0.13) 0%, transparent 70%)" }}
      />

      <div className="relative z-10 mx-auto flex w-full max-w-7xl flex-col px-4 sm:px-6 lg:px-8 pt-6 pb-8">
        {/* 顶栏 */}
        <header className="flex items-center justify-between py-2">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-cyan-500 via-indigo-600 to-purple-600 p-[1.5px]">
              <div className="flex h-full w-full items-center justify-center rounded-[10px] bg-slate-950">
                <span className="text-lg">🧠</span>
              </div>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span
                  className="bg-gradient-to-r from-white via-slate-200 to-cyan-400 bg-clip-text font-mono text-lg font-extrabold tracking-widest text-transparent"
                >
                  saiOS
                </span>
                <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 font-mono text-[10px] tracking-wide text-cyan-300">
                  v3.8 AIGC
                </span>
              </div>
              <span className="text-[11px] font-medium tracking-wider text-slate-400">
                共生智能操作系统
              </span>
            </div>
          </div>
          <div className="hidden items-center gap-2.5 rounded-full border border-white/10 bg-slate-900/80 px-3 py-1.5 text-xs md:flex">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
            <span className="font-mono text-slate-300">NODE-A12: ONLINE</span>
          </div>
        </header>

        {/* 主区：左墙 + 右登录 */}
        <main className="grid flex-1 items-center gap-8 py-6 lg:grid-cols-12 lg:py-2">
          {/* 左：品牌语 + 真实作品墙 + 能力巡览 */}
          <div className="hidden space-y-8 pr-2 lg:col-span-7 lg:flex lg:flex-col lg:justify-between">
            <div className="space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-cyan-500/20 bg-gradient-to-r from-cyan-500/10 via-purple-500/10 to-transparent px-3.5 py-1.5 text-xs font-medium text-cyan-300">
                <span>✨</span> 下一代个人多模态 AIGC 创作引擎
              </div>
              <h1 className="text-4xl font-black leading-tight tracking-tight text-white lg:text-5xl">
                把想法，
                <span className="saios-grad-text">变成画面</span>与现实。
              </h1>
              <p className="max-w-xl text-sm leading-relaxed text-slate-400 lg:text-base">
                saiOS 整合神经网络生图、长篇写作、旋律生成、角色演练与自动化流程，打造人机共生的极客数字工作室。
              </p>
            </div>

            {/* 真实作品拼贴墙（非对称 5 图，挂图渐变兜底不留黑洞） */}
            <div className="grid grid-cols-3 gap-3.5">
              {COLLAGE.slice(0, 5).map((id, idx) => {
                // 第二版布局：第 1-3 张高 h-44；第 4 张 h-40，第 5 张横跨 2 列 h-40
                const tall = idx < 3;
                const span2 = idx === 4;
                const fallback = [
                  "linear-gradient(135deg,#0e7490,#1e3a8a)",
                  "linear-gradient(135deg,#7c3aed,#0e7490)",
                  "linear-gradient(135deg,#059669,#1e3a8a)",
                  "linear-gradient(135deg,#b45309,#7c3aed)",
                  "linear-gradient(135deg,#0e7490,#7c3aed)",
                ][idx];
                return (
                  <div
                    key={id}
                    className={
                      (span2 ? "col-span-2 " : "") +
                      "saios-art group relative cursor-pointer overflow-hidden rounded-2xl border border-white/10 " +
                      (tall ? "h-44" : "h-40")
                    }
                    style={
                      idx === 1
                        ? { animation: "saiosFloat 8s ease-in-out infinite" }
                        : idx === 3
                          ? { animation: "saiosFloatRev 9s ease-in-out infinite" }
                          : undefined
                    }
                  >
                    <div
                      className="absolute inset-0"
                      style={{ background: fallback }}
                    />
                    <img
                      src={`${R2}/${id}.jpg`}
                      alt=""
                      loading="lazy"
                      className="relative h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
                      onError={(e) => {
                        e.currentTarget.style.opacity = "0";
                      }}
                    />
                    <div className="saios-art-shade absolute inset-0" />
                    <span className="absolute bottom-2.5 left-2.5 rounded-md border border-cyan-500/30 bg-black/60 font-mono text-[10px] text-cyan-300 backdrop-blur-md">
                      {["生图 · 自研", "角色 · 演练", "写歌 · 声学", "漫画 · 分镜", "写作 · 长编"][idx % 5]}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* 能力巡览 */}
            <div className="space-y-2">
              <span className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest text-slate-400">
                <span className="text-cyan-400">▣</span> 多模态能力巡览
              </span>
              <div className="flex flex-wrap gap-2">
                {CAPS.map((c) => (
                  <span
                    key={c.label}
                    className={`flex items-center gap-1.5 rounded-xl border bg-slate-900/80 px-3 py-1.5 text-xs ${c.cls}`}
                  >
                    <span>{c.icon}</span> {c.label}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* 右：玻璃登录卡 */}
          <div className="w-full max-w-md lg:col-span-5 lg:mx-auto">
            <div className="saios-glass-accent relative overflow-hidden rounded-3xl border border-white/10 p-6 sm:p-8">
              <div className="absolute left-1/4 right-1/4 top-0 h-[2px] bg-gradient-to-r from-transparent via-cyan-400 to-transparent" />

              <div className="mb-8 space-y-2 text-center">
                <div className="mb-2 inline-flex h-14 w-14 items-center justify-center rounded-2xl border border-cyan-500/40 bg-gradient-to-tr from-cyan-500/20 via-indigo-500/20 to-purple-500/20 shadow-[0_0_25px_rgba(0,242,254,0.3)]">
                  <span className="animate-pulse text-2xl">🧠</span>
                </div>
                <h2 className="text-2xl font-bold tracking-wide text-white">SAIOS · AIGC Studio</h2>
                <p className="text-xs text-slate-400">连接个人认知神经网络，进入创作控制台</p>
              </div>

              <form onSubmit={onSubmit} noValidate className="space-y-4">
                <div className="space-y-1.5">
                  <label className="flex items-center justify-between text-xs font-medium text-slate-300">
                    <span>管理员账号</span>
                    {fieldErrors.username && (
                      <span className="text-[11px] text-rose-400">{fieldErrors.username}</span>
                    )}
                  </label>
                  <div className="relative">
                    <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400">👤</span>
                    <input
                      type="text"
                      autoComplete="username"
                      placeholder="输入系统账户名称"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      className={inputBase}
                      aria-invalid={Boolean(fieldErrors.username)}
                    />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label className="flex items-center justify-between text-xs font-medium text-slate-300">
                    <span>系统访问密码</span>
                    {fieldErrors.password && (
                      <span className="text-[11px] text-rose-400">{fieldErrors.password}</span>
                    )}
                  </label>
                  <div className="relative">
                    <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400">🔒</span>
                    <input
                      type={showPw ? "text" : "password"}
                      autoComplete="current-password"
                      placeholder="输入访问密码"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className={inputBase}
                      aria-invalid={Boolean(fieldErrors.password)}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPw((v) => !v)}
                      aria-label={showPw ? "隐藏密码" : "显示密码"}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 transition-colors hover:text-slate-200"
                    >
                      {showPw ? "🙈" : "👁️"}
                    </button>
                  </div>
                </div>

                {formError && (
                  <div
                    role="alert"
                    className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/15 p-3 text-xs text-rose-300"
                  >
                    <span>⚠️</span> {formError}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="saios-glow-btn group relative mt-4 flex w-full items-center justify-center gap-2 overflow-hidden rounded-xl py-3.5 text-sm font-bold tracking-wider text-slate-950 shadow-[0_0_20px_rgba(0,242,254,0.3)] transition-all hover:-translate-y-0.5"
                >
                  <span className="saios-shimmer absolute inset-0" />
                  <span className="relative flex items-center gap-2">
                    {isSubmitting ? (
                      <>
                        <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-900 border-t-transparent" />
                        正在连接神经算力节点…
                      </>
                    ) : (
                      <>
                        <span>⚡</span> 登 录 创 作 中 枢
                      </>
                    )}
                  </span>
                </button>
              </form>

              <div className="mt-6 flex items-center justify-between border-t border-white/5 pt-4 text-[11px] text-slate-500">
                <span className="flex items-center gap-1">
                  <span className="text-cyan-400">🛡️</span> 端到端加密验证
                </span>
                <span>saiOS Engine v3.8.2</span>
              </div>
            </div>
          </div>
        </main>

        {/* 页脚（备案号） */}
        <footer className="mt-8 flex flex-col items-center justify-between gap-2 border-t border-white/10 pt-4 text-xs text-slate-400 sm:flex-row">
          <span>© 2026 saiOS · AIGC Studio. All Rights Reserved.</span>
          <a
            href="https://beian.miit.gov.cn/"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 underline decoration-slate-600 underline-offset-4 transition-colors hover:text-cyan-400"
          >
            <span className="text-cyan-400">🛡️</span> 蜀ICP备2026023925号-2
          </a>
        </footer>
      </div>

      {/* 页面私有样式 */}
      <style>{`
        .saios-grad-text{
          background:linear-gradient(90deg,#fff 0%,#00f2fe 30%,#a855f7 70%,#fff 100%);
          background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:transparent;
          -webkit-text-fill-color:transparent;animation:saiosShimmer 6s linear infinite;
        }
        @keyframes saiosShimmer{to{background-position:-200% center}}
        .saios-glass-accent{
          background:rgba(13,19,35,0.75);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);
          border-color:rgba(0,242,254,0.2);box-shadow:0 0 30px rgba(0,242,254,0.08),0 20px 40px rgba(0,0,0,0.6);
        }
        .saios-glow-btn{
          background:linear-gradient(135deg,#00f2fe 0%,#4facfe 50%,#9d4edd 100%);
          background-size:200% 200%;animation:saiosBgShift 4s ease infinite;
        }
        .saios-glow-btn:hover{box-shadow:0 0 25px rgba(0,242,254,0.5),0 0 10px rgba(157,78,221,0.3)}
        @keyframes saiosBgShift{0%,100%{background-position:0% 50%}50%{background-position:100% 50%}}
        .saios-shimmer{background:linear-gradient(90deg,transparent,rgba(255,255,255,0.25),transparent);background-size:200% 100%;animation:saiosShine 2.6s linear infinite}
        @keyframes saiosShine{0%{background-position:-150% 0}100%{background-position:150% 0}}
        .saios-art{transform:translateY(0)}
        @keyframes saiosFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-8px)}}
        @keyframes saiosFloatRev{0%,100%{transform:translateY(0) rotate(0deg)}50%{transform:translateY(8px) rotate(-1deg)}}
        .saios-art-shade{background:linear-gradient(to top,rgba(5,7,12,0.85) 0%,rgba(5,7,12,0.1) 60%,transparent 100%);opacity:.85;transition:opacity .3s}
        .saios-art:hover .saios-art-shade{opacity:.5}
        ::-webkit-scrollbar{width:6px;height:6px}
        ::-webkit-scrollbar-track{background:rgba(5,7,12,0.9)}
        ::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.15);border-radius:4px}
        ::-webkit-scrollbar-thumb:hover{background:rgba(0,242,254,0.4)}
      `}</style>
    </div>
  );
}
