import { useState } from "react";

import { Check, Copy, ExternalLink } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/layout/PageHeader";
import { useAuthStore } from "@/stores/auth";
import { copyText } from "@/lib/clipboard";

// 按当前访问的 host 动态拼接（本地 8001/8002；云上经反代/端口映射可达）
const ST_URL = `http://${window.location.hostname}:8001`;
const GATEWAY_URL = `http://${window.location.hostname}:8002/v1`;

export function SillyTavernPage() {
  const accessToken = useAuthStore((s) => s.accessToken);
  const [copied, setCopied] = useState(false);

  async function copyToken() {
    if (!accessToken) return;
    await copyText(accessToken);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div>
      <PageHeader
        title="角色扮演（SillyTavern）"
        description="AI 角色扮演聊天室 —— 独立窗口运行，连本机 AIGC 网关"
      />
      <div className="max-w-2xl space-y-4 p-4 md:p-6">
        <div className="rounded-[var(--radius-card)] border border-border bg-surface p-5">
          <h3 className="text-sm font-semibold">第一步：打开 SillyTavern</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            SillyTavern 是独立应用，会在新窗口打开（首次访问按引导设置管理员密码）。
          </p>
          <a href={ST_URL} target="_blank" rel="noreferrer" className="mt-3 inline-block">
            <Button>
              <ExternalLink className="h-4 w-4" aria-hidden />
              打开 SillyTavern
            </Button>
          </a>
        </div>

        <div className="rounded-[var(--radius-card)] border border-border bg-surface p-5">
          <h3 className="text-sm font-semibold">第二步：复制 API Key</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            这是你登录工作台的凭证（24 小时有效），SillyTavern 用它连接 AIGC 网关：
          </p>
          <div className="mt-3 flex items-center gap-2">
            <code className="flex-1 truncate rounded-lg border border-border bg-background px-3 py-2 font-mono text-xs">
              {accessToken ?? "（未登录，请先登录工作台）"}
            </code>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void copyToken()}
              disabled={!accessToken}
            >
              {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
              {copied ? "已复制" : "复制"}
            </Button>
          </div>
        </div>

        <div className="rounded-[var(--radius-card)] border border-border bg-surface p-5">
          <h3 className="text-sm font-semibold">第三步：在 SillyTavern 里配置</h3>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
            <li>右上角设置 → API 连接</li>
            <li>API 选 <code className="font-mono text-xs">Custom (OpenAI)</code></li>
            <li>
              Chat Completion 源填：<code className="font-mono text-xs">{GATEWAY_URL}</code>
            </li>
            <li>API Key 粘贴第二步复制的 token</li>
            <li>模型填 <code className="font-mono text-xs">gpt-oss-120b-medium</code>（或 grok-chat-fast）</li>
            <li>保存后即可开始角色扮演</li>
          </ol>
        </div>
      </div>
    </div>
  );
}
