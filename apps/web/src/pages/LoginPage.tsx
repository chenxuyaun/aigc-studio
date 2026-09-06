import { useEffect, useState, type FormEvent } from "react";

import { useNavigate } from "react-router-dom";

import type { User } from "@aigc/shared-types";

import {
  AlertTriangle,
  AudioLines,
  BrainCircuit,
  Clapperboard,
  Drama,
  Eye,
  EyeOff,
  Image,
  Layers,
  Lock,
  LogIn,
  Music,
  PenLine,
  ShieldCheck,
  Sparkles,
  User as UserIcon,
} from "lucide-react";

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
  { icon: Image, label: "神经网络生图" },
  { icon: PenLine, label: "沉浸式长文精修" },
  { icon: Music, label: "AI 编曲写歌" },
  { icon: AudioLines, label: "语音合成 TTS" },
  { icon: Clapperboard, label: "漫画分镜绘制" },
  { icon: Drama, label: "拟真人设演练" },
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
    "w-full rounded-xl border border-border bg-surface py-3 pl-10 pr-4 text-sm text-foreground placeholder:text-muted-foreground outline-none transition-colors" +
    " focus:border-primary/60 focus-visible:ring-2 focus-visible:ring-primary/30";

  return (
    <div className="relative flex min-h-dvh w-full overflow-hidden bg-background text-foreground">
      <div className="relative z-10 mx-auto flex w-full max-w-7xl flex-col px-4 sm:px-6 lg:px-8 pt-6 pb-8">
        {/* 顶栏 */}
        <header className="flex items-center justify-between py-2">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <BrainCircuit className="h-5 w-5" aria-hidden />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-serif text-xl font-semibold text-foreground">saiOS</span>
                <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 font-mono text-[10px] text-primary-text">
                  v3.8 AIGC
                </span>
              </div>
              <span className="text-sm font-medium text-muted-foreground">共生智能操作系统</span>
            </div>
          </div>
          <div className="hidden items-center gap-2 rounded-full border border-border bg-surface px-3 py-1.5 text-xs text-muted-foreground md:flex">
            <span className="h-2 w-2 rounded-full bg-primary" />
            <span className="font-mono">NODE-A12: ONLINE</span>
          </div>
        </header>

        {/* 主区：左墙 + 右登录 */}
        <main className="grid flex-1 items-center gap-8 py-6 lg:grid-cols-12 lg:py-2">
          {/* 左：品牌语 + 真实作品墙 + 能力巡览 */}
          <div className="hidden space-y-8 pr-2 lg:col-span-7 lg:flex lg:flex-col lg:justify-between">
            <div className="space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-3.5 py-1.5 text-sm font-medium text-primary-text">
                <Sparkles className="h-3.5 w-3.5" aria-hidden /> 下一代个人多模态 AIGC 创作引擎
              </div>
              <h1 className="text-balance font-serif text-4xl font-semibold leading-tight text-foreground lg:text-5xl">
                把想法，变成画面与现实。
              </h1>
              <p className="max-w-xl text-sm leading-relaxed text-muted-foreground lg:text-base">
                saiOS 整合神经网络生图、长篇写作、旋律生成、角色演练与自动化流程，打造人机共生的极客数字工作室。
              </p>
            </div>

            {/* 真实作品拼贴墙（非对称 5 图，挂图失败回退素底不留黑洞） */}
            <div className="grid grid-cols-3 gap-3.5">
              {COLLAGE.slice(0, 5).map((id, idx) => {
                // 第二版布局：第 1-3 张高 h-44；第 4 张 h-40，第 5 张横跨 2 列 h-40
                const tall = idx < 3;
                const span2 = idx === 4;
                return (
                  <div
                    key={id}
                    className={
                      (span2 ? "col-span-2 " : "") +
                      "relative cursor-pointer overflow-hidden rounded-2xl border border-border bg-border " +
                      (tall ? "h-44" : "h-40")
                    }
                  >
                    <img
                      src={`${R2}/${id}.jpg`}
                      alt=""
                      loading="lazy"
                      className="relative h-full w-full object-cover"
                      onError={(e) => {
                        e.currentTarget.style.opacity = "0";
                      }}
                    />
                    <span className="absolute bottom-2.5 left-2.5 rounded-md border border-border bg-surface/90 px-1.5 py-0.5 font-mono text-[10px] text-primary-text">
                      {["生图 · 自研", "角色 · 演练", "写歌 · 声学", "漫画 · 分镜", "写作 · 长编"][idx % 5]}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* 能力巡览 */}
            <div className="space-y-2">
              <span className="flex items-center gap-1.5 text-sm font-medium text-muted-foreground">
                <Layers className="h-4 w-4 text-primary-text" aria-hidden /> 多模态能力巡览
              </span>
              <div className="flex flex-wrap gap-2">
                {CAPS.map((c) => (
                  <span
                    key={c.label}
                    className="flex items-center gap-1.5 rounded-xl border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs text-primary-text"
                  >
                    <c.icon className="h-3.5 w-3.5" aria-hidden /> {c.label}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* 右：纸卡登录 */}
          <div className="w-full max-w-md lg:col-span-5 lg:mx-auto">
            <div className="relative rounded-2xl border border-border bg-surface p-6 shadow-zen sm:p-8">
              <div className="mb-8 space-y-2 text-center">
                <div className="mb-2 inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-primary text-primary-foreground">
                  <BrainCircuit className="h-6 w-6" aria-hidden />
                </div>
                <h2 className="text-balance font-serif text-xl font-semibold text-foreground">SAIOS · AIGC Studio</h2>
                <p className="text-sm text-muted-foreground">连接个人认知神经网络，进入创作控制台</p>
              </div>

              <form onSubmit={onSubmit} noValidate className="space-y-4">
                <div className="space-y-1.5">
                  <label className="flex items-center justify-between text-sm font-medium text-foreground">
                    <span>管理员账号</span>
                    {fieldErrors.username && (
                      <span className="text-[11px] text-danger">{fieldErrors.username}</span>
                    )}
                  </label>
                  <div className="relative">
                    <UserIcon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
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
                  <label className="flex items-center justify-between text-sm font-medium text-foreground">
                    <span>系统访问密码</span>
                    {fieldErrors.password && (
                      <span className="text-[11px] text-danger">{fieldErrors.password}</span>
                    )}
                  </label>
                  <div className="relative">
                    <Lock className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
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
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {showPw ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
                    </button>
                  </div>
                </div>

                {formError && (
                  <div
                    role="alert"
                    className="flex items-center gap-2 rounded-xl border border-danger/30 bg-danger/10 p-3 text-xs text-danger"
                  >
                    <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden /> {formError}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary-hover disabled:opacity-60"
                >
                  {isSubmitting ? (
                    <>
                      <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
                      正在验证…
                    </>
                  ) : (
                    <>
                      <LogIn className="h-4 w-4" aria-hidden /> 登录创作中枢
                    </>
                  )}
                </button>
              </form>

              <div className="mt-6 flex items-center justify-between border-t border-border pt-4 text-[11px] text-muted-foreground">
                <span className="flex items-center gap-1">
                  <ShieldCheck className="h-3.5 w-3.5 text-primary-text" aria-hidden /> 端到端加密验证
                </span>
                <span>saiOS Engine v3.8.2</span>
              </div>
            </div>
          </div>
        </main>

        {/* 页脚（备案号） */}
        <footer className="mt-8 flex flex-col items-center justify-between gap-2 border-t border-border pt-4 text-xs text-muted-foreground sm:flex-row">
          <span>© 2026 saiOS · AIGC Studio. All Rights Reserved.</span>
          <a
            href="https://beian.miit.gov.cn/"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 underline decoration-border underline-offset-4 transition-colors hover:text-primary-text"
          >
            <ShieldCheck className="h-3.5 w-3.5 text-primary-text" aria-hidden /> 蜀ICP备2026023925号-2
          </a>
        </footer>
      </div>

      {/* 页面私有样式（仅保留中性滚动条） */}
      <style>{`
        ::-webkit-scrollbar{width:6px;height:6px}
        ::-webkit-scrollbar-track{background:var(--color-background)}
        ::-webkit-scrollbar-thumb{background:var(--color-border);border-radius:4px}
        ::-webkit-scrollbar-thumb:hover{background:var(--color-border-strong)}
      `}</style>
    </div>
  );
}