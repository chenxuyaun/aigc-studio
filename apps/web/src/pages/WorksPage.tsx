import { useEffect, useState } from "react";

import { BookOpen, FolderOpen, MessageCircle, Music, Users } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { Dialog } from "@/components/ui/Dialog";
import { apiClient } from "@/lib/apiClient";
import { copyShareUrl } from "@/lib/share";
import type { ChatSession } from "@/pages/roleplay/types";

interface StoryProjectItem {
  id: string;
  title: string;
  genre: string;
  status: string;
  updated_at: string;
}

interface CharacterItem {
  asset_id: string;
  name?: string;
  filename: string;
}

interface MusicWorkItem {
  id: string;
  title: string;
  theme: string;
  style: string;
  lyrics: string;
  chords: string;
  arrangement: string;
  style_en: string;
  source: string;
  tags: string;
  created_at: string;
}

function fmtTime(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function WorksPage() {
  const navigate = useNavigate();
  const [rooms, setRooms] = useState<ChatSession[]>([]);
  const [works, setWorks] = useState<StoryProjectItem[]>([]);
  const [chars, setChars] = useState<CharacterItem[]>([]);
  const [musicWorks, setMusicWorks] = useState<MusicWorkItem[]>([]);
  const [loading, setLoading] = useState(true);
  // 音乐作品对比：勾选 2 首并排展示
  const [compareIds, setCompareIds] = useState<string[]>([]);
  // 作品搜索 + 发布到群的群选择
  const [workQuery, setWorkQuery] = useState("");
  const [activeTag, setActiveTag] = useState(""); // 按标签浏览
  const [publishFor, setPublishFor] = useState(""); // 正在发布的作品 id
  const [detailWork, setDetailWork] = useState<MusicWorkItem | null>(null); // 作品详情弹窗

  const loadMusicWorks = async (q = workQuery, tag = activeTag) => {
    try {
      const res = await apiClient.get<{ items: MusicWorkItem[] }>(
        `/generations/music/works?q=${encodeURIComponent(q)}&tag=${encodeURIComponent(tag)}`,
      );
      setMusicWorks(res.items);
    } catch {
      /* 忽略 */
    }
  };

  // 标签聚合：从当前作品列表提取去重（点击即按标签过滤）
  const allTags = Array.from(
    new Set(
      musicWorks
        .flatMap((w) => (w.tags || "").split(",").map((t) => t.trim()))
        .filter(Boolean),
    ),
  ).slice(0, 12);

  const toggleTag = (tag: string) => {
    const next = activeTag === tag ? "" : tag;
    setActiveTag(next);
    void loadMusicWorks(workQuery, next);
  };

  useEffect(() => {
    void (async () => {
      try {
        const [r1, r2, r3, r4] = await Promise.all([
          apiClient.get<{ items: ChatSession[] }>("/roleplay/chats"),
          apiClient.get<{ items: StoryProjectItem[] }>("/story/projects"),
          apiClient.get<{ items: CharacterItem[] }>("/roleplay/characters"),
          apiClient.get<{ items: MusicWorkItem[] }>("/generations/music/works"),
        ]);
        setRooms(r1.items.filter((c) => c.is_room));
        setWorks(r2.items);
        setChars(r3.items);
        setMusicWorks(r4.items);
      } catch {
        /* 加载失败保持空态 */
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const playWorks = works.filter((w) => w.genre === "群演剧本");
  const compareWorks = musicWorks.filter((w) => compareIds.includes(w.id));
  // 版本标注：同主题的第 N 稿
  const workVersions = new Map<string, number>();
  for (const w of musicWorks) {
    const key = w.theme || w.title;
    workVersions.set(key, (workVersions.get(key) ?? 0) + 1);
  }
  const workVersionOf = (w: MusicWorkItem): number => {
    const key = w.theme || w.title;
    const total = workVersions.get(key) ?? 1;
    return total; // 列表倒序：第一项是最新稿
  };

  async function deleteMusicWork(id: string) {
    try {
      await apiClient.del(`/generations/music/works/${id}`);
      setMusicWorks((prev) => prev.filter((w) => w.id !== id));
      setCompareIds((prev) => prev.filter((x) => x !== id));
    } catch {
      /* 忽略 */
    }
  }

  async function publishToChat(workId: string, chatId: string) {
    try {
      const res = await apiClient.post<{ ok: boolean; title: string }>(
        `/generations/music/works/${workId}/to-chat`,
        { chat_id: chatId },
      );
      alert(`《${res.title}》已发布到群聊`);
      setPublishFor("");
    } catch (e) {
      alert(e instanceof Error ? e.message : "发布失败");
    }
  }

  return (
    <div>
      <PageHeader
        title="我的创作"
        description="群演作品、创作群、角色演员池——你的创作资产一览"
      />
      <div className="grid gap-4 p-4 md:p-6 lg:grid-cols-2">
        {/* 音乐作品（圆桌/写歌定稿，自动存入） */}
        <section className="rounded-[var(--radius-card)] border border-border bg-surface p-4 lg:col-span-2">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <Music className="h-4 w-4 text-primary-text" aria-hidden />
              音乐作品（{musicWorks.length}）——圆桌/写歌定稿自动存入
            </h2>
            <input
              value={workQuery}
              onChange={(e) => {
                setWorkQuery(e.target.value);
                void loadMusicWorks(e.target.value);
              }}
              placeholder="搜索歌名/主题/风格…"
              className="ml-auto h-8 w-48 rounded-lg border border-input bg-surface px-3 text-xs outline-none focus:border-primary"
              aria-label="搜索音乐作品"
            />
          </div>
          {allTags.length > 0 && (
            <div className="mb-3 flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-muted-foreground">🏷 按标签浏览：</span>
              {allTags.map((t) => (
                <button
                  key={t}
                  onClick={() => toggleTag(t)}
                  className={`rounded-full px-2.5 py-0.5 text-[11px] transition-colors ${
                    activeTag === t
                      ? "bg-primary text-primary-text"
                      : "bg-muted text-muted-foreground hover:bg-primary/15"
                  }`}
                >
                  {t}
                </button>
              ))}
              {activeTag && (
                <button
                  onClick={() => toggleTag(activeTag)}
                  className="text-[11px] text-destructive hover:underline"
                >
                  ✕ 清除筛选
                </button>
              )}
            </div>
          )}
          {loading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">加载中…</p>
          ) : musicWorks.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              还没有作品。去「音乐创作助手」开一场圆桌，定稿会自动存到这里
            </p>
          ) : (
            <>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {musicWorks.slice(0, 9).map((w) => (
                  <div
                    key={w.id}
                    className="flex flex-col gap-1.5 rounded-lg border border-border p-3"
                  >
                    <div className="flex items-center gap-2">
                      <button type="button" className="truncate font-medium hover:text-primary-text" onClick={() => setDetailWork(w)} title="查看详情">{w.title}</button>
                      {w.style && (
                        <span className="shrink-0 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary-text">
                          {w.style}
                        </span>
                      )}
                      {workVersionOf(w) > 1 && (
                        <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                          第 {workVersionOf(w)} 稿
                        </span>
                      )}
                    </div>
                    {w.tags && (
                      <div className="flex flex-wrap gap-1">
                        {w.tags
                          .split(",")
                          .map((t) => t.trim())
                          .filter(Boolean)
                          .slice(0, 4)
                          .map((t) => (
                            <span
                              key={t}
                              className="rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground"
                            >
                              {t}
                            </span>
                          ))}
                      </div>
                    )}
                    <div className="flex items-center gap-2">
                    <label className="ml-auto flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
                      <input
                        type="checkbox"
                        checked={compareIds.includes(w.id)}
                          onChange={(e) => {
                            const checked = e.target.checked;
                            setCompareIds((prev) => {
                              if (!checked) return prev.filter((x) => x !== w.id);
                              if (prev.length >= 2) {
                                const keep = (prev[1] ?? prev[0]) ?? "";
                                return [keep, w.id];
                              }
                              return [...prev, w.id];
                            });
                          }}
                          className="h-3 w-3 accent-[var(--primary)]"
                        />
                        对比
                      </label>
                    </div>
                    <p className="line-clamp-3 whitespace-pre-wrap text-[11px] leading-relaxed text-muted-foreground">
                      {w.lyrics.slice(0, 120)}
                      {w.lyrics.length > 120 ? "…" : ""}
                    </p>
                    <div className="mt-auto flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                      <span>{fmtTime(w.created_at)}</span>
                      <span className="rounded bg-muted px-1.5 py-0.5">
                        {w.source === "roundtable" ? "圆桌" : w.source}
                      </span>
                      <button
                        onClick={() => void copyShareUrl("music", w.id)}
                        className="text-primary-text hover:underline"
                      >
                        分享
                      </button>
                      <button
                        onClick={() => setPublishFor(publishFor === w.id ? "" : w.id)}
                        className="text-primary-text hover:underline"
                      >
                        发布到群
                      </button>
                      <button
                        onClick={() => void deleteMusicWork(w.id)}
                        className="ml-auto text-danger hover:underline"
                      >
                        删除
                      </button>
                    </div>
                    {publishFor === w.id && (
                      <div className="mt-1 flex flex-wrap gap-1.5 border-t border-border pt-1.5">
                        {rooms.length === 0 ? (
                          <span className="text-[11px] text-muted-foreground">还没有群，先去 AI 导演工作室建群</span>
                        ) : (
                          rooms.slice(0, 4).map((r) => (
                            <button
                              key={r.id}
                              onClick={() => void publishToChat(w.id, r.id)}
                              className="rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[11px] hover:border-primary"
                            >
                              📢 {r.title}
                            </button>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* 对比视图：勾选 2 首并排 */}
              {compareWorks.length === 2 && (
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  {compareWorks.map((w, i) => (
                    <div key={w.id} className="rounded-lg border border-primary/30 bg-muted/20 p-3">
                      <p className="mb-1.5 text-sm font-semibold">
                        第 {i + 1} 首 ·《{w.title}》
                        {w.style && (
                          <span className="ml-2 rounded bg-primary/10 px-1.5 py-0.5 text-[10px]">
                            {w.style}
                          </span>
                        )}
                      </p>
                      <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs leading-relaxed">
                        {w.lyrics}
                      </pre>
                      {w.arrangement && (
                        <p className="mt-1.5 text-[11px] text-muted-foreground">
                          🎧 {w.arrangement.slice(0, 100)}…
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {musicWorks.length > 9 && (
                <p className="mt-2 text-[11px] text-muted-foreground">
                  共 {musicWorks.length} 首，仅显示最近 9 首
                </p>
              )}
            </>
          )}
          <button
            onClick={() => navigate("/create/music")}
            className="mt-3 text-xs text-primary-text hover:underline"
          >
            去创作新歌（音乐创作助手）→
          </button>
        </section>

        {/* 群演作品 */}
        <section className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <BookOpen className="h-4 w-4 text-primary-text" aria-hidden />
            群演作品（{playWorks.length}）
            <button
              onClick={() => navigate("/story")}
              className="ml-auto text-xs text-primary-text hover:underline"
              title="全部创作项目（含非群演剧本）"
            >
              查看全部项目 →
            </button>
          </h2>
          {loading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">加载中…</p>
          ) : playWorks.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              还没有作品。群聊里演完后，点「群信息 → 存入创作工作室」即可存档
            </p>
          ) : (
            <ul className="space-y-2">
              {playWorks.slice(0, 6).map((w) => (
                <li key={w.id}>
                  <button
                    onClick={() => navigate(`/story/${w.id}`)}
                    className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2 text-left transition-colors hover:border-primary"
                  >
                    <span className="truncate font-medium">{w.title}</span>
                    <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">
                      {fmtTime(w.updated_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {works.length > playWorks.length && (
            <button
              onClick={() => navigate("/story")}
              className="mt-3 text-xs text-primary-text hover:underline"
            >
              查看全部创作工作室项目（{works.length}）→
            </button>
          )}
        </section>

        {/* 创作群 */}
        <section className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <MessageCircle className="h-4 w-4 text-primary-text" aria-hidden />
            我的创作群（{rooms.length}）
          </h2>
          {loading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">加载中…</p>
          ) : rooms.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              还没有群。去「AI 导演工作室」给个主题，一键建组开演
            </p>
          ) : (
            <ul className="space-y-2">
              {rooms.slice(0, 6).map((r) => (
                <li key={r.id}>
                  <button
                    onClick={() => navigate(`/roleplay?chat=${r.id}`)}
                    className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2 text-left transition-colors hover:border-primary"
                  >
                    <span className="truncate font-medium">{r.title}</span>
                    <span className="ml-auto shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {r.message_count} 条演出
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <button
            onClick={() => navigate("/create/studio")}
            className="mt-3 text-xs text-primary-text hover:underline"
          >
            新建创作群（AI 导演工作室）→
          </button>
        </section>

        {/* 角色演员池 */}
        <section className="rounded-[var(--radius-card)] border border-border bg-surface p-4 lg:col-span-2">
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <Users className="h-4 w-4 text-primary-text" aria-hidden />
            角色演员池（{chars.length}）——选角时自动检索复用，越用越厚
          </h2>
          {loading ? (
            <p className="py-6 text-center text-sm text-muted-foreground">加载中…</p>
          ) : chars.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              还没有角色卡。AI 导演建组时会自动创建并沉淀到这里
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {chars.slice(0, 24).map((c) => (
                <button
                  key={c.asset_id}
                  onClick={() => navigate("/roleplay")}
                  className="rounded-full border border-border bg-muted/40 px-3 py-1 text-xs transition-colors hover:border-primary"
                  title="点击前往角色扮演"
                >
                  {c.name || c.filename}
                </button>
              ))}
              {chars.length > 24 && (
                <span className="px-2 py-1 text-xs text-muted-foreground">
                  +{chars.length - 24} 位…
                </span>
              )}
            </div>
          )}
          <button
            onClick={() => navigate("/roleplay")}
            className="mt-3 flex items-center gap-1 text-xs text-primary-text hover:underline"
          >
            <FolderOpen className="h-3.5 w-3.5" aria-hidden />
            前往角色扮演管理角色卡 →
          </button>
        </section>

        {/* 音乐作品详情弹窗 */}
        <Dialog open={detailWork !== null} onClose={() => setDetailWork(null)} title={detailWork ? `《${detailWork.title}》` : ""}>
        {detailWork && (
          <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto text-sm">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              {detailWork.style && (
                <span className="rounded bg-primary/10 px-2 py-0.5 text-primary-text">{detailWork.style}</span>
              )}
              {detailWork.tags &&
                detailWork.tags.split(",").filter(Boolean).slice(0, 4).map((t) => (
                  <span key={t} className="rounded bg-muted px-2 py-0.5 text-muted-foreground">{t}</span>
                ))}
              <span className="text-muted-foreground">{detailWork.created_at ? new Date(detailWork.created_at).toLocaleString("zh-CN") : ""}</span>
              <span className="rounded bg-muted px-2 py-0.5 text-muted-foreground">
                {detailWork.source === "roundtable" ? "圆桌" : detailWork.source}
              </span>
            </div>
            {detailWork.theme && (
              <p className="text-xs text-muted-foreground">主题：{detailWork.theme}</p>
            )}
            <div>
              <p className="mb-1 text-xs font-semibold text-foreground">🎤 歌词</p>
              <pre className="whitespace-pre-wrap rounded-lg bg-muted/40 p-3 text-xs leading-relaxed">{detailWork.lyrics}</pre>
            </div>
            {detailWork.chords && (
              <div>
                <p className="mb-1 text-xs font-semibold text-foreground">🎸 和弦谱</p>
                <pre className="whitespace-pre-wrap rounded-lg bg-muted/40 p-3 font-mono text-xs leading-relaxed">{detailWork.chords}</pre>
              </div>
            )}
            {detailWork.arrangement && (
              <div>
                <p className="mb-1 text-xs font-semibold text-foreground">🎧 编曲思路</p>
                <p className="rounded-lg bg-muted/40 p-3 text-xs leading-relaxed">{detailWork.arrangement}</p>
              </div>
            )}
            {detailWork.style_en && (
              <p className="text-xs text-muted-foreground">🎼 Suno 风格：{detailWork.style_en}</p>
            )}
            <div className="flex flex-wrap gap-2 border-t border-border pt-3">
              <button
                onClick={() => void copyShareUrl("music", detailWork.id)}
                className="rounded-full border border-border px-3 py-1 text-xs hover:border-primary"
              >
                🔗 复制分享链接
              </button>
              {rooms.length > 0 && (
                <select
                  value=""
                  onChange={(e) => {
                    if (e.target.value) {
                      void publishToChat(detailWork.id, e.target.value);
                    }
                  }}
                  className="rounded-full border border-border px-3 py-1 text-xs"
                >
                  <option value="">发布到创作群…</option>
                  {rooms.map((r) => (
                    <option key={r.id} value={r.id}>{r.title || r.id.slice(0, 8)}</option>
                  ))}
                </select>
              )}
              <button
                onClick={() => {
                  if (window.confirm(`确认删除「${detailWork.title}」？`)) {
                    void deleteMusicWork(detailWork.id);
                    setDetailWork(null);
                  }
                }}
                className="rounded-full border border-border px-3 py-1 text-xs text-danger hover:border-danger"
              >
                🗑 删除
              </button>
            </div>
          </div>
        )}
        </Dialog>
      </div>
    </div>
  );
}
