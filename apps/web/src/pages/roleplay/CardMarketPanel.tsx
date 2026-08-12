import { useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";

interface MarketCard {
  slug: string;
  name: string;
  author: string;
  category: string;
  tags: string[];
  download_count: number;
  avg_rating: number;
  summary: string;
}

/** 卡库（xstavern 公开索引）：搜索/分类筛选/浏览/直链。 */
export function CardMarketPanel() {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [sort, setSort] = useState("popular");
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 24;

  const listQ = useQuery({
    queryKey: ["cardmarket", q, cat, sort, page],
    queryFn: () => {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
        sort,
      });
      if (q) params.set("q", q);
      if (cat) params.set("category", cat);
      return apiClient.get<{ total: number; items: MarketCard[] }>(`/cardmarket?${params}`);
    },
  });
  const catsQ = useQuery({
    queryKey: ["cardmarket", "categories"],
    queryFn: () => apiClient.get<{ categories: { name: string; count: number }[] }>("/cardmarket/categories"),
    staleTime: 10 * 60_000,
  });

  const items = listQ.data?.items ?? [];
  const total = listQ.data?.total ?? 0;

  // 切换筛选时回到第一页
  const reset = () => setPage(1);
  const onSearch = (v: string) => {
    setQ(v);
    reset();
  };
  const onCat = (c: string) => {
    setCat(c);
    reset();
  };
  const onSort = (s: string) => {
    setSort(s);
    reset();
  };

  const preview = (slug: string) => `/api/v1/cardmarket/preview/${slug}`;
  const link = (slug: string) =>
    `https://chat.xstavern.com/api/marketplace.php?action=download&format=json&slug=${slug}`;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <input
          value={q}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="搜索卡名 / 作者 / 标签…"
          className="min-w-0 flex-1 rounded-lg border border-border bg-muted/40 px-2.5 py-1.5 text-xs outline-none focus:border-primary"
        />
        <select
          value={sort}
          onChange={(e) => onSort(e.target.value)}
          className="rounded-lg border border-border bg-muted/40 px-2 py-1.5 text-xs outline-none"
        >
          <option value="popular">热门</option>
          <option value="rating">评分</option>
          <option value="newest">最新</option>
          <option value="name">名称</option>
        </select>
      </div>

      <div className="flex flex-wrap gap-1">
        <button
          onClick={() => onCat("")}
          className={cn(
            "rounded-full border px-2 py-0.5 text-[10px]",
            !cat ? "border-primary bg-primary/10 text-primary-text" : "border-border text-muted-foreground",
          )}
        >
          全部
        </button>
        {(catsQ.data?.categories ?? []).slice(0, 12).map((c) => (
          <button
            key={c.name}
            onClick={() => onCat(c.name)}
            className={cn(
              "rounded-full border px-2 py-0.5 text-[10px]",
              cat === c.name
                ? "border-primary bg-primary/10 text-primary-text"
                : "border-border text-muted-foreground hover:border-primary",
            )}
          >
            {c.name.split("/").pop()}·{c.count}
          </button>
        ))}
      </div>

      <p className="text-[10px] text-muted-foreground">
        共 {total} 张卡（外部公开索引，浏览可参考；下载需前往来源站）
      </p>

      <div className="grid grid-cols-2 gap-2">
        {items.map((c) => (
          <div key={c.slug} className="overflow-hidden rounded-xl border border-border bg-muted/30">
            <div
              className="aspect-[4/3] bg-muted/50 bg-cover bg-center"
              style={{ backgroundImage: `url('${preview(c.slug)}')` }}
            />
            <div className="flex flex-col gap-1 p-2">
              <span className="truncate text-[11px] font-medium" title={c.name}>
                {c.name}
              </span>
              <span className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                <span className="truncate">👤 {c.author || "匿名"}</span>
                <span>⬇ {c.download_count}</span>
                {c.avg_rating > 0 && <span>⭐ {c.avg_rating}</span>}
              </span>
              <span className="line-clamp-2 text-[10px] leading-relaxed text-muted-foreground">
                {c.summary || "暂无简介"}
              </span>
              <a
                href={link(c.slug)}
                target="_blank"
                rel="noreferrer"
                className="mt-1 text-right text-[10px] text-primary-text hover:underline"
              >
                来源直链 ↗
              </a>
            </div>
          </div>
        ))}
      </div>

      {listQ.isFetching && <p className="text-center text-[10px] text-muted-foreground">加载中…</p>}
      {total > page * PAGE_SIZE && (
        <button
          onClick={() => setPage((p) => p + 1)}
          className="rounded-full border border-border px-4 py-1.5 text-[11px] hover:border-primary"
        >
          加载更多（{Math.min(total - page * PAGE_SIZE, PAGE_SIZE)}）
        </button>
      )}
    </div>
  );
}
