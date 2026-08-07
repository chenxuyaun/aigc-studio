import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Share2,
  Copy,
  ExternalLink,
  Heart,
  Pencil,
  Plus,
  Search,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  User as UserIcon,
} from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import type { Paginated, Prompt, PromptCategory } from "@aigc/shared-types";

import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { GallerySkeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { PageHeader } from "@/components/layout/PageHeader";
import { AppError, apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";
import { copyText } from "@/lib/clipboard";
import { applyTemplateValues, parseTemplateVariables } from "@/lib/promptTemplate";

const PAGE_SIZE = 24;

interface CategoriesResponse {
  items: PromptCategory[];
}
interface FavIds {
  ids: string[];
}

const PROMPT_TYPE_OPTS = [
  { v: "text", label: "文本" },
  { v: "image", label: "图片" },
  { v: "video", label: "视频" },
  { v: "audio", label: "音频" },
  { v: "code", label: "代码" },
  { v: "agent", label: "代理" },
  { v: "education", label: "教育" },
  { v: "other", label: "其他" },
];

function HeartButton({
  favorited,
  onToggle,
  className,
}: {
  favorited: boolean;
  onToggle: () => void;
  className?: string;
}) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      aria-pressed={favorited}
      aria-label={favorited ? "取消收藏" : "收藏"}
      className={cn(
        "inline-flex items-center justify-center rounded-lg border border-white/15 bg-black/55 p-1.5 text-white backdrop-blur transition-colors",
        className,
      )}
    >
      <Heart className={cn("h-4 w-4", favorited && "fill-danger text-danger")} aria-hidden />
    </button>
  );
}

function PromptCard({
  prompt,
  favorited,
  onOpen,
  onToggleFav,
  canManage,
  onEdit,
}: {
  prompt: Prompt;
  favorited: boolean;
  onOpen: (p: Prompt) => void;
  onToggleFav: (id: string) => void;
  canManage: boolean;
  onEdit: (p: Prompt) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [imgOk, setImgOk] = useState(true);
  const vars = useMemo(() => parseTemplateVariables(prompt.content), [prompt.content]);

  async function copy() {
    await copyText(prompt.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <figure className="group mb-3 break-inside-avoid overflow-hidden rounded-xl border border-border bg-surface-raised transition-colors hover:border-border-strong">
      <div className="relative">
        <button
          onClick={() => onOpen(prompt)}
          className="block w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`查看提示词：${prompt.title}`}
        >
          {prompt.cover_url && imgOk ? (
            <img
              src={prompt.cover_url}
              alt={prompt.title}
              loading="lazy"
              onError={() => setImgOk(false)}
              className="w-full bg-muted object-cover"
            />
          ) : (
            <div className="flex aspect-square items-center justify-center bg-muted text-xs text-muted-foreground">
              无预览图
            </div>
          )}
        </button>
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/65 via-transparent to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
        <HeartButton
          favorited={favorited}
          onToggle={() => onToggleFav(prompt.id)}
          className={cn(
            "absolute left-2 top-2 transition-opacity",
            favorited ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
          )}
        />
        {canManage && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onEdit(prompt);
            }}
            className="absolute left-2 bottom-2 inline-flex items-center justify-center rounded-lg border border-white/15 bg-black/55 p-1.5 text-white opacity-0 backdrop-blur transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
            aria-label="编辑"
          >
            <Pencil className="h-3.5 w-3.5" aria-hidden />
          </button>
        )}
        <button
          onClick={() => void copy()}
          className="absolute right-2 top-2 inline-flex items-center gap-1 rounded-lg border border-white/15 bg-black/55 px-2.5 py-1.5 text-xs font-medium text-white opacity-0 backdrop-blur transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          aria-label="复制提示词"
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "已复制" : "复制"}
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            void copyText(`${window.location.origin}/share/prompts/${prompt.id}`);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          className="absolute right-[86px] top-2 inline-flex items-center gap-1 rounded-lg border border-white/15 bg-black/55 px-2.5 py-1.5 text-xs font-medium text-white opacity-0 backdrop-blur transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
          aria-label="复制分享链接"
          title="复制公开分享链接（需提示词为公开）"
        >
          <Share2 className="h-3.5 w-3.5" aria-hidden />
          分享
        </button>
      </div>
      <button onClick={() => onOpen(prompt)} className="block w-full space-y-1 p-3 text-left">
        <p className="line-clamp-1 text-sm font-medium text-foreground">
          {prompt.title}
          {vars.length > 0 && (
            <span className="ml-1.5 inline-flex translate-y-[-1px] items-center rounded-md bg-primary/10 px-1.5 py-0.5 align-middle text-[10px] font-medium text-primary">
              变量 {vars.length}
            </span>
          )}
        </p>
        {prompt.source_author && (
          <p className="flex items-center gap-1 text-xs text-muted-foreground">
            <UserIcon className="h-3 w-3" aria-hidden />
            <span className="truncate">{prompt.source_author}</span>
          </p>
        )}
      </button>
    </figure>
  );
}

function PromptDetail({
  prompt,
  categoryName,
  favorited,
  canManage,
  onToggleFav,
  onEdit,
  onDelete,
  onClose,
}: {
  prompt: Prompt;
  categoryName: string;
  favorited: boolean;
  canManage: boolean;
  onToggleFav: (id: string) => void;
  onEdit: (p: Prompt) => void;
  onDelete: (p: Prompt) => void;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [copied, setCopied] = useState(false);

  const vars = useMemo(() => parseTemplateVariables(prompt.content), [prompt.content]);
  const [values, setValues] = useState<Record<string, string>>({});
  // 切换提示词时重置变量值为默认值
  useEffect(() => {
    const init: Record<string, string> = {};
    for (const v of vars) init[v.name] = v.defaultValue;
    setValues(init);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prompt.id]);
  const finalContent = useMemo(
    () => applyTemplateValues(prompt.content, values),
    [prompt.content, values],
  );

  async function copy() {
    await copyText(finalContent);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <Dialog open onClose={onClose} title={prompt.title}>
      <div className="space-y-4 p-5">
        {prompt.cover_url && (
          <img
            src={prompt.cover_url}
            alt={prompt.title}
            className="max-h-[46dvh] w-full rounded-xl border border-border object-contain"
          />
        )}
        {vars.length > 0 && (
          <div className="space-y-3 rounded-xl border border-primary/25 bg-primary/5 p-3">
            <p className="flex items-center gap-1.5 text-xs font-medium text-foreground">
              <SlidersHorizontal className="h-3.5 w-3.5 text-primary" aria-hidden />
              模板变量（{vars.length}）· 填好后「复制」或「用于创作」会带上你的填写
            </p>
            {vars.map((v) => (
              <label key={v.name} className="block">
                <span className="mb-1 block text-xs text-muted-foreground">{v.name}</span>
                <Input
                  value={values[v.name] ?? ""}
                  onChange={(e) =>
                    setValues((s) => ({ ...s, [v.name]: e.target.value }))
                  }
                  placeholder={v.defaultValue}
                />
              </label>
            ))}
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {categoryName && (
            <span className="rounded-full bg-secondary px-2.5 py-1 text-secondary-foreground">
              {categoryName}
            </span>
          )}
          {prompt.source_author && (
            <span className="flex items-center gap-1">
              <UserIcon className="h-3 w-3" aria-hidden />
              {prompt.source_author}
            </span>
          )}
          {prompt.source_url && (
            <a
              href={prompt.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 hover:text-foreground"
            >
              <ExternalLink className="h-3 w-3" aria-hidden />
              来源
            </a>
          )}
        </div>
        <div className="rounded-xl border border-border bg-surface p-3">
          <p className="whitespace-pre-wrap break-words font-mono-ui text-[13px] leading-relaxed text-foreground">
            {prompt.content}
          </p>
        </div>
      </div>
      <div className="sticky bottom-0 flex flex-wrap gap-2 border-t border-border bg-surface-raised p-4">
        <Button
          variant="outline"
          size="icon"
          onClick={() => onToggleFav(prompt.id)}
          aria-pressed={favorited}
          aria-label={favorited ? "取消收藏" : "收藏"}
        >
          <Heart className={cn("h-4 w-4", favorited && "fill-danger text-danger")} aria-hidden />
        </Button>
        <Button variant="outline" onClick={() => void copy()} className="flex-1">
          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
          {copied ? "已复制" : "复制"}
        </Button>
        {canManage && (
          <>
            <Button
              variant="outline"
              onClick={() => onEdit(prompt)}
            >
              <Pencil className="h-4 w-4" aria-hidden />
              编辑
            </Button>
            <Button
              variant="outline"
              className="text-danger hover:bg-danger/10"
              onClick={() => onDelete(prompt)}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
              删除
            </Button>
          </>
        )}
        <Button
          onClick={() => {
            const route =
              prompt.prompt_type === "text"
                ? "/create/text"
                : prompt.prompt_type === "video"
                  ? "/create/video"
                  : prompt.prompt_type === "audio"
                    ? "/create/audio"
                    : "/create/image";
            navigate(route, { state: { prompt: finalContent } });
          }}
          className="flex-1"
        >
          <Sparkles className="h-4 w-4" aria-hidden />
          用于创作
        </Button>
      </div>
    </Dialog>
  );
}

interface PromptFormState {
  title: string;
  content: string;
  prompt_type: string;
  category_id: string;
  is_public: boolean;
  tags: string;
}

const EMPTY_FORM: PromptFormState = {
  title: "",
  content: "",
  prompt_type: "text",
  category_id: "",
  is_public: true,
  tags: "",
};

function PromptEditor({
  prompt,
  categories,
  onClose,
}: {
  prompt: Prompt | null;
  categories: PromptCategory[];
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState<PromptFormState>(() =>
    prompt
      ? {
          title: prompt.title,
          content: prompt.content,
          prompt_type: prompt.prompt_type,
          category_id: prompt.category_id ?? "",
          is_public: prompt.is_public,
          tags: (prompt.tags ?? []).join(", "),
        }
      : EMPTY_FORM,
  );
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const tags = form.tags
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const body = {
        title: form.title.trim(),
        content: form.content.trim(),
        prompt_type: form.prompt_type,
        category_id: form.category_id || null,
        is_public: form.is_public,
        tags,
      };
      if (prompt) {
        return apiClient.put<Prompt>(`/prompts/${prompt.id}`, body);
      }
      return apiClient.post<Prompt>("/prompts/", body);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["prompts"] });
      void qc.invalidateQueries({ queryKey: ["prompts", "mine"] });
      void qc.invalidateQueries({ queryKey: ["prompts", "tags"] });
      onClose();
    },
    onError: (err) => {
      setError(err instanceof AppError ? err.message : "保存失败");
    },
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.title.trim() || !form.content.trim()) {
      setError("请填写标题和内容");
      return;
    }
    setError(null);
    mutation.mutate();
  }

  return (
    <Dialog open onClose={onClose} title={prompt ? "编辑提示词" : "新建提示词"}>
      <form onSubmit={handleSubmit} className="space-y-4 p-5">
        <Field label="标题" required>
          {({ id }) => (
            <Input
              id={id}
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="给提示词起个名字"
              required
            />
          )}
        </Field>
        <Field label="内容" required hint="提示词的具体内容，用于 AI 生成">
          {({ id }) => (
            <Textarea
              id={id}
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
              placeholder="输入提示词内容…"
              rows={6}
              required
            />
          )}
        </Field>
        <Field label="类型">
          {({ id, describedBy }) => (
            <Select
              id={id}
              aria-describedby={describedBy}
              value={form.prompt_type}
              onChange={(e) => setForm({ ...form, prompt_type: e.target.value })}
            >
              {PROMPT_TYPE_OPTS.map((o) => (
                <option key={o.v} value={o.v}>
                  {o.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="分类">
          {({ id, describedBy }) => (
            <Select
              id={id}
              aria-describedby={describedBy}
              value={form.category_id}
              onChange={(e) => setForm({ ...form, category_id: e.target.value })}
            >
              <option value="">未分类</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="标签" hint="逗号分隔，如：绘画, 写实">
          {({ id }) => (
            <Input
              id={id}
              value={form.tags}
              onChange={(e) => setForm({ ...form, tags: e.target.value })}
              placeholder="绘画, 写实, 提示词工程"
            />
          )}
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.is_public}
            onChange={(e) => setForm({ ...form, is_public: e.target.checked })}
            className="h-4 w-4 rounded border-input"
          />
          公开（其他用户可看到）
        </label>
        {error && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {error}
          </p>
        )}
        <div className="flex gap-2 pt-2">
          <Button type="button" variant="ghost" onClick={onClose} className="flex-1">
            取消
          </Button>
          <Button type="submit" loading={mutation.isPending} className="flex-1">
            {prompt ? "保存" : "创建"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function PromptsPage() {
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  const initialQ = searchParams.get("q") || searchParams.get("search") || "";
  const [category, setCategory] = useState("");
  const [tag, setTag] = useState("");
  const [searchInput, setSearchInput] = useState(initialQ);
  const [search, setSearch] = useState(initialQ);
  const [favMode, setFavMode] = useState(false);
  const [selected, setSelected] = useState<Prompt | null>(null);
  const [editing, setEditing] = useState<Prompt | null>(null);
  const [creating, setCreating] = useState(false);
  const [toDelete, setToDelete] = useState<Prompt | null>(null);

  // 顶部搜索框（AppShell）跳转带 ?q= 时同步查询（已在 /prompts 页时重复搜索也能生效）
  useEffect(() => {
    if (initialQ) {
      setSearchInput(initialQ);
      setSearch(initialQ);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const categoriesQuery = useQuery({
    queryKey: ["prompts", "categories"],
    queryFn: () => apiClient.get<CategoriesResponse>("/prompts/categories"),
    staleTime: 5 * 60_000,
  });

  const tagsQuery = useQuery({
    queryKey: ["prompts", "tags"],
    queryFn: () => apiClient.get<Array<{ name: string; count: number }>>("/prompts/tags"),
    staleTime: 30_000,
  });

  const favIdsQuery = useQuery({
    queryKey: ["prompts", "fav-ids"],
    queryFn: () => apiClient.get<FavIds>("/prompts/mine/favorite-ids"),
  });
  const favSet = useMemo(() => new Set(favIdsQuery.data?.ids ?? []), [favIdsQuery.data]);

  const favMutation = useMutation({
    mutationFn: (id: string) => apiClient.post(`/prompts/${id}/favorite`),
    onMutate: async (id: string) => {
      await qc.cancelQueries({ queryKey: ["prompts", "fav-ids"] });
      const prev = qc.getQueryData<FavIds>(["prompts", "fav-ids"]);
      qc.setQueryData<FavIds>(["prompts", "fav-ids"], (old) => {
        const ids = old?.ids ?? [];
        return { ids: ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id] };
      });
      return { prev };
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(["prompts", "fav-ids"], ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["prompts", "fav-ids"] });
      if (favMode) void qc.invalidateQueries({ queryKey: ["prompts", "favlist"] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.del(`/prompts/${id}`),
    onSuccess: () => {
      setToDelete(null);
      setSelected(null);
      void qc.invalidateQueries({ queryKey: ["prompts"] });
      void qc.invalidateQueries({ queryKey: ["prompts", "mine"] });
    },
  });

  const listQuery = useInfiniteQuery({
    queryKey: favMode ? ["prompts", "favlist"] : ["prompts", "list", { category, tag, search }],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ page: String(pageParam), page_size: String(PAGE_SIZE) });
      if (favMode) return apiClient.get<Paginated<Prompt>>(`/prompts/mine/favorites?${params}`);
      if (category) params.set("category_id", category);
      if (tag) params.set("tag", tag);
      if (search) params.set("search", search);
      return apiClient.get<Paginated<Prompt>>(`/prompts/?${params.toString()}`);
    },
    getNextPageParam: (last) => (last.page < last.pages ? last.page + 1 : undefined),
  });

  const sentinelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && listQuery.hasNextPage && !listQuery.isFetchingNextPage) {
          void listQuery.fetchNextPage();
        }
      },
      { rootMargin: "600px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [listQuery.hasNextPage, listQuery.isFetchingNextPage, listQuery]);

  const items = listQuery.data?.pages.flatMap((p) => p.items) ?? [];
  const total = listQuery.data?.pages[0]?.total ?? 0;
  const categories = categoriesQuery.data?.items ?? [];
  const catNames = useMemo(
    () => new Map((categoriesQuery.data?.items ?? []).map((c) => [c.id, c.name])),
    [categoriesQuery.data],
  );

  function toggleFav(id: string) {
    favMutation.mutate(id);
  }

  return (
    <div>
      <PageHeader
        title="提示词库"
        description={
          favMode
            ? "我收藏的提示词"
            : total > 0
              ? `共 ${total} 条精选提示词，点击卡片查看`
              : "精选 AI 绘画提示词"
        }
        actions={
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            新建提示词
          </Button>
        }
      >
        {!favMode && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setSearch(searchInput.trim());
            }}
            className="relative max-w-md"
          >
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="搜索提示词标题…"
              className="pl-9"
              aria-label="搜索提示词"
            />
          </form>
        )}
        <div className="flex flex-nowrap gap-2 overflow-x-auto">
          <Chip active={favMode} accent onClick={() => setFavMode((v) => !v)}>
            <Heart className={cn("mr-1 inline h-3.5 w-3.5", favMode && "fill-current")} aria-hidden />
            收藏
          </Chip>
          <Chip active={!favMode && category === ""} onClick={() => { setFavMode(false); setCategory(""); }}>
            全部
          </Chip>
          {categories.map((c) => (
            <Chip
              key={c.id}
              active={!favMode && category === c.id}
              onClick={() => { setFavMode(false); setCategory(c.id); }}
            >
              {c.name}
            </Chip>
          ))}
          <span className="mx-1 h-4 w-px self-center bg-border" aria-hidden />
          {(tagsQuery.data ?? []).map((t) => (
            <Chip
              key={t.name}
              active={!favMode && category === "" && tag === t.name}
              onClick={() => {
                setFavMode(false);
                setCategory("");
                setTag(tag === t.name ? "" : t.name);
              }}
            >
              #{t.name}
              <span className="ml-1 text-[10px] opacity-70">{t.count}</span>
            </Chip>
          ))}
        </div>
      </PageHeader>
      <div className="space-y-4 p-4 md:p-6">
        {listQuery.isPending ? (
          <GallerySkeleton />
        ) : listQuery.isError ? (
          <ErrorState error={listQuery.error} onRetry={() => void listQuery.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            title={favMode ? "还没有收藏" : "没有匹配的提示词"}
            description={favMode ? "在画廊里点 ♥ 收藏喜欢的提示词，这里就能找到。" : "换个分类或搜索关键词试试。"}
            action={
              !favMode && (
                <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
                  <Plus className="h-4 w-4" aria-hidden />
                  新建提示词
                </Button>
              )
            }
          />
        ) : (
          <>
            <div className="columns-2 gap-3 sm:columns-3 lg:columns-4 xl:columns-5">
              {items.map((p) => (
                <PromptCard
                  key={p.id}
                  prompt={p}
                  favorited={favSet.has(p.id)}
                  onOpen={setSelected}
                  onToggleFav={toggleFav}
                  canManage={!favMode}
                  onEdit={setEditing}
                />
              ))}
            </div>
            {listQuery.hasNextPage && (
              <div ref={sentinelRef} className="flex justify-center py-6">
                {listQuery.isFetchingNextPage ? (
                  <GallerySkeleton />
                ) : (
                  <span className="text-xs text-muted-foreground">滚动加载更多…</span>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {selected && (
        <PromptDetail
          prompt={selected}
          categoryName={selected.category_id ? (catNames.get(selected.category_id) ?? "") : ""}
          favorited={favSet.has(selected.id)}
          canManage={!favMode}
          onToggleFav={toggleFav}
          onEdit={(p) => {
            setSelected(null);
            setEditing(p);
          }}
          onDelete={(p) => {
            setSelected(null);
            setToDelete(p);
          }}
          onClose={() => setSelected(null)}
        />
      )}

      {(editing || creating) && (
        <PromptEditor
          prompt={editing}
          categories={categories}
          onClose={() => {
            setEditing(null);
            setCreating(false);
          }}
        />
      )}

      <ConfirmDialog
        open={toDelete !== null}
        title="删除提示词"
        description={`将删除「${toDelete?.title ?? ""}」，此操作不可恢复。`}
        confirmText="删除"
        loading={deleteMutation.isPending}
        onConfirm={() => toDelete && deleteMutation.mutate(toDelete.id)}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}

function Chip({
  active,
  accent = false,
  onClick,
  children,
}: {
  active: boolean;
  accent?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "inline-flex shrink-0 items-center whitespace-nowrap rounded-full border px-3 py-1.5 text-sm transition-colors",
        active
          ? accent
            ? "border-danger bg-danger/10 text-danger"
            : "border-primary bg-primary text-primary-foreground"
          : "border-border bg-surface text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
