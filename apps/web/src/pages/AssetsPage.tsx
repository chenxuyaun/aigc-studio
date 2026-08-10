import { useMemo, useRef, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download, FileAudio, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import type { Asset, MediaAccess, Paginated } from "@aigc/shared-types";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Dialog } from "@/components/ui/Dialog";
import { GridSkeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { usePrivateMediaUrl } from "@/hooks/usePrivateMediaUrl";
import { AppError, apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";
import { toClientApiPath } from "@/lib/paths";

const PAGE_SIZE = 24;

const FILTERS = [
  { v: "", label: "全部" },
  { v: "image/", label: "图片" },
  { v: "audio/", label: "音频" },
  { v: "video/", label: "视频" },
];

function AssetThumb({ asset }: { asset: Asset }) {
  const isImage = asset.mime_type.startsWith("image/");
  const endpoint = asset.access_url_endpoint ?? `/assets/${asset.id}/access-url`;
  const { url, loading } = usePrivateMediaUrl(isImage ? endpoint : null);

  if (isImage) {
    return (
      <div className="flex aspect-square items-center justify-center overflow-hidden bg-surface">
        {url ? (
          <img
            src={url}
            alt={asset.filename}
            className="h-full w-full object-cover"
            referrerPolicy="no-referrer"
          />
        ) : (
          <div className={`h-full w-full bg-muted ${loading ? "animate-pulse" : ""}`} />
        )}
      </div>
    );
  }
  return (
    <div className="flex aspect-square items-center justify-center bg-surface text-muted-foreground">
      <FileAudio className="h-8 w-8" aria-hidden />
    </div>
  );
}

async function downloadAsset(asset: Asset) {
  const accessPath = toClientApiPath(
    asset.access_url_endpoint ?? `/assets/${asset.id}/access-url`,
  );
  const access = await apiClient.get<MediaAccess>(accessPath);
  if (access.url.startsWith("http://") || access.url.startsWith("https://")) {
    const a = document.createElement("a");
    a.href = access.url;
    a.download = asset.filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
    return;
  }
  const blob = await apiClient.getBlob(toClientApiPath(access.url));
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = asset.filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function AssetsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const highlight = (location.state as { highlight?: string } | null)?.highlight ?? "";
  const [page, setPage] = useState(1);
  const [section, setSection] = useState<"assets" | "photography">("assets");
  const [mimePrefix, setMimePrefix] = useState("");
  const [toDelete, setToDelete] = useState<Asset | null>(null);
  const [preview, setPreview] = useState<Asset | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  // 多文件上传进度：当前文件序号 / 总数 / 当前文件百分比 + 失败明细
  const [uploadDone, setUploadDone] = useState(0);
  const [uploadTotal, setUploadTotal] = useState(0);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [uploadFailures, setUploadFailures] = useState<string[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const query = useQuery({
    queryKey: ["assets", { page, mimePrefix }],
    queryFn: () => {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (mimePrefix) params.set("mime_prefix", mimePrefix);
      return apiClient.get<Paginated<Asset>>(`/assets/?${params}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiClient.del(`/assets/${id}`),
    onSuccess: () => {
      setToDelete(null);
      setPreview(null);
      void qc.invalidateQueries({ queryKey: ["assets"] });
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async (files: FileList) => {
      const results: Asset[] = [];
      const failures: string[] = [];
      const all = Array.from(files);
      setUploadTotal(all.length);
      setUploadDone(0);
      setUploadPercent(0);
      setUploadFailures([]);
      for (let i = 0; i < all.length; i += 1) {
        const file = all[i]!;
        try {
          const form = new FormData();
          form.append("file", file);
          // 尾斜杠与后端 POST /assets/ 对齐，避免 307 重定向丢失 Authorization。
          const asset = await apiClient.postFormWithProgress<Asset>("/assets/", form, (p) =>
            setUploadPercent(p),
          );
          results.push(asset);
        } catch (err) {
          failures.push(
            `${file.name}: ${err instanceof AppError ? err.message : "上传失败"}`,
          );
        }
        setUploadDone(i + 1);
      }
      if (failures.length > 0) setUploadFailures(failures);
      return results;
    },
    onSuccess: (results) => {
      if (results.length > 0) {
        setUploadError(null);
        toast.success(`上传成功 ${results.length} 个素材`);
        void qc.invalidateQueries({ queryKey: ["assets"] });
      }
    },
    onError: (err) => {
      setUploadError(err instanceof AppError ? err.message : "上传失败");
    },
  });

  function handleUpload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploadError(null);
    uploadMutation.mutate(files);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    handleUpload(e.dataTransfer.files);
  }

  const pages = query.data?.pages ?? 0;
  const total = query.data?.total ?? 0;
  const items = query.data?.items ?? [];

  const previewEndpoint = useMemo(
    () =>
      preview
        ? preview.access_url_endpoint ?? `/assets/${preview.id}/access-url`
        : null,
    [preview],
  );
  // 图片/音频/视频统一走 access-url 预览（之前只传 image，导致音视频永远拿不到 url）
  const previewMedia = usePrivateMediaUrl(
    preview?.mime_type.startsWith("image/") ||
      preview?.mime_type.startsWith("audio/") ||
      preview?.mime_type.startsWith("video/")
      ? previewEndpoint
      : null,
  );

  return (
    <div>
      <PageHeader
        title="素材库"
        description={total > 0 ? `共 ${total} 个素材` : "生成结果统一在此管理"}
        actions={
          <Button size="sm" onClick={() => fileRef.current?.click()}>
            <Plus className="h-4 w-4" aria-hidden />
            上传素材
          </Button>
        }
      >
        {FILTERS.map((f) => (
          <button
            key={f.v || "all"}
            type="button"
            onClick={() => {
              setMimePrefix(f.v);
              setPage(1);
            }}
            className={cn(
              "rounded-full border px-3 py-1 text-sm transition-colors",
              mimePrefix === f.v
                ? "border-primary bg-primary/12 font-semibold text-primary-text"
                : "border-border text-muted-foreground hover:border-primary",
            )}
          >
            {f.label}
          </button>
        ))}
      </PageHeader>
      <div className="flex gap-1 border-b">
        {(
          [
            ["assets", "素材"],
            ["photography", "写真摄影"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            className={`border-b-2 px-4 py-2 text-sm ${
              section === k ? "border-primary font-medium" : "border-transparent text-muted-foreground"
            }`}
            onClick={() => setSection(k)}
          >
            {label}
          </button>
        ))}
      </div>
      {section === "photography" && (
        <div className="flex flex-col items-center gap-3 p-10 text-center">
          <p className="text-sm text-muted-foreground">
            写真摄影已升级为独立页面（参考图集管理 / 风格参考出图）
          </p>
          <Button onClick={() => navigate("/photography")}>打开写真摄影页 →</Button>
        </div>
      )}
      <div className={section === "assets" ? "space-y-4 p-4 md:p-6" : "hidden"}>
        {/* 上传区域：拖拽或点击上传 */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-6 text-center transition-colors",
            dragOver
              ? "border-primary bg-primary/5 text-primary-text"
              : "border-border text-muted-foreground hover:border-primary hover:text-primary-text",
          )}
        >
          <Upload className="h-6 w-6" aria-hidden />
          <p className="text-sm">
            {uploadMutation.isPending
              ? `正在上传 ${Math.min(uploadDone + 1, uploadTotal)}/${uploadTotal} · ${uploadPercent}%`
              : "拖拽文件到此处，或点击选择文件"}
          </p>
          <p className="text-xs">支持图片 / 音频，单文件最大 20 MB</p>
          {uploadMutation.isPending && (
            <div className="h-1.5 w-48 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full bg-primary transition-all"
                style={{
                  width: `${((uploadDone + uploadPercent / 100) / Math.max(uploadTotal, 1)) * 100}%`,
                }}
              />
            </div>
          )}
          <input
            ref={fileRef}
            type="file"
            accept="image/*,audio/*,video/*"
            multiple
            className="hidden"
            onChange={(e) => handleUpload(e.target.files)}
          />
        </div>

        {uploadError && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {uploadError}
          </p>
        )}

        {uploadFailures.length > 0 && (
          <div className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-sm text-warning">
            <p className="font-medium">部分文件上传失败：</p>
            <ul className="mt-1 list-inside list-disc space-y-0.5">
              {uploadFailures.map((f) => (
                <li key={f} className="break-all font-mono text-xs">
                  {f}
                </li>
              ))}
            </ul>
          </div>
        )}

        {query.isPending ? (
          <GridSkeleton />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            title="素材库为空"
            description="可拖拽上传图片/音频，或生成任务完成后自动入库。"
            action={
              <Button size="sm" onClick={() => fileRef.current?.click()}>
                <Plus className="h-4 w-4" aria-hidden />
                上传素材
              </Button>
            }
          />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {items.map((asset) => (
                <Card
                  key={asset.id}
                  className={cn(
                    "group relative overflow-hidden",
                    highlight === asset.id && "ring-2 ring-primary",
                  )}
                >
                  <button
                    type="button"
                    className="block w-full text-left"
                    onClick={() => setPreview(asset)}
                  >
                    <AssetThumb asset={asset} />
                    <p className="truncate px-2 py-2 text-xs text-muted-foreground">
                      {asset.filename}
                    </p>
                    {asset.task_id && (
                      <p className="truncate px-2 pb-2 font-mono text-[10px] text-muted-foreground">
                        task {asset.task_id.slice(0, 8)}
                      </p>
                    )}
                  </button>
                  <div className="absolute right-2 top-2 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                    <button
                      type="button"
                      onClick={() => void downloadAsset(asset)}
                      aria-label="下载"
                      className="grid h-8 w-8 place-items-center rounded-lg border border-white/15 bg-black/55 text-white backdrop-blur hover:bg-black/70"
                    >
                      <Download className="h-4 w-4" aria-hidden />
                    </button>
                    <button
                      type="button"
                      onClick={() => setToDelete(asset)}
                      aria-label="删除"
                      className="grid h-8 w-8 place-items-center rounded-lg border border-white/15 bg-black/55 text-white backdrop-blur hover:bg-danger"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </button>
                  </div>
                </Card>
              ))}
            </div>

            {pages > 1 && (
              <div className="flex items-center justify-center gap-3 pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  <ChevronLeft className="h-4 w-4" aria-hidden />
                  上一页
                </Button>
                <span className="text-sm text-muted-foreground">
                  {page} / {pages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= pages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  下一页
                  <ChevronRight className="h-4 w-4" aria-hidden />
                </Button>
              </div>
            )}
          </>
        )}
      </div>

      {preview && (
        <Dialog open onClose={() => setPreview(null)} title={preview.filename}>
          <div className="space-y-3">
            {preview.mime_type.startsWith("image/") ? (
              previewMedia.url ? (
                <img
                  src={previewMedia.url}
                  alt={preview.filename}
                  className="max-h-[70dvh] w-full rounded-xl object-contain"
                  referrerPolicy="no-referrer"
                />
              ) : (
                <div className="h-48 animate-pulse rounded-xl bg-muted" />
              )
            ) : preview.mime_type.startsWith("audio/") ? (
              previewMedia.url ? (
                <audio controls src={previewMedia.url} className="w-full" />
              ) : (
                <div className="h-24 animate-pulse rounded-xl bg-muted" />
              )
            ) : preview.mime_type.startsWith("video/") ? (
              previewMedia.url ? (
                <video controls src={previewMedia.url} className="max-h-[70dvh] w-full rounded-xl" />
              ) : (
                <div className="h-48 animate-pulse rounded-xl bg-muted" />
              )
            ) : (
              <p className="text-sm text-muted-foreground">{preview.mime_type}</p>
            )}
            <p className="text-xs text-muted-foreground">
              {(preview.size_bytes / 1024).toFixed(1)} KB
              {preview.task_id ? ` · 任务 ${preview.task_id}` : ""}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => void downloadAsset(preview)}>
                <Download className="h-4 w-4" aria-hidden />
                下载
              </Button>
              {preview.mime_type.startsWith("image/") && (
                <Button
                  onClick={() =>
                    navigate("/create/image", {
                      state: {
                        reference_asset_id: preview.id,
                        reference_label: preview.filename,
                        prompt: "参考此素材的风格与构图，",
                      },
                    })
                  }
                >
                  <Sparkles className="h-4 w-4" aria-hidden />
                  用作参考出图
                </Button>
              )}
              {preview.task_id && (
                <Link
                  to="/tasks"
                  className="inline-flex h-10 items-center rounded-xl border border-border px-4 text-sm hover:border-primary"
                >
                  查看任务
                </Link>
              )}
              <Button
                variant="outline"
                className="text-danger"
                onClick={() => setToDelete(preview)}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
                删除
              </Button>
              <Button variant="ghost" onClick={() => setPreview(null)}>
                关闭
              </Button>
            </div>
          </div>
        </Dialog>
      )}

      <ConfirmDialog
        open={toDelete !== null}
        title="删除素材"
        description={`将删除「${toDelete?.filename ?? ""}」，此操作不可恢复。`}
        confirmText="删除"
        loading={deleteMutation.isPending}
        onConfirm={() => toDelete && deleteMutation.mutate(toDelete.id)}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}
