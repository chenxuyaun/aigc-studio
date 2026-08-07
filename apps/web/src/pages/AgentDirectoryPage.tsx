import { useCallback, useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input } from "@/components/ui/Field";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { apiClient } from "@/lib/apiClient";

interface AgentProjectItem {
  id: string;
  name: string;
  url: string;
  github_url: string;
  homepage_url: string;
  description: string;
  categories: string[];
  tags: string[];
  stars: number;
  language: string;
  license: string;
}

interface AgentArticleItem {
  id: string;
  title: string;
  url: string;
  description: string;
  categories: string[];
  related_projects: string[];
  content?: string;
}

interface AgentComparisonItem {
  id: string;
  title: string;
  url: string;
  description: string;
  categories: string[];
  projects: string[];
  content?: string;
}

interface Stats {
  counts: { projects: number; articles: number; comparisons: number };
  top_categories: [string, number][];
}

type Tab = "projects" | "articles" | "comparisons";
type DetailItem = AgentProjectItem | AgentArticleItem | AgentComparisonItem;

const isComparison = (d: DetailItem): d is AgentComparisonItem => "projects" in d;
const isArticle = (d: DetailItem): d is AgentArticleItem => "related_projects" in d;
const isProject = (d: DetailItem): d is AgentProjectItem => "github_url" in d;


/** AgentList 外部目录：开源 AI Agent 项目检索（搜索/分类/排序/详情）。 */
export function AgentDirectoryPage() {
  const toast = useToast();
  const [stats, setStats] = useState<Stats | null>(null);
  const [tab, setTab] = useState<Tab>("projects");
  const [items, setItems] = useState<(AgentProjectItem | AgentArticleItem | AgentComparisonItem)[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState("stars");
  const [limit] = useState(30);
  const [detail, setDetail] = useState<DetailItem | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const loadStats = useCallback(async () => {
    try {
      const r = await apiClient.get<Stats>("/agentlist/stats");
      setStats(r);
    } catch {
      setStats(null);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ limit: String(limit), sort });
      if (search.trim()) params.set("search", search.trim());
      if (category) params.set("category", category);
      const path =
        tab === "projects"
          ? "/agentlist/projects"
          : tab === "articles"
            ? "/agentlist/articles"
            : "/agentlist/comparisons";
      const r = await apiClient.get<{ items: typeof items; total: number }>(`${path}?${params}`);
      setItems(r.items);
      setTotal(r.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [tab, search, category, sort, limit]);

  useEffect(() => {
    void loadStats();
  }, [loadStats]);

  useEffect(() => {
    void load();
  }, [load]);

  const openDetail = async (item: DetailItem) => {
    const base = tab === "projects" ? "/agentlist/projects" : tab === "articles" ? "/agentlist/articles" : "/agentlist/comparisons";
    try {
      const r = await apiClient.get<{ project?: AgentProjectItem; article?: AgentArticleItem; comparison?: AgentComparisonItem }>(
        `${base}/${item.id}`,
      );
      setDetail(r.project ?? r.article ?? r.comparison ?? item);
      setExpanded(false);
    } catch {
      setDetail(item);
    }
  };

  const sync = async () => {
    setSyncing(true);
    try {
      const r = await apiClient.post<{ ok: boolean; projects: number; articles: number; comparisons: number }>("/agentlist/sync");
      toast.success(`同步完成：${r.projects} 项目 / ${r.articles} 文章 / ${r.comparisons} 对比表`);
      void loadStats();
      void load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "同步失败");
    } finally {
      setSyncing(false);
    }
  };

  const catOptions = useMemo(() => stats?.top_categories ?? [], [stats]);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-4">
      <PageHeader
        title="Agent 项目目录"
        description="开源 AI Agent 项目精选目录（AgentList 全量数据）"
        actions={
          <Button onClick={sync} disabled={syncing}>
            {syncing ? "同步中…" : "重新同步"}
          </Button>
        }
      />

      {stats && (
        <div className="grid grid-cols-3 gap-3">
          {[
            ["项目", stats.counts.projects],
            ["长文", stats.counts.articles],
            ["对比表", stats.counts.comparisons],
          ].map(([label, n]) => (
            <div key={String(label)} className="rounded-lg border bg-card p-4 text-center">
              <div className="text-2xl font-semibold">{n}</div>
              <div className="text-sm text-muted-foreground">{label}</div>
            </div>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-52 flex-1">
          <Field label="搜索">
            {({ id }) => (
              <Input
                id={id}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={tab === "projects" ? "名称 / 描述 / 标签" : "标题 / 描述"}
              />
            )}
          </Field>
        </div>
        {tab === "projects" && (
          <>
            <div className="min-w-44">
              <Field label="分类">
                {({ id }) => (
                  <select
                    id={id}
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                  >
                    <option value="">全部分类</option>
                    {catOptions.map(([c, n]) => (
                      <option key={c} value={c}>
                        {c} ({n})
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            </div>
            <div className="min-w-36">
              <Field label="排序">
                {({ id }) => (
                  <select
                    id={id}
                    className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                    value={sort}
                    onChange={(e) => setSort(e.target.value)}
                  >
                    <option value="stars">星数</option>
                    <option value="name">名称</option>
                  </select>
                )}
              </Field>
            </div>
          </>
        )}
        <Button variant="outline" onClick={load} disabled={loading}>
          查询
        </Button>
      </div>

      <div className="flex gap-1 border-b">
        {(
          [
            ["projects", "项目"],
            ["articles", "长文"],
            ["comparisons", "对比表"],
          ] as [Tab, string][]
        ).map(([t, label]) => (
          <button
            key={t}
            className={`-mb-px border-b-2 px-4 py-2 text-sm ${tab === t ? "border-primary font-medium" : "border-transparent text-muted-foreground"}`}
            onClick={() => {
              setTab(t);
              setCategory("");
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <LoadingState label="加载中…" />
      ) : error ? (
        <ErrorState error={error} />
      ) : items.length === 0 ? (
        <EmptyState title="没有匹配的条目" />
      ) : (
        <div className="flex flex-col gap-2">
          <div className="text-sm text-muted-foreground">
            共 {total} 条
          </div>
          {items.map((it) => {
            if (tab === "projects") {
              const p = it as AgentProjectItem;
              return (
                <button
                  key={p.id}
                  onClick={() => openDetail(p)}
                  className="flex items-start justify-between gap-4 rounded-lg border bg-card p-4 text-left hover:border-primary/50"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium">{p.name}</span>
                      {p.language && (
                        <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                          {p.language}
                        </span>
                      )}
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{p.description}</p>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {p.categories.map((c) => (
                        <span key={c} className="rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary-text">
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="shrink-0 text-right text-sm">
                    <div className="font-medium">{p.stars.toLocaleString()} ★</div>
                    {p.license && <div className="text-xs text-muted-foreground">{p.license}</div>}
                  </div>
                </button>
              );
            }
            const a = it as AgentArticleItem;
            return (
              <button
                key={it.id}
                onClick={() => openDetail(it)}
                className="rounded-lg border bg-card p-4 text-left hover:border-primary/50"
              >
                <div className="font-medium">
                  {tab === "articles" ? a.title : (it as AgentComparisonItem).title}
                </div>
                <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{it.description}</p>
                {tab === "comparisons" && (it as AgentComparisonItem).projects.length > 0 && (
                  <div className="mt-2 text-xs text-muted-foreground">
                    {(it as AgentComparisonItem).projects.join(" / ")}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      )}

      <Dialog open={detail !== null} onClose={() => setDetail(null)} title={detail ? (isProject(detail) ? detail.name : (isArticle(detail) || isComparison(detail) ? detail.title : "")) : ""}>
        {detail && (
          <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto">
            <p className="text-sm text-muted-foreground">{detail.description}</p>
            {isProject(detail) && detail.tags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {detail.tags.map((t) => (
                  <span key={t} className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                    #{t}
                  </span>
                ))}
              </div>
            )}
            {isComparison(detail) && detail.projects.length > 0 && (
              <div className="text-sm">
                对比对象：{detail.projects.join(" / ")}
              </div>
            )}
            {isArticle(detail) && detail.related_projects.length > 0 && (
              <div className="text-sm">
                相关项目：
                <div className="mt-1 flex flex-wrap gap-1">
                  {detail.related_projects.map((t) => (
                    <span key={t} className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {"content" in detail && detail.content && (
              <>
                <pre className="whitespace-pre-wrap rounded-md bg-muted/50 p-3 text-xs leading-relaxed">
                  {expanded ? detail.content : detail.content.slice(0, 6000)}
                  {!expanded && detail.content.length > 6000 && " …"}
                </pre>
                {detail.content.length > 6000 && (
                  <button
                    className="text-sm text-primary-text underline"
                    onClick={() => setExpanded((v) => !v)}
                  >
                    {expanded ? "收起" : `展开全文（${detail.content.length} 字符）`}
                  </button>
                )}
              </>
            )}
            <div className="flex flex-wrap gap-2">
              {detail.url && (
                <a className="text-sm text-primary-text underline" href={detail.url} target="_blank" rel="noreferrer">
                  原站链接
                </a>
              )}
              {isProject(detail) && detail.github_url && (
                <a
                  className="text-sm text-primary-text underline"
                  href={detail.github_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  GitHub
                </a>
              )}
              {isProject(detail) && detail.homepage_url && (
                <a
                  className="text-sm text-primary-text underline"
                  href={detail.homepage_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  官网
                </a>
              )}
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
