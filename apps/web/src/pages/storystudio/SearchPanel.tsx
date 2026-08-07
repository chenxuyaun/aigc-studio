import { useEffect, useState } from "react";

import { Search as SearchIcon } from "lucide-react";

import { apiClient } from "@/lib/apiClient";
import type { SearchResultItem } from "@aigc/shared-types";

interface Props {
  projectId: string;
  onOpenChapter: (chapterId: string) => void;
}

/** 项目内「查找」：搜章节/梗概 + 本人知识库文档，点击章节结果跳转编辑器。 */
export function SearchPanel({ projectId, onOpenChapter }: Props) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState<SearchResultItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    const query = q.trim();
    if (!query) {
      setItems(null);
      return;
    }
    setBusy(true);
    setError("");
    const timer = window.setTimeout(() => {
      apiClient
        .get<{ items: SearchResultItem[] }>(
          `/story/projects/${projectId}/search?q=${encodeURIComponent(query)}&limit=15`,
        )
        .then((r) => setItems(r.items))
        .catch((e) => setError(e instanceof Error ? e.message : "搜索失败"))
        .finally(() => setBusy(false));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [q, projectId]);

  return (
    <div className="flex h-full flex-col gap-2 p-3">
      <div className="relative">
        <SearchIcon
          className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="查找前文 / 知识库…"
          className="h-8 w-full rounded-lg border border-border bg-surface pl-8 pr-2 text-xs text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none"
        />
      </div>
      {busy && <p className="text-xs text-muted-foreground">查找中…</p>}
      {error && <p className="text-xs text-danger">{error}</p>}
      {!q && !busy && (
        <p className="pt-6 text-center text-xs text-muted-foreground">
          搜本章节正文、大纲与知识库资料，<br />结果点击章节可直接跳转。
        </p>
      )}
      {q && !busy && items && items.length === 0 && (
        <p className="pt-4 text-center text-xs text-muted-foreground">未找到相关内容</p>
      )}
      <div className="flex-1 space-y-1.5 overflow-y-auto">
        {(items ?? []).map((item) => {
          const isChapter = item.scope === "story" && !!item.meta?.chapter_no;
          return (
            <div
              key={`${item.scope}-${item.id}`}
              className="rounded-lg border border-border bg-surface p-2"
            >
              <div className="flex items-start justify-between gap-1">
                <button
                  onClick={() => (isChapter ? onOpenChapter(item.id) : setExpanded(expanded === item.id ? null : item.id))}
                  className="min-w-0 text-left text-xs font-medium text-foreground hover:text-primary"
                  title={isChapter ? "打开该章节" : "展开资料片段"}
                >
                  {item.title}
                </button>
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {item.scope === "story" ? "章节" : "资料"}
                </span>
              </div>
              <p
                className={`mt-0.5 text-[11px] leading-relaxed text-muted-foreground ${
                  item.scope === "story" || expanded === item.id ? "" : "line-clamp-2"
                }`}
              >
                {item.snippet}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
