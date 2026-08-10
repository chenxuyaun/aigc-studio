import { useEffect, useState } from "react";

import { Music } from "lucide-react";
import { useParams } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";

interface SharedWork {
  id: string;
  title: string;
  theme: string;
  style: string;
  lyrics: string;
  chords: string;
  arrangement: string;
  style_en: string;
  created_at: string;
}

export function SharedMusicPage() {
  const { workId } = useParams<{ workId: string }>();
  const [work, setWork] = useState<SharedWork | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!workId) return;
    void (async () => {
      try {
        // 公开只读分享页：匿名访问，不走鉴权
        const res = await fetch(
          `/api/v1/generations/music/works/${workId}/public`,
        );
        if (!res.ok) throw new Error("作品不存在或已删除");
        setWork((await res.json()) as SharedWork);
      } catch (e) {
        setError(e instanceof Error ? e.message : "作品不存在或已删除");
      }
    })();
  }, [workId]);

  return (
    <div>
      <PageHeader
        title="音乐作品分享"
        description="朋友分享给你的一首歌"
      />
      <div className="p-4 md:p-6">
        {error ? (
          <div className="rounded-[var(--radius-card)] border border-border bg-surface p-6 text-center text-sm text-muted-foreground">
            {error}
          </div>
        ) : !work ? (
          <div className="rounded-[var(--radius-card)] border border-border bg-surface p-6 text-center text-sm text-muted-foreground">
            加载中…
          </div>
        ) : (
          <div className="mx-auto flex max-w-2xl flex-col gap-4 rounded-[var(--radius-card)] border border-border bg-surface p-6">
            <div className="flex items-center gap-2">
              <Music className="h-5 w-5 text-primary-text" aria-hidden />
              <h2 className="font-display text-xl font-bold">《{work.title}》</h2>
              {work.style && (
                <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary-text">
                  {work.style}
                </span>
              )}
            </div>
            {work.theme && (
              <p className="text-xs text-muted-foreground">创作主题：{work.theme}</p>
            )}
            <div className="rounded-lg bg-muted/40 p-4">
              <p className="mb-2 text-xs font-semibold">🎤 歌词</p>
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
                {work.lyrics}
              </pre>
            </div>
            {work.chords && (
              <div className="rounded-lg bg-muted/40 p-4">
                <p className="mb-2 text-xs font-semibold">🎸 和弦谱</p>
                <pre className="whitespace-pre-wrap font-mono text-sm leading-relaxed">
                  {work.chords}
                </pre>
              </div>
            )}
            {work.arrangement && (
              <div className="rounded-lg bg-muted/40 p-4">
                <p className="mb-2 text-xs font-semibold">🎧 编曲思路</p>
                <p className="text-sm leading-relaxed">{work.arrangement}</p>
              </div>
            )}
            {work.style_en && (
              <p className="text-xs text-muted-foreground">
                🎼 Suno 风格：{work.style_en}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
