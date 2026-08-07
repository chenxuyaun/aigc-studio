import { useEffect, useMemo, useState } from "react";

import { Search as SearchIcon } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";
import type { SearchResultItem } from "@aigc/shared-types";

const SCOPE_TABS: { value: string; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "knowledge", label: "知识库" },
  { value: "story", label: "章节" },
  { value: "prompts", label: "提示词" },
  { value: "agents", label: "Agent" },
  { value: "assets", label: "素材" },
  { value: "asmr", label: "ASMR" },
];

function resultTarget(item: SearchResultItem): string {
  switch (item.scope) {
    case "story": {
      const projectId = String(item.meta?.project_id ?? "");
      return projectId ? `/story/${projectId}?chapter=${item.id}` : "/story";
    }
    case "knowledge":
      return "/knowledge";
    case "prompts":
      return `/prompts?q=${encodeURIComponent(item.title)}`;
    case "agents":
      return `/agents?search=${encodeURIComponent(item.title)}`;
    case "asmr":
      return `/asmr?q=${encodeURIComponent(item.title)}`;
    default:
      return "/assets";
  }
}

export function SearchPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [input, setInput] = useState(params.get("q") ?? "");
  const [scope, setScope] = useState("all");
  const [items, setItems] = useState<SearchResultItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const q = params.get("q") ?? "";

  useEffect(() => {
    if (!q.trim()) {
      setItems(null);
      return;
    }
    setBusy(true);
    setError("");
    const sc = scope === "all" ? "" : `&scope=${scope}`;
    apiClient
      .get<{ items: SearchResultItem[] }>(`/search?q=${encodeURIComponent(q)}&limit=30${sc}`)
      .then((r) => setItems(r.items))
      .catch((e) => setError(e instanceof Error ? e.message : "搜索失败"))
      .finally(() => setBusy(false));
  }, [q, scope]);

  const grouped = useMemo(() => {
    const g = new Map<string, SearchResultItem[]>();
    for (const item of items ?? []) {
      const list = g.get(item.scope) ?? [];
      list.push(item);
      g.set(item.scope, list);
    }
    return g;
  }, [items]);

  return (
    <div>
      <PageHeader title="本地搜索" description="全站全文检索：知识库 / 章节 / 提示词 / Agent / 素材（纯本地，无需外部搜索服务）">
        <form
          className="flex w-full max-w-xl items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const v = input.trim();
            if (v) navigate(`/search?q=${encodeURIComponent(v)}`);
          }}
        >
          <div className="relative flex-1">
            <SearchIcon
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入关键词，回车搜索…"
              className="h-10 w-full rounded-full border border-border-strong bg-surface py-0 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <button
            type="submit"
            className="h-10 rounded-full bg-primary px-5 text-sm font-semibold text-primary-foreground hover:bg-primary-hover"
          >
            搜索
          </button>
        </form>
      </PageHeader>

      <div className="space-y-4 p-4 md:p-6">
        {q && (
          <div className="flex flex-wrap items-center gap-1.5">
            {SCOPE_TABS.map((t) => (
              <button
                key={t.value}
                onClick={() => setScope(t.value)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs",
                  scope === t.value
                    ? "border-primary/40 bg-primary/10 font-medium text-primary"
                    : "border-border bg-surface text-muted-foreground hover:border-border-strong",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}

        {busy && <p className="text-sm text-muted-foreground">搜索中…</p>}
        {error && <p className="text-sm text-danger">{error}</p>}

        {!q && !busy && (
          <div className="rounded-2xl border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
            输入关键词搜索全部内容。支持：知识库文档、小说章节正文/大纲、提示词、Agent 设定、素材文件名。
          </div>
        )}

        {q && !busy && items && items.length === 0 && (
          <p className="text-sm text-muted-foreground">未找到与「{q}」相关的内容</p>
        )}

        {!busy && items && items.length > 0 && (
          <div className="space-y-5">
            {Array.from(grouped.entries()).map(([scopeName, list]) => (
              <section key={scopeName}>
                <h2 className="mb-2 text-sm font-semibold text-muted-foreground">
                  {SCOPE_TABS.find((t) => t.value === scopeName)?.label ?? scopeName}（{list.length}）
                </h2>
                <div className="space-y-2">
                  {list.map((item) => (
                    <button
                      key={`${item.scope}-${item.id}`}
                      onClick={() => navigate(resultTarget(item))}
                      className="flex w-full flex-col gap-1 rounded-2xl border border-border bg-surface p-3.5 text-left transition-colors hover:border-border-strong hover:bg-surface-raised"
                    >
                      <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                        {item.title}
                        {item.scope === "story" && item.meta?.chapter_no ? (
                          <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground">
                            第 {String(item.meta.chapter_no)} 章
                          </span>
                        ) : null}
                        {item.scope === "story" && item.meta?.project_title ? (
                          <span className="truncate text-xs text-muted-foreground">
                            {String(item.meta.project_title)}
                          </span>
                        ) : null}
                      </span>
                      <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                        {item.snippet}
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
