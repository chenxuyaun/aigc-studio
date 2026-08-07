import { useEffect, useMemo, useState } from "react";

import type { CatalogItem } from "@aigc/shared-types";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Download, FolderOpen, Image as ImageIcon, Wand2, X } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { useMediaTask } from "@/hooks/useMediaTask";
import { usePrivateMediaUrl } from "@/hooks/usePrivateMediaUrl";
import { apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";

const SIZE_PRESETS = [
  { label: "512²", w: 512, h: 512 },
  { label: "768²", w: 768, h: 768 },
  { label: "1024²", w: 1024, h: 1024 },
  { label: "1280×720", w: 1280, h: 720 },
  { label: "720×1280", w: 720, h: 1280 },
];

interface ImageHandoff {
  prompt?: string;
  negative_prompt?: string;
  reference_photo_id?: string;
  reference_asset_id?: string;
  reference_label?: string;
  width?: number;
  height?: number;
  model?: string;
}

export function ImageGenPage() {
  const location = useLocation();
  const handoff = (location.state as ImageHandoff | null) ?? null;
  const [prompt, setPrompt] = useState(handoff?.prompt ?? "");
  const [negative, setNegative] = useState(handoff?.negative_prompt ?? "");
  const [width, setWidth] = useState(handoff?.width ?? 512);
  const [height, setHeight] = useState(handoff?.height ?? 512);
  const [numImages, setNumImages] = useState(1);
  // 高级参数：seed 固定可复现；cfg_scale/steps 对真实模型生效
  const [seed, setSeed] = useState<string>("");
  const [cfgScale, setCfgScale] = useState<string>("");
  const [steps, setSteps] = useState<string>("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [model, setModel] = useState(handoff?.model ?? "");
  const [refPhotoId, setRefPhotoId] = useState<string | null>(
    handoff?.reference_photo_id ?? null,
  );
  const [refAssetId, setRefAssetId] = useState<string | null>(
    handoff?.reference_asset_id ?? null,
  );
  const [refLabel, setRefLabel] = useState(handoff?.reference_label ?? "");
  const task = useMediaTask("/generations/image/generate");

  // DB Provider 驱动模型选项：内置 huggingface + 已注册 Provider（自动出现）
  const dbProviders = useQuery({
    queryKey: ["providers", "public"],
    queryFn: async () => {
      try {
        return await apiClient.get<CatalogItem[]>("/providers/catalog");
      } catch {
        return await apiClient.get<CatalogItem[]>("/providers/");
      }
    },
    staleTime: 30_000,
  });
  const MODEL_OPTS = useMemo(
    () => [
      { v: "huggingface", label: "HuggingFace SDXL（需外网）" },
      ...(dbProviders.data ?? []).map((p) => ({
        v: p.id,
        label: `${p.name}${p.default_model ? ` · ${p.default_model}` : ""}`,
      })),
    ],
    [dbProviders.data],
  );

  // location.state 变化时同步（从写真再次跳入）
  useEffect(() => {
    if (!handoff) return;
    if (handoff.prompt) setPrompt(handoff.prompt);
    if (handoff.negative_prompt !== undefined) setNegative(handoff.negative_prompt);
    if (handoff.reference_photo_id) {
      setRefPhotoId(handoff.reference_photo_id);
      setRefAssetId(null);
      setRefLabel(handoff.reference_label ?? "写真参考");
    }
    if (handoff.reference_asset_id) {
      setRefAssetId(handoff.reference_asset_id);
      setRefPhotoId(null);
      setRefLabel(handoff.reference_label ?? "素材参考");
    }
    if (handoff.width) setWidth(handoff.width);
    if (handoff.height) setHeight(handoff.height);
    if (handoff.model) setModel(handoff.model);
  }, [handoff]);

  const refAccess =
    refPhotoId != null
      ? `/photography/photos/${refPhotoId}/access-url`
      : refAssetId != null
        ? `/assets/${refAssetId}/access-url`
        : null;
  const refMedia = usePrivateMediaUrl(refAccess);

  function clearReference() {
    setRefPhotoId(null);
    setRefAssetId(null);
    setRefLabel("");
  }

  function generate() {
    if (!prompt.trim() || task.busy) return;
    void task.run({
      model,
      prompt,
      negative_prompt: negative,
      width,
      height,
      num_images: numImages,
      seed: seed ? Number(seed) : undefined,
      cfg_scale: cfgScale ? Number(cfgScale) : undefined,
      steps: steps ? Number(steps) : undefined,
      reference_photo_id: refPhotoId,
      reference_asset_id: refAssetId,
    });
  }

  /** 变体：固定当前 prompt/参数，自动换一个 seed 再生成。 */
  function generateVariant() {
    if (!prompt.trim() || task.busy) return;
    const base = seed ? Number(seed) : Math.floor(Math.random() * 2 ** 31);
    const next = (base + Math.floor(Math.random() * 100000) + 1) % 2 ** 31;
    setSeed(String(next));
    // 等 state 生效后生成
    setTimeout(() => {
      void task.run({
        model,
        prompt,
        negative_prompt: negative,
        width,
        height,
        num_images: numImages,
        seed: next,
        cfg_scale: cfgScale ? Number(cfgScale) : undefined,
        steps: steps ? Number(steps) : undefined,
        reference_photo_id: refPhotoId,
        reference_asset_id: refAssetId,
      });
    }, 0);
  }

  async function downloadResult() {
    if (!task.result?.assetUrl) return;
    const a = document.createElement("a");
    a.href = task.result.assetUrl;
    a.download = `image-${task.result.assetId.slice(0, 8)}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  return (
    <div>
      <PageHeader
        title="图片生成"
        description={
          model
            ? `当前模型：${model}`
            : "未选择模型（将自动使用已启用 Provider）"
        }
      />
      <div className="grid gap-4 p-4 md:grid-cols-[360px_1fr] md:p-6">
        <div className="flex flex-col gap-4">
          <Field
            label="模型 / Provider"
            hint="已注册的 DB Provider（Grok 等）自动出现在列表"
          >
            {({ id }) => (
              <select
                id={id}
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="h-10 w-full rounded-lg border border-input bg-surface px-3 text-sm"
              >
                {MODEL_OPTS.map((o) => (
                  <option key={o.v} value={o.v}>
                    {o.label}
                  </option>
                ))}
                {!MODEL_OPTS.some((o) => o.v === model) && (
                  <option value={model}>{model}</option>
                )}
              </select>
            )}
          </Field>
          <Field label="参考图" hint="可从写真相册「用作参考出图」带入">
            {() =>
              refPhotoId || refAssetId ? (
                <div className="flex items-center gap-3 rounded-xl border border-border p-2">
                  <div className="h-16 w-16 overflow-hidden rounded-lg bg-muted">
                    {refMedia.url ? (
                      <img
                        src={refMedia.url}
                        alt={refLabel || "参考图"}
                        className="h-full w-full object-cover"
                        referrerPolicy="no-referrer"
                      />
                    ) : (
                      <div className="h-full w-full animate-pulse bg-muted" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{refLabel || "参考图"}</p>
                    <p className="truncate font-mono text-[11px] text-muted-foreground">
                      {refPhotoId ? `photo ${refPhotoId}` : `asset ${refAssetId}`}
                    </p>
                  </div>
                  <Button variant="ghost" size="sm" onClick={clearReference} aria-label="移除参考图">
                    <X className="h-4 w-4" aria-hidden />
                  </Button>
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  <Link
                    to="/photography"
                    className="inline-flex h-9 items-center rounded-xl border border-dashed border-border px-3 text-sm text-muted-foreground hover:border-primary hover:text-primary"
                  >
                    从写真选择
                  </Link>
                  <Link
                    to="/assets"
                    className="inline-flex h-9 items-center rounded-xl border border-dashed border-border px-3 text-sm text-muted-foreground hover:border-primary hover:text-primary"
                  >
                    从素材库选择
                  </Link>
                </div>
              )
            }
          </Field>

          <Field label="提示词" required>
            {({ id }) => (
              <Textarea
                id={id}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={6}
                placeholder="例如：保持参考人物气质，换成都市夜景，电影感光影"
              />
            )}
          </Field>
          <Field label="负面提示词" hint="不希望出现的元素">
            {({ id }) => (
              <Textarea
                id={id}
                value={negative}
                onChange={(e) => setNegative(e.target.value)}
                rows={2}
                placeholder="模糊、低质量、文字…"
              />
            )}
          </Field>
          <Field label="尺寸预设">
            {() => (
              <div className="flex flex-wrap gap-2">
                {SIZE_PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    onClick={() => {
                      setWidth(p.w);
                      setHeight(p.h);
                    }}
                    className={
                      width === p.w && height === p.h
                        ? "rounded-lg border border-primary bg-primary/12 px-2.5 py-1 text-xs font-semibold text-primary"
                        : "rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground hover:border-primary"
                    }
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            )}
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="宽">
              {({ id }) => (
                <Input
                  id={id}
                  type="number"
                  min={64}
                  max={2048}
                  value={width}
                  onChange={(e) => {
                    const v = Math.min(2048, Math.max(64, Number(e.target.value) || 512));
                    setWidth(v);
                  }}
                />
              )}
            </Field>
            <Field label="高">
              {({ id }) => (
                <Input
                  id={id}
                  type="number"
                  min={64}
                  max={2048}
                  value={height}
                  onChange={(e) => {
                    const v = Math.min(2048, Math.max(64, Number(e.target.value) || 512));
                    setHeight(v);
                  }}
                />
              )}
            </Field>
          </div>
          <Field label="张数">
            {({ id }) => (
              <Input
                id={id}
                type="number"
                min={1}
                max={4}
                value={numImages}
                onChange={(e) =>
                  setNumImages(Math.min(4, Math.max(1, Number(e.target.value) || 1)))
                }
              />
            )}
          </Field>
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-primary"
          >
            <ChevronDown
              className={cn("h-3.5 w-3.5 transition-transform", showAdvanced && "rotate-180")}
              aria-hidden
            />
            高级参数{showAdvanced ? "" : "（种子 / 采样）"}
          </button>
          {showAdvanced && (
            <div className="grid grid-cols-3 gap-3">
              <Field label="种子 Seed" hint="固定后可复现同一张图">
                {({ id }) => (
                  <Input
                    id={id}
                    type="number"
                    min={0}
                    max={4294967295}
                    value={seed}
                    onChange={(e) => setSeed(e.target.value)}
                    placeholder="随机"
                  />
                )}
              </Field>
              <Field label="CFG 强度">
                {({ id }) => (
                  <Input
                    id={id}
                    type="number"
                    min={1}
                    max={20}
                    step={0.5}
                    value={cfgScale}
                    onChange={(e) => setCfgScale(e.target.value)}
                    placeholder="默认"
                  />
                )}
              </Field>
              <Field label="采样步数">
                {({ id }) => (
                  <Input
                    id={id}
                    type="number"
                    min={1}
                    max={100}
                    value={steps}
                    onChange={(e) => setSteps(e.target.value)}
                    placeholder="默认"
                  />
                )}
              </Field>
            </div>
          )}
          <Button onClick={generate} loading={task.busy} disabled={!prompt.trim()}>
            <Wand2 className="h-4 w-4" aria-hidden />
            {refPhotoId || refAssetId ? "参考生成" : "生成图片"}
          </Button>
          {task.busy && <ProgressBar progress={task.progress} status={task.status} />}
          {task.error && (
            <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
              {task.error}
            </p>
          )}
          {task.result && (
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className={
                    task.result.isReal
                      ? "rounded-full bg-success/12 px-2.5 py-0.5 text-xs font-medium text-success"
                      : "rounded-full bg-warning/12 px-2.5 py-0.5 text-xs font-medium text-warning"
                  }
                >
                  {task.result.isReal
                    ? `真实生成 · ${task.result.provider ?? "provider"}`
                    : "生成结果"}
                </span>
                {task.result.fallbackReason && (
                  <span className="text-xs text-muted-foreground" title={task.result.fallbackReason}>
                    已回退
                  </span>
                )}
              </div>
              {task.result.fallbackReason && (
                <p
                  className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs text-warning"
                  role="status"
                >
                  {task.result.fallbackReason}
                </p>
              )}
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" onClick={() => void downloadResult()}>
                  <Download className="h-4 w-4" aria-hidden />
                  下载
                </Button>
                <Button variant="outline" size="sm" onClick={generate} disabled={task.busy}>
                  再生成
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={generateVariant}
                  disabled={task.busy}
                  title="保留当前提示词与参数，自动换一个种子生成"
                >
                  <Wand2 className="h-4 w-4" aria-hidden />
                  变体
                </Button>
                <Link
                  to="/assets"
                  state={{ highlight: task.result.assetId }}
                  className="inline-flex h-8 items-center gap-1 rounded-xl border border-border px-3 text-sm hover:border-primary"
                >
                  <FolderOpen className="h-4 w-4" aria-hidden />
                  去素材库
                </Link>
                <Link
                  to="/tasks"
                  className="inline-flex h-8 items-center text-sm text-primary hover:underline"
                >
                  任务中心
                </Link>
              </div>
            </div>
          )}
        </div>

        <div className="relative flex min-h-80 items-center justify-center rounded-[var(--radius-card)] border border-border bg-surface">
          {task.result ? (
            <>
              <img
                src={task.result.assetUrl}
                alt={`生成结果：${prompt}`}
                className="max-h-[70dvh] max-w-full rounded-lg"
              />
              <div className="absolute left-3 top-3">
                <span
                  className={
                    task.result.isReal
                      ? "rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-white"
                      : "rounded-md bg-black/55 px-2 py-1 text-[11px] font-medium text-warning"
                  }
                >
                  {task.result.isReal ? "Real" : "Result"}
                </span>
              </div>
            </>
          ) : (
            <div className="flex flex-col items-center gap-2 text-muted-foreground">
              <ImageIcon className="h-8 w-8" aria-hidden />
              <p className="text-sm">生成的图片会显示在这里</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
