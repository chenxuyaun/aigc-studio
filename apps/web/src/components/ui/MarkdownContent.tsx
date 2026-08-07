import { useEffect, useState, type ImgHTMLAttributes, type ReactNode } from "react";

import { Check, Copy } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { apiClient } from "@/lib/apiClient";
import { copyText } from "@/lib/clipboard";

/** Markdown 内容渲染：表格/任务列表/代码块（带复制按钮）。react-markdown 默认不渲染 raw HTML，无 XSS 风险。 */
export function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="markdown-body text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre: CodeBlock,
          img: SmartImg,
          a: (props) => (
            <a
              {...props}
              target="_blank"
              rel="noreferrer noopener"
              className="text-primary underline underline-offset-2"
            />
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

/**
 * 私有媒体图片：/api/ 开头的地址需要 JWT 才能访问（浏览器裸 <img> 会 401）。
 * 带鉴权 fetch → blob → objectURL 渲染；外部 URL 原样直出。
 */
function SmartImg({ src, alt }: ImgHTMLAttributes<HTMLImageElement>) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;

    async function load() {
      if (!src) return;
      if (!src.startsWith("/api/")) {
        setUrl(src);
        return;
      }
      // apiClient 已带 /api/v1 前缀，去掉 markdown 里的绝对前缀
      const path = src.startsWith("/api/v1/") ? src.slice("/api/v1".length) : src;
      try {
        const blob = await apiClient.getBlob(path);
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      } catch {
        if (!cancelled) setUrl(null); // 鉴权失败/不存在：不渲染破图
      }
    }
    void load();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src]);

  if (!src || !url) return null;
  return (
    <img
      src={url}
      alt={alt ?? ""}
      loading="lazy"
      className="max-h-[420px] max-w-full rounded-lg border border-border"
    />
  );
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="group relative my-2 overflow-hidden rounded-lg border border-border bg-surface-raised">
      <button
        type="button"
        className="absolute right-2 top-2 z-10 flex items-center gap-1 rounded-md border border-border bg-surface px-1.5 py-0.5 text-xs text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
        onClick={() => {
          const text = extractText(children);
          if (!text) return;
          void copyText(text).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          });
        }}
        aria-label="复制代码"
      >
        {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
        {copied ? "已复制" : "复制"}
      </button>
      <pre className="overflow-x-auto p-3 text-xs text-foreground">{children}</pre>
    </div>
  );
}

/** 从 react-markdown code 节点提取纯文本。 */
function extractText(node: ReactNode): string {
  if (node == null) return "";
  if (typeof node === "string") return node;
  if (typeof node === "number" || typeof node === "boolean") return String(node);
  if (Array.isArray(node)) return node.map(extractText).join("");
  if (typeof node === "object" && "props" in node) {
    return extractText((node as { props: { children?: ReactNode } }).props?.children);
  }
  return "";
}
