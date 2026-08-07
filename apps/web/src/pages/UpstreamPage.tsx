import { useEffect, useState } from "react";

import { Activity, Bot, Database, Image as ImageIcon, RefreshCw, Server, Zap } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/layout/PageHeader";
import { AppError, apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";

interface UpstreamStatus {
  grok_pool: { total: number; active: number; error?: string };
  register: {
    reachable: boolean;
    phase?: string;
    current?: number;
    total?: number;
    success?: number;
    failed?: number;
    error?: string;
  };
  grok_image: { ok: boolean; error?: string; cached?: boolean };
  cpa: { reachable: boolean; error?: string };
}

function StatusCard({
  title,
  icon: Icon,
  ok,
  children,
}: {
  title: string;
  icon: typeof Server;
  ok: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="flex items-center gap-2 text-sm font-semibold">
          <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
          {title}
        </span>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-xs font-medium",
            ok ? "bg-success/15 text-success" : "bg-danger/15 text-danger",
          )}
        >
          {ok ? "正常" : "异常"}
        </span>
      </div>
      <div className="space-y-1 text-sm text-muted-foreground">{children}</div>
    </div>
  );
}

export function UpstreamPage() {
  const [status, setStatus] = useState<UpstreamStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastTask, setLastTask] = useState("");

  async function load() {
    setLoading(true);
    try {
      const d = await apiClient.get<UpstreamStatus>("/upstream/status");
      setStatus(d);
      setError("");
    } catch (e) {
      setError(e instanceof AppError ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 30000);
    return () => clearInterval(timer);
  }, []);

  async function triggerBatch() {
    setBusy(true);
    try {
      const d = await apiClient.post<{ id: string }>("/upstream/register", { run_count: 10 });
      setLastTask(d.id);
      setError("");
    } catch (e) {
      setError(e instanceof AppError ? e.message : "触发失败");
    } finally {
      setBusy(false);
    }
  }

  const grokOk = (status?.grok_image.ok ?? false) && !status?.grok_pool.error;
  const regPhase = status?.register.phase;

  return (
    <div>
      <PageHeader
        title="上游状态"
        description="grok 账号池 · 注册机 · 生成能力一览（每 30 秒自动刷新）"
      />
      <div className="space-y-4 p-4 md:p-6">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" onClick={() => void load()} loading={loading}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            刷新
          </Button>
          <Button size="sm" onClick={() => void triggerBatch()} loading={busy}>
            <Zap className="h-3.5 w-3.5" aria-hidden />
            立即注册一批（10 个）
          </Button>
          {lastTask && (
            <span className="text-xs text-muted-foreground">
              注册任务已提交：{lastTask.slice(0, 8)}…（见任务中心）
            </span>
          )}
        </div>

        {error && <p className="text-sm text-danger">{error}</p>}
        {loading && !status && <p className="text-sm text-muted-foreground">加载中…</p>}

        {status && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-2">
            <StatusCard title="Grok 账号池" icon={Database} ok={grokOk}>
              <p>
                总数 <b className="text-foreground">{status.grok_pool.total}</b> · Active{" "}
                <b className="text-foreground">{status.grok_pool.active}</b>
              </p>
              {status.grok_pool.error && <p className="text-danger">{status.grok_pool.error}</p>}
            </StatusCard>

            <StatusCard
              title="Grok 图片生成"
              icon={ImageIcon}
              ok={status.grok_image.ok}
            >
              <p>{status.grok_image.ok ? "可用（探测成功）" : "不可用（限流/风控）"}</p>
              {status.grok_image.error && <p className="text-danger">{status.grok_image.error}</p>}
              {status.grok_image.cached && <p className="text-xs">缓存结果（10 分钟内）</p>}
            </StatusCard>

            <StatusCard
              title="注册机"
              icon={Bot}
              ok={status.register.reachable && regPhase !== undefined}
            >
              {status.register.reachable ? (
                <>
                  <p>
                    状态：<b className="text-foreground">{regPhase ?? "unknown"}</b>
                    {typeof status.register.current === "number" && (
                      <span>
                        {" "}
                        · 本轮 {status.register.current}/{status.register.total}
                      </span>
                    )}
                  </p>
                  <p>
                    成功 {status.register.success ?? 0} · 失败 {status.register.failed ?? 0}
                  </p>
                  {status.register.error && (
                    <p className="text-danger">{status.register.error}</p>
                  )}
                </>
              ) : (
                <p className="text-danger">{status.register.error || "不可达"}</p>
              )}
            </StatusCard>

            <StatusCard title="GPT-OSS（cpa）" icon={Server} ok={status.cpa.reachable}>
              <p>{status.cpa.reachable ? "在线（12 个模型）" : "离线"}</p>
              {status.cpa.error && <p className="text-danger">{status.cpa.error}</p>}
            </StatusCard>
          </div>
        )}

        <div className="rounded-xl border border-border bg-surface p-4 text-xs text-muted-foreground">
          <Activity className="mr-1 inline h-3.5 w-3.5" aria-hidden />
          自动机制：账号健康巡检每 30 分钟 · 注册批次每 4 小时自动补号（可在 .env 调整
          REGISTER_BATCH_INTERVAL_HOURS / REGISTER_BATCH_COUNT）· 本页状态每 30 秒刷新
        </div>
      </div>
    </div>
  );
}
