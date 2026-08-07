import { useState, type FormEvent } from "react";

import { useNavigate } from "react-router-dom";

import type { User } from "@aigc/shared-types";

import { Button } from "@/components/ui/Button";
import { Field, Input } from "@/components/ui/Field";
import { AppError, apiClient } from "@/lib/apiClient";
import { useAuthStore } from "@/stores/auth";

interface TokenResponse {
  access_token: string;
  refresh_token: string;
}

const R2 = "https://pub-54e40727ca014de0a7fecf608f7b0412.r2.dev/images/originals";
const COLLAGE = [14798, 14657, 25960, 19660, 14385, 16163, 16814, 14513, 15908];

export function LoginPage() {
  const navigate = useNavigate();
  const [formError, setFormError] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<{ username?: string; password?: string }>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

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

  return (
    <div className="grid min-h-dvh bg-background md:grid-cols-[1.1fr_1fr]">
      {/* 品牌侧：真实作品拼贴 */}
      <div className="relative hidden overflow-hidden md:block">
        <div className="absolute inset-0 grid grid-cols-3 gap-2 p-2">
          {COLLAGE.map((id) => (
            <img
              key={id}
              src={`${R2}/${id}.jpg`}
              alt=""
              loading="lazy"
              className="h-full w-full rounded-xl object-cover"
            />
          ))}
        </div>
        <div className="absolute inset-0 bg-gradient-to-br from-background/85 via-background/55 to-background/85" />
        <div className="relative flex h-full flex-col justify-between p-9">
          <span className="font-mono-ui text-xs uppercase tracking-[0.16em] text-muted-foreground">
            AI 创作中心
          </span>
          <div>
            <h2 className="max-w-[14ch] text-3xl font-bold tracking-tight text-balance">
              把想法，变成画面。
            </h2>
            <p className="mt-3 max-w-[30ch] text-sm text-muted-foreground">
              文本 · 图片 · 视频 · 语音，一个工作台。无需任何模型 Key 也能完整体验。
            </p>
          </div>
        </div>
      </div>

      {/* 表单侧 */}
      <div className="flex flex-col justify-center px-6 py-12 sm:px-12">
        <div className="mx-auto w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5">
            <img
              src="/logo.png"
              alt="AIGC Studio"
              className="h-9 w-9 rounded-xl object-cover"
              draggable={false}
            />
            <span className="text-lg font-semibold tracking-tight">AIGC Studio</span>
          </div>
          <p className="font-mono-ui text-xs uppercase tracking-[0.16em] text-muted-foreground">
            欢迎回来
          </p>
          <h1 className="mb-6 mt-1 text-2xl font-semibold tracking-tight">登录你的创作空间</h1>

          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <Field label="用户名或邮箱" required error={fieldErrors.username}>
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  autoComplete="username"
                  aria-describedby={describedBy}
                  aria-invalid={Boolean(fieldErrors.username)}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              )}
            </Field>
            <Field label="密码" required error={fieldErrors.password}>
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  type="password"
                  autoComplete="current-password"
                  aria-describedby={describedBy}
                  aria-invalid={Boolean(fieldErrors.password)}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              )}
            </Field>

            {formError && (
              <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
                {formError}
              </p>
            )}

            <Button type="submit" className="w-full" loading={isSubmitting}>
              登录
            </Button>
            {/* 默认口令只在本机开发环境展示，生产构建不提示 */}
            {import.meta.env.DEV && (
              <p className="text-center text-xs text-muted-foreground">
                默认管理员：admin / admin123
              </p>
            )}
          </form>
        </div>
      </div>
    </div>
  );
}
