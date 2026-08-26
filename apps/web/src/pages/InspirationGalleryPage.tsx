import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Copy, Layers, Search, Sparkles, Wand2 } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { copyText } from "@/lib/clipboard";

/**
 * saiOS v2 —— 灵感画廊（/inspiration）
 * 数据源：gpt-image2.canghe.ai 同源开源库 awesome-gpt-image-2 的 529 个真实案例
 * （prompt 全文 + 分类/风格/场景标签 + 成品图）。纯静态实现，零后端依赖。
 *
 * 三个核心能力：
 *  1. category/styles/scenes 维度浏览 + 全文搜索
 *  2. 高频风格词 + 共现「风格配方」，一键作为预设带去 Studio
 *  3. prompt 相似度推荐（前端 TF-IDF 余弦，529×529 毫秒级）
 */

interface CaseItem {
  id: number;
  t: string;
  c: string;
  st: string[];
  sc: string[];
  f: boolean;
  img: string;
  p: string;
}

/**
 * 画廊静态资源路径：nginx 已把 ^/gallery 前缀直接路由给 saiOS 容器（与 /static 同级），
 * 因此统一走根绝对路径——本地 vite dev 与公网均成立。勿拼 /saios 前缀（会被 SPA fallback 吃掉返回 HTML）。
 */
const GALLERY_BASE = "/gallery";

const STOP = new Set([
  "的", "了", "在", "是", "和", "与", "上", "下", "中", "为", "你", "我", "他", "她", "它", "们", "这", "那", "一个",
  "the", "a", "an", "of", "and", "to", "in", "for", "with", "on", "at", "is", "are", "by", "from", "as",
]);

/** 中文 bigram + 英文单词混合分词 */
function tokenize(s: string): string[] {
  const out: string[] = [];
  for (const w of s.toLowerCase().match(/[a-z][a-z0-9'-]{1,}/g) ?? []) if (!STOP.has(w)) out.push(w);
  for (const seg of s.replace(/[^\u4e00-\u9fa5]+/g, " ").split(/\s+/)) {
    for (let i = 0; i < seg.length - 1; i++) {
      const bg = seg.slice(i, i + 2);
      if (!STOP.has(bg)) out.push(bg);
    }
  }
  return out;
}

interface VecIdx {
  vecs: Map<string, number>[];
}

function buildIndex(prompts: string[]): VecIdx {
  const docs = prompts.map(tokenize);
  const df = new Map<string, number>();
  for (const terms of docs) for (const t of new Set(terms)) df.set(t, (df.get(t) ?? 0) + 1);
  const n = docs.length;
  const vecs = docs.map((terms) => {
    const tf = new Map<string, number>();
    for (const t of terms) tf.set(t, (tf.get(t) ?? 0) + 1);
    const v = new Map<string, number>();
    let norm = 0;
    for (const [t, f] of tf) {
      const w = (f / terms.length) * Math.log(n / (df.get(t) ?? 1));
      v.set(t, w);
      norm += w * w;
    }
    norm = Math.sqrt(norm) || 1;
    for (const [t, w] of v) v.set(t, w / norm);
    return v;
  });
  return { vecs };
}

function topSimilar(idx: VecIdx, i: number, k: number): { j: number; score: number }[] {
  const a = idx.vecs[i];
  if (!a) return [];
  const scored: { j: number; score: number }[] = [];
  for (let j = 0; j < idx.vecs.length; j++) {
    if (j === i) continue;
    const b = idx.vecs[j];
    if (!b) continue;
    const small = a.size < b.size ? a : b;
    const large = a.size < b.size ? b : a;
    let s = 0;
    small.forEach((w, t) => {
      const wb = large.get(t);
      if (wb) s += w * wb;
    });
    scored.push({ j, score: s });
  }
  scored.sort((x, y) => y.score - x.score);
  return scored.slice(0, k);
}

export function InspirationGalleryPage() {
  const navigate = useNavigate();
  const [category, setCategory] = useState("");
  const [styleSel, setStyleSel] = useState<string[]>([]);
  const [scene, setScene] = useState("");
  const [q, setQ] = useState("");
  const [detail, setDetail] = useState<CaseItem | null>(null);
  const [copied, setCopied] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["gallery-cases"],
    queryFn: async () => {
      const res = await fetch(`${GALLERY_BASE}/cases.json`);
      if (!res.ok) throw new Error(`加载案例库失败 (${res.status})`);
      return (await res.json()) as CaseItem[];
    },
    staleTime: Infinity,
  });

  const cases = data ?? [];

  // ── 统计：分类 / 高频风格词 / 风格共现配方 / 场景 ──
  const stats = useMemo(() => {
    const cat = new Map<string, number>();
    const wordFreq = new Map<string, number>();
    const pairFreq = new Map<string, number>();
    const sceneFreq = new Map<string, number>();
    for (const c of cases) {
      cat.set(c.c, (cat.get(c.c) ?? 0) + 1);
      for (const s of c.sc ?? []) sceneFreq.set(s, (sceneFreq.get(s) ?? 0) + 1);
      const styles = [...(c.st ?? [])].sort();
      for (const s of styles) wordFreq.set(s, (wordFreq.get(s) ?? 0) + 1);
      for (let i = 0; i < styles.length; i++)
        for (let j = i + 1; j < styles.length; j++) {
          const key = `${styles[i]}|${styles[j]}`;
          pairFreq.set(key, (pairFreq.get(key) ?? 0) + 1);
        }
    }
    const top = (m: Map<string, number>, n: number): [string, number][] =>
      [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, n);
    return {
      cats: top(cat, 99),
      hotStyles: top(wordFreq, 16),
      recipes: top(pairFreq, 8).map(([k, v]) => ({ a: k.split("|")[0], b: k.split("|")[1], n: v })),
      scenes: top(sceneFreq, 12),
    };
  }, [cases]);

  // ── 相似度索引（数据就绪后构建一次）──
  const index = useMemo(() => (cases.length ? buildIndex(cases.map((c) => c.p)) : null), [cases]);

  // ── 筛选 ──
  const filtered = useMemo(() => {
    const kw = q.trim().toLowerCase();
    return cases.filter(
      (c) =>
        (!category || c.c === category) &&
        (!scene || (c.sc ?? []).includes(scene)) &&
        styleSel.every((s) => (c.st ?? []).includes(s)) &&
        (!kw || c.p.toLowerCase().includes(kw) || c.t.toLowerCase().includes(kw)),
    );
  }, [cases, category, scene, styleSel, q]);

  // 详情的相似推荐
  const similar = useMemo(() => {
    if (!detail || !index) return [];
    const at = cases.findIndex((c) => c.id === detail.id);
    if (at < 0) return [];
    return topSimilar(index, at, 6)
      .map(({ j }) => cases[j])
      .filter((c): c is CaseItem => Boolean(c));
  }, [detail, index, cases]);

  function toggleStyle(s: string) {
    setStyleSel((v) => (v.includes(s) ? v.filter((x) => x !== s) : [...v, s]));
  }

  function copy(text: string, tag: string) {
    void copyText(text);
    setCopied(tag);
    setTimeout(() => setCopied(""), 1600);
  }

  function openInStudio(prompt: string) {
    navigate(`/studio?prompt=${encodeURIComponent(prompt)}`);
  }

  useEffect(() => {
    document.title = "灵感画廊 · saiOS";
  }, []);

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8">
      <PageHeader
        title="灵感画廊"
        description="gpt-image2 案例库 · 529 组真实出图案例，按分类/风格/场景浏览，一键把 prompt 带进 Studio 再创作"
      />

      {/* ═══ 风格配方（高频共现组合）═══ */}
      {!isLoading && stats.recipes.length > 0 && (
        <section className="mb-6 rounded-card border border-border bg-surface p-4">
          <p className="mb-3 flex items-center gap-1.5 text-xs font-bold uppercase tracking-widest text-primary-text">
            <Sparkles className="h-3.5 w-3.5" aria-hidden /> 高频风格配方 · 案例库中共现最多的风格组合
          </p>
          <div className="flex flex-wrap gap-2">
            {stats.recipes.map((r) => (
              <button
                key={`${r.a}+${r.b}`}
                onClick={() => openInStudio(`【风格配方】${r.a} + ${r.b}\n主题：（描述你想画的画面，例如：一只戴宇航头盔的橘猫漂浮在星云中）`)}
                className="group inline-flex items-center gap-2 rounded-full border border-border bg-muted px-3.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
                title="点击带此配方去 Studio 开新图"
              >
                <span className="text-foreground">{r.a}</span>
                <span className="text-primary-text">+</span>
                <span className="text-foreground">{r.b}</span>
                <span className="font-mono text-[10px] opacity-60">{r.n} 例</span>
                <Wand2 className="h-3 w-3 opacity-0 text-primary-text transition-opacity group-hover:opacity-100" aria-hidden />
              </button>
            ))}
          </div>
        </section>
      )}

      {/* ═══ 筛选区 ═══ */}
      <div className="mb-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索 prompt 关键词…（如：霓虹、赛博、猫、logo）"
              className="h-10 w-full rounded-xl border border-input bg-surface pl-9 pr-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          <select
            value={scene}
            onChange={(e) => setScene(e.target.value)}
            className="h-10 rounded-xl border border-input bg-surface px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="">全部场景</option>
            {stats.scenes.map(([s, n]) => (
              <option key={s} value={s}>
                {s} ({n})
              </option>
            ))}
          </select>
        </div>

        {/* 分类 tab */}
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => setCategory("")}
            className={`rounded-full px-3 py-1.5 text-xs font-medium ${!category ? "bg-primary text-primary-foreground" : "border border-border text-muted-foreground hover:text-foreground"}`}
          >
            全部 ({cases.length})
          </button>
          {stats.cats.map(([c, n]) => (
            <button
              key={c}
              onClick={() => setCategory(category === c ? "" : c)}
              className={`rounded-full px-3 py-1.5 text-xs font-medium ${category === c ? "bg-primary text-primary-foreground" : "border border-border text-muted-foreground hover:text-foreground"}`}
            >
              {c} ({n})
            </button>
          ))}
        </div>

        {/* 高频风格 chips */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">热门风格</span>
          {stats.hotStyles.map(([s, n]) => (
            <button
              key={s}
              onClick={() => toggleStyle(s)}
              className={`rounded-full px-2.5 py-1 text-[11px] ${styleSel.includes(s) ? "bg-primary-text/15 font-semibold text-primary-text ring-1 ring-primary-text" : "border border-border text-muted-foreground hover:border-primary hover:text-foreground"}`}
            >
              {s} <span className="font-mono text-[9px] opacity-60">{n}</span>
            </button>
          ))}
          {(category || scene || styleSel.length > 0 || q) && (
            <button
              onClick={() => {
                setCategory("");
                setScene("");
                setStyleSel([]);
                setQ("");
              }}
              className="ml-auto text-xs text-danger hover:underline"
            >
              清除全部筛选
            </button>
          )}
        </div>
      </div>

      {/* ═══ 结果网格 ═══ */}
      {error ? (
        <ErrorState error={error} />
      ) : isLoading ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="aspect-square animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState title="没有匹配的案例" description="换个关键词或清除筛选试试" />
      ) : (
        <>
          <p className="mb-2 font-mono text-[11px] text-muted-foreground">{filtered.length} 个案例</p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {filtered.map((c) => (
              <button
                key={c.id}
                onClick={() => setDetail(c)}
                className="group overflow-hidden rounded-xl border border-border bg-surface text-left shadow-[var(--shadow-soft)] transition-all hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)]"
              >
                <div className="relative aspect-square overflow-hidden bg-muted">
                  <img
                    src={`${GALLERY_BASE}/img/${c.img.replace(/^data\/images\//, "")}`}
                    alt={c.t}
                    loading="lazy"
                    className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                  />
                  {c.f && (
                    <span className="absolute left-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-[9px] font-bold text-amber-300 backdrop-blur">
                      ★ 精选
                    </span>
                  )}
                </div>
                <div className="p-2.5">
                  <p className="truncate text-xs font-semibold">{c.t}</p>
                  <p className="mt-1 truncate text-[10px] text-muted-foreground">
                    {c.c} · {(c.st ?? []).slice(0, 2).join(" / ")}
                  </p>
                </div>
              </button>
            ))}
          </div>
        </>
      )}

      {/* ═══ 详情抽屉 ═══ */}
      {detail && (
        <Dialog open onClose={() => setDetail(null)} title={detail.t}>
          <div className="max-h-[75dvh] space-y-4 overflow-y-auto p-4">
            <img
              src={`${GALLERY_BASE}/img/${detail.img.replace(/^data\/images\//, "")}`}
              alt={detail.t}
              className="max-h-[46dvh] w-full rounded-xl object-contain"
            />
            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              <span className="rounded-full bg-muted px-2.5 py-1 font-medium">{detail.c}</span>
              {(detail.st ?? []).map((s) => (
                <button
                  key={s}
                  onClick={() => {
                    if (!styleSel.includes(s)) toggleStyle(s);
                    setDetail(null);
                  }}
                  className="rounded-full border border-border px-2.5 py-1 text-muted-foreground hover:border-primary hover:text-foreground"
                >
                  {s}
                </button>
              ))}
              {(detail.sc ?? []).map((s) => (
                <span key={s} className="rounded-full bg-primary/10 px-2.5 py-1 text-primary-text">
                  {s}
                </span>
              ))}
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Prompt 全文</p>
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-xl border border-border bg-muted/50 p-3 text-xs leading-relaxed">
                {detail.p}
              </pre>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => copy(detail.p, `case-${detail.id}`)}>
                <Copy className="h-3.5 w-3.5" aria-hidden />
                {copied === `case-${detail.id}` ? "已复制 ✓" : "复制 Prompt"}
              </Button>
              <Button size="sm" variant="outline" onClick={() => openInStudio(detail.p)}>
                <Sparkles className="h-3.5 w-3.5" aria-hidden />
                在 Studio 打开
              </Button>
            </div>

            {/* 相似推荐 */}
            {similar.length > 0 && (
              <div>
                <p className="mb-2 flex items-center gap-1 text-xs font-bold uppercase tracking-widest text-primary-text">
                  <Layers className="h-3.5 w-3.5" aria-hidden /> Prompt 相似推荐
                </p>
                <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                  {similar.map((sc) => (
                    <button
                      key={sc.id}
                      onClick={() => setDetail(sc)}
                      className="overflow-hidden rounded-lg border border-border transition-transform hover:-translate-y-0.5"
                      title={sc.t}
                    >
                      <img
                        src={`${GALLERY_BASE}/img/${sc.img.replace(/^data\/images\//, "")}`}
                        alt={sc.t}
                        loading="lazy"
                        className="aspect-square w-full object-cover"
                      />
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Dialog>
      )}
    </div>
  );
}
