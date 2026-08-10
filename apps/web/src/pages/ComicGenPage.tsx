import { useState } from "react";

import { BookOpen, Download, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { PageHeader } from "@/components/layout/PageHeader";
import { RoundtablePanel } from "@/components/creation/RoundtablePanel";
import { EmptyState } from "@/components/ui/States";
import { useMediaTask } from "@/hooks/useMediaTask";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";
import { toClientApiPath } from "@/lib/paths";

const STYLES = ["日式漫画", "美式漫画", "极简线条", "水彩插画", "赛博朋克"];
const LAYOUTS = [
  { v: "grid", label: "网格" },
  { v: "manga", label: "条漫" },
] as const;
const PANEL_OPTS = [
  { v: 4, label: "4 格" },
  { v: 6, label: "6 格" },
  { v: 9, label: "9 格" },
];

interface ComicAsset {
  index: number;
  asset_id: string;
  url: string;
  scene: string;
  dialogue: string;
}

interface ComicCover {
  asset_id: string;
  url: string;
}

export function ComicGenPage() {
  const task = useMediaTask("/generations/comic/generate");
  const [genMode, setGenMode] = useState<"single" | "roundtable">("single");
  const [prompt, setPrompt] = useState("");
  const [panels, setPanels] = useState(4);
  const [style, setStyle] = useState(STYLES[0]);
  const [characters, setCharacters] = useState("");
  const [layout, setLayout] = useState<"grid" | "manga">("grid");
  const [comic, setComic] = useState<{
    assets: ComicAsset[];
    pageUrl: string;
    title: string;
    coverUrl: string;
  } | null>(null);

  async function generate() {
    if (!prompt.trim() || task.busy) return;
    setComic(null);
    const raw = await task.run({
      model: "grok-imagine-image",
      prompt,
      panels,
      style,
      characters,
      layout,
    });
    // 成功后解析每格资产 + 换取可展示 URL
    if (raw?.comic) {
      const c = raw.comic as { assets?: ComicAsset[]; title?: string; cover?: ComicCover | null };
      const assets = (c.assets ?? []).slice().sort((a, b) => a.index - b.index);
      const resolved = await Promise.all(
        assets.map(async (a) => {
          const acc = await apiClient.get<{ url: string }>(
            toClientApiPath(`/assets/${a.asset_id}/access-url`),
          );
          return { ...a, url: acc.url };
        }),
      );
      let coverUrl = "";
      if (c.cover?.asset_id) {
        const acc = await apiClient.get<{ url: string }>(
          toClientApiPath(`/assets/${c.cover.asset_id}/access-url`),
        );
        coverUrl = acc.url;
      }
      setComic({
        assets: resolved,
        pageUrl: task.result?.assetUrl ?? "",
        title: c.title ?? "",
        coverUrl,
      });
    }
  }

  return (
    <div>
      <PageHeader
        title="漫画生成"
        description="输入主题，自动分镜 → 逐格出图 → 拼合成漫画页"
      />
      {/* 模式切换：直接生成 / 创作圆桌 */}
      <div className="flex gap-1 border-b border-border px-4 pt-2 md:px-6" role="tablist">
        {(
          [
            { key: "single", label: "⚡ 直接生成" },
            { key: "roundtable", label: "🎙️ 创作圆桌（多角色讨论分镜方案）" },
          ] as { key: "single" | "roundtable"; label: string }[]
        ).map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={genMode === t.key}
            onClick={() => setGenMode(t.key)}
            className={cn(
              "rounded-t-lg border-b-2 px-4 py-2 text-sm font-medium transition-colors",
              genMode === t.key
                ? "border-primary text-primary-text"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {genMode === "roundtable" ? (
        <div className="p-4 md:p-6">
          <RoundtablePanel
            domain="comic"
            themeLabel="漫画主题"
            themePlaceholder="例如：一只会修钟表的猫，深夜帮老街的钟楼找回时间…"
            extraLabel="附加要求（可选）"
            extraPlaceholder="格数 / 画风（日式/美式/水彩）/ 角色设定…"
            onFinal={(f) => {
              if (f.content) {
                setPrompt(f.content);
                setGenMode("single");
              }
            }}
          />
        </div>
      ) : (
      <div className="grid gap-6 p-4 md:p-6 lg:grid-cols-[380px_1fr]">
        <div className="space-y-4 rounded-[var(--radius-card)] border border-border bg-surface p-5">
          <Field label="漫画主题" required>
            {({ id }) => (
              <Textarea
                id={id}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={4}
                placeholder="例如：一只橘猫和一只柴犬成为朋友，一起冒险的故事"
              />
            )}
          </Field>
          <Field label="角色设定" hint="可选，帮助分镜保持角色描述">
            {({ id }) => (
              <Input
                id={id}
                value={characters}
                onChange={(e) => setCharacters(e.target.value)}
                placeholder="例如：主角是戴着红色围巾的橘猫"
              />
            )}
          </Field>
          <Field label="格数">
            {() => (
            <div className="flex gap-2">
              {PANEL_OPTS.map((o) => (
                <button
                  key={o.v}
                  onClick={() => setPanels(o.v)}
                  className={`flex-1 rounded-xl border px-3 py-2 text-sm transition-colors ${
                    panels === o.v
                      ? "border-primary bg-primary/10 font-medium text-primary-text"
                      : "border-border text-muted-foreground hover:border-border-strong"
                  }`}
                >
                  {o.label}
                </button>
              ))}
            </div>
            )}
          </Field>
          <Field label="布局">
            {() => (
            <div className="flex gap-2">
              {LAYOUTS.map((o) => (
                <button
                  key={o.v}
                  onClick={() => setLayout(o.v)}
                  className={`flex-1 rounded-xl border px-3 py-2 text-sm transition-colors ${
                    layout === o.v
                      ? "border-primary bg-primary/10 font-medium text-primary-text"
                      : "border-border text-muted-foreground hover:border-border-strong"
                  }`}
                >
                  {o.label}
                </button>
              ))}
            </div>
            )}
          </Field>
          <Field label="风格">
            {() => (
            <div className="flex flex-wrap gap-2">
              {STYLES.map((s) => (
                <button
                  key={s}
                  onClick={() => setStyle(s)}
                  className={`rounded-full border px-3 py-1.5 text-xs transition-colors ${
                    style === s
                      ? "border-primary bg-primary/10 font-medium text-primary-text"
                      : "border-border text-muted-foreground hover:border-border-strong"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
            )}
          </Field>
          <Button onClick={() => void generate()} loading={task.busy} className="w-full">
            <BookOpen className="h-4 w-4" aria-hidden />
            生成漫画
          </Button>
          {task.busy && (
            <p className="text-xs text-muted-foreground">
              正在分镜 → 逐格出图（{panels} 格约 2-4 分钟）→ 拼合…
            </p>
          )}
          {task.error && (
            <p className="text-sm text-danger">{task.error}</p>
          )}
        </div>

        <div className="space-y-6">
          {task.status === "succeeded" && comic && (
            <>
              {comic.title && (
                <h3 className="text-xl font-bold">{comic.title}</h3>
              )}
              {comic.coverUrl && (
                <div className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
                  <h4 className="mb-3 text-sm font-semibold text-muted-foreground">封面</h4>
                  <img
                    src={comic.coverUrl}
                    alt="漫画封面"
                    className="mx-auto max-h-[480px] rounded-xl border border-border"
                  />
                </div>
              )}
              <div className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
                <div className="mb-3 flex items-center justify-between">
                  <h3 className="text-sm font-semibold">漫画页（拼合）</h3>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => void generate()}>
                      <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                      重新生成
                    </Button>
                    <a href={comic.pageUrl} download="comic.jpg" target="_blank" rel="noreferrer">
                      <Button variant="outline" size="sm">
                        <Download className="h-3.5 w-3.5" aria-hidden />
                        下载
                      </Button>
                    </a>
                  </div>
                </div>
                <img
                  src={comic.pageUrl}
                  alt="漫画页"
                  className="w-full rounded-xl border border-border"
                />
              </div>
              <div>
                <h3 className="mb-3 text-sm font-semibold">分镜详情（{comic.assets.length} 格）</h3>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {comic.assets.map((a) => (
                    <figure
                      key={a.index}
                      className="overflow-hidden rounded-xl border border-border bg-surface"
                    >
                      <img src={a.url} alt={`第 ${a.index + 1} 格`} className="w-full" />
                      <figcaption className="space-y-1 p-3">
                        <p className="text-xs text-muted-foreground">{a.scene}</p>
                        {a.dialogue && (
                          <p className="text-sm font-medium text-foreground">「{a.dialogue}」</p>
                        )}
                      </figcaption>
                    </figure>
                  ))}
                </div>
              </div>
            </>
          )}
          {task.status === "succeeded" && !comic && (
            <p className="text-sm text-muted-foreground">正在解析分镜数据…</p>
          )}
          {task.status === "" && (
            <EmptyState
              title="还没有漫画"
              description="填写左侧主题，一键生成带分镜的漫画页"
            />
          )}
        </div>
      </div>
      )}
    </div>
  );
}
