/**
 * 社区分享墙（批11）：登录用户发布作品（文字/图片），互相浏览与点赞。
 * 不开放匿名注册——所有操作需登录。
 */

import { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";

interface Post {
  id: string;
  author_name: string;
  title: string;
  content: string;
  kind: string;
  image_url: string;
  likes: number;
  liked_by_me: boolean;
  mine: boolean;
  created_at: string | null;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

export default function CommunityPage() {
  const [posts, setPosts] = useState<Post[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // 发布表单
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async (p: number) => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiClient.get<{ items: Post[]; total: number }>(
        `/community/posts?page=${p}&page_size=12`,
      );
      setPosts((prev) => (p === 1 ? r.items : [...prev, ...r.items]));
      setTotal(r.total);
      setPage(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(1);
  }, [load]);

  async function publish() {
    if (!title.trim()) return;
    setPublishing(true);
    setNotice(null);
    try {
      await apiClient.post("/community/posts", {
        title: title.trim(),
        content: content.trim(),
        kind: imageUrl.trim() ? "image" : "text",
        image_url: imageUrl.trim(),
      });
      setTitle("");
      setContent("");
      setImageUrl("");
      setNotice("✓ 已发布到分享墙");
      setTimeout(() => setNotice(null), 2000);
      await load(1);
    } catch (e) {
      setError(e instanceof Error ? e.message : "发布失败");
    } finally {
      setPublishing(false);
    }
  }

  async function toggleLike(p: Post) {
    // 乐观更新
    setPosts((prev) =>
      prev.map((x) =>
        x.id === p.id
          ? { ...x, likes: x.likes + (x.liked_by_me ? -1 : 1), liked_by_me: !x.liked_by_me }
          : x,
      ),
    );
    try {
      await apiClient.post(`/community/posts/${p.id}/like`);
    } catch {
      void load(page); // 失败回滚
    }
  }

  async function remove(p: Post) {
    try {
      await apiClient.del(`/community/posts/${p.id}`);
      setPosts((prev) => prev.filter((x) => x.id !== p.id));
      setTotal((t) => Math.max(0, t - 1));
    } catch {
      /* 删除失败静默 */
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6">
      <header>
        <h1 className="text-xl font-semibold text-foreground">分享墙</h1>
        <p className="mt-1 text-xs text-muted-foreground">
          展示你的创作成果，看看其他创作者在做什么。共 {total} 个分享。
        </p>
      </header>

      {/* 发布表单 */}
      <section className="ai-glass rounded-2xl p-4">
        <h2 className="text-sm font-medium text-foreground">分享我的作品</h2>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="标题（必填）"
          maxLength={120}
          className="ai-glass-input mt-2 w-full rounded-lg px-3 py-2 text-sm text-foreground outline-none"
        />
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={3}
          placeholder="介绍一下这个作品…"
          maxLength={4000}
          className="ai-glass-input mt-2 w-full resize-y rounded-lg px-3 py-2 text-sm text-foreground outline-none"
        />
        <input
          value={imageUrl}
          onChange={(e) => setImageUrl(e.target.value)}
          placeholder="图片链接（可选，填了就以图片帖展示）"
          maxLength={500}
          className="ai-glass-input mt-2 w-full rounded-lg px-3 py-2 text-xs text-foreground outline-none"
        />
        <div className="mt-2 flex items-center gap-3">
          <button
            type="button"
            onClick={() => void publish()}
            disabled={publishing || !title.trim()}
            className="rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {publishing ? "发布中…" : "🚀 发布到分享墙"}
          </button>
          {notice && <span className="text-xs text-emerald-300">{notice}</span>}
          {error && <span className="text-xs text-rose-300">{error}</span>}
        </div>
      </section>

      {/* 墙 */}
      {!error && posts.length === 0 && !loading && (
        <p className="text-center text-xs text-muted-foreground">
          还没有人分享。发第一帖，让大家看到你的作品！
        </p>
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {posts.map((p) => (
          <article
            key={p.id}
            className="ai-glass flex flex-col overflow-hidden rounded-2xl transition-transform hover:-translate-y-0.5"
          >
            {p.kind === "image" && p.image_url && (
              <img
                src={p.image_url}
                alt={p.title}
                className="h-40 w-full object-cover"
                loading="lazy"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = "none";
                }}
              />
            )}
            <div className="flex flex-1 flex-col p-4">
              <h3 className="text-sm font-medium leading-snug text-foreground">{p.title}</h3>
              {p.content && (
                <p className="mt-1.5 line-clamp-4 flex-1 whitespace-pre-wrap text-xs leading-relaxed text-foreground/80">
                  {p.content}
                </p>
              )}
              <div className="mt-3 flex items-center justify-between border-t border-white/5 pt-2.5">
                <div className="text-[11px] text-muted-foreground">
                  👤 {p.author_name} · {fmtDate(p.created_at)}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void toggleLike(p)}
                    className={cn(
                      "rounded-full px-2.5 py-1 text-[11px] transition-colors",
                      p.liked_by_me
                        ? "bg-rose-500/20 text-rose-300"
                        : "bg-white/5 text-muted-foreground hover:text-rose-300",
                    )}
                  >
                    ❤️ {p.likes}
                  </button>
                  {p.mine && (
                    <button
                      type="button"
                      onClick={() => void remove(p)}
                      title="删除这条分享"
                      className="text-[11px] text-muted-foreground hover:text-rose-300"
                    >
                      🗑
                    </button>
                  )}
                </div>
              </div>
            </div>
          </article>
        ))}
      </div>
      {posts.length < total && (
        <button
          type="button"
          onClick={() => void load(page + 1)}
          disabled={loading}
          className="ai-glass-input mx-auto rounded-lg px-4 py-1.5 text-xs text-foreground/80 hover:text-foreground disabled:opacity-50"
        >
          {loading ? "加载中…" : "加载更多"}
        </button>
      )}
    </div>
  );
}
