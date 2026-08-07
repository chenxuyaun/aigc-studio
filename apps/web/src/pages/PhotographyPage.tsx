import {
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Camera,
  ImagePlus,
  Plus,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";

import type { Paginated, Photo, PhotoAlbum } from "@aigc/shared-types";

import { PageHeader } from "@/components/layout/PageHeader";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Dialog } from "@/components/ui/Dialog";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { GallerySkeleton, GridSkeleton } from "@/components/ui/Skeleton";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { usePrivateMediaUrl } from "@/hooks/usePrivateMediaUrl";
import { AppError, apiClient } from "@/lib/apiClient";
import { cn } from "@/lib/cn";
import { useAuthStore } from "@/stores/auth";

/** 私有媒体图：经 access-url 换取可展示地址（local blob / R2 预签名）。 */
function AuthImage({
  accessEndpoint,
  alt,
  className,
}: {
  accessEndpoint?: string | null;
  alt: string;
  className?: string;
}) {
  const { url, loading } = usePrivateMediaUrl(accessEndpoint);
  if (!url) {
    return (
      <div
        className={cn("bg-muted", loading && "animate-pulse", className)}
        aria-hidden
      />
    );
  }
  return (
    <img
      src={url}
      alt={alt}
      className={className}
      loading="lazy"
      referrerPolicy="no-referrer"
    />
  );
}

function CreateAlbumDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [styleTags, setStyleTags] = useState("");
  const [isPublic, setIsPublic] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      apiClient.post<PhotoAlbum>("/photography/albums", {
        title: title.trim(),
        description: description.trim(),
        style_tags: styleTags.trim(),
        is_public: isPublic,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["photography", "albums"] });
      setTitle("");
      setDescription("");
      setStyleTags("");
      setIsPublic(true);
      setError(null);
      onClose();
    },
    onError: (err) => {
      setError(err instanceof AppError ? err.message : "创建失败");
    },
  });

  if (!open) return null;

  return (
    <Dialog open onClose={onClose} title="新建写真相册">
      <form
        className="space-y-4 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          if (!title.trim()) {
            setError("请填写相册名称");
            return;
          }
          mutation.mutate();
        }}
      >
        <Field label="相册名称" required>
          {({ id }) => (
            <Input
              id={id}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="例如：日系清新人像"
              maxLength={200}
            />
          )}
        </Field>
        <Field label="简介">
          {({ id }) => (
            <Textarea
              id={id}
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="风格说明、拍摄场景、适用提示词方向…"
            />
          )}
        </Field>
        <Field label="风格标签" hint="逗号分隔，例如：日系, 胶片, 人像">
          {({ id }) => (
            <Input
              id={id}
              value={styleTags}
              onChange={(e) => setStyleTags(e.target.value)}
              placeholder="日系, 胶片, 人像"
            />
          )}
        </Field>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input
            type="checkbox"
            checked={isPublic}
            onChange={(e) => setIsPublic(e.target.checked)}
            className="h-4 w-4 rounded border-border"
          />
          公开可见（其他登录用户可浏览）
        </label>
        {error && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button type="submit" loading={mutation.isPending}>
            创建
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function AlbumCard({
  album,
  onOpen,
}: {
  album: PhotoAlbum;
  onOpen: (id: string) => void;
}) {
  const tags = useMemo(
    () =>
      album.style_tags
        .split(/[,，]/)
        .map((t) => t.trim())
        .filter(Boolean)
        .slice(0, 3),
    [album.style_tags],
  );

  return (
    <button
      onClick={() => onOpen(album.id)}
      className="group overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface-raised text-left transition-all hover:-translate-y-0.5 hover:border-primary"
    >
      <div className="relative aspect-[4/3] bg-muted">
        {album.cover_photo_id || album.cover_access_url_endpoint || album.cover_url ? (
          <AuthImage
            accessEndpoint={
              album.cover_access_url_endpoint ??
              (album.cover_photo_id
                ? `/photography/photos/${album.cover_photo_id}/access-url`
                : null)
            }
            alt={album.title}
            className="h-full w-full object-cover transition-transform duration-200 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-muted-foreground">
            <Camera className="h-8 w-8" aria-hidden />
            <span className="text-xs">待上传封面</span>
          </div>
        )}
        <span className="absolute bottom-2 right-2 rounded-full bg-black/55 px-2 py-0.5 text-xs text-white backdrop-blur">
          {album.photo_count} 张
        </span>
      </div>
      <div className="space-y-1.5 p-3">
        <p className="line-clamp-1 text-sm font-semibold text-foreground">{album.title}</p>
        {album.description && (
          <p className="line-clamp-2 text-xs text-muted-foreground">{album.description}</p>
        )}
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1 pt-0.5">
            {tags.map((t) => (
              <span
                key={t}
                className="rounded-full bg-secondary px-2 py-0.5 text-[11px] text-secondary-foreground"
              >
                {t}
              </span>
            ))}
          </div>
        )}
      </div>
    </button>
  );
}

/** 写真摄影 — 相册列表 */
export function PhotographyPage() {
  const navigate = useNavigate();
  const [createOpen, setCreateOpen] = useState(false);
  const [mineOnly, setMineOnly] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  const query = useQuery({
    queryKey: ["photography", "albums", { mineOnly, search }],
    queryFn: () => {
      const params = new URLSearchParams({ page: "1", page_size: "48" });
      if (mineOnly) params.set("mine", "true");
      if (search) params.set("search", search);
      return apiClient.get<Paginated<PhotoAlbum>>(`/photography/albums?${params}`);
    },
  });

  return (
    <div>
      <PageHeader
        title="写真摄影"
        description="管理写真参考图集，后续可直接用于风格参考与生成"
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            新建相册
          </Button>
        }
      >
        <form
          className="relative max-w-sm flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            setSearch(searchInput.trim());
          }}
        >
          <Input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索相册名或风格标签…"
            aria-label="搜索相册"
          />
        </form>
        <Button
          variant={mineOnly ? "primary" : "outline"}
          size="sm"
          onClick={() => setMineOnly((v) => !v)}
        >
          {mineOnly ? "只看我的" : "全部相册"}
        </Button>
      </PageHeader>
      <div className="space-y-4 p-4 md:p-6">
        {query.isPending ? (
          <GridSkeleton />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : query.data.items.length === 0 ? (
          <EmptyState
            title={mineOnly || search ? "没有匹配的相册" : "还没有写真相册"}
            description="先建一个相册，再把参考图集上传进去。后续可接图生图 / 风格参考。"
            action={
              <Button onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4" aria-hidden />
                新建相册
              </Button>
            }
          />
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {query.data.items.map((album) => (
              <AlbumCard
                key={album.id}
                album={album}
                onOpen={(id) => navigate(`/photography/${id}`)}
              />
            ))}
          </div>
        )}
      </div>

      <CreateAlbumDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  );
}

/** 写真摄影 — 相册详情 + 上传 */
export function PhotographyAlbumPage() {
  const { albumId = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.user);
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [toDeletePhoto, setToDeletePhoto] = useState<Photo | null>(null);
  const [toDeleteAlbum, setToDeleteAlbum] = useState(false);
  const [preview, setPreview] = useState<Photo | null>(null);

  const albumQuery = useQuery({
    queryKey: ["photography", "album", albumId],
    queryFn: () => apiClient.get<PhotoAlbum>(`/photography/albums/${albumId}`),
    enabled: Boolean(albumId),
  });

  const photosQuery = useInfiniteQuery({
    queryKey: ["photography", "photos", albumId],
    queryFn: ({ pageParam }) =>
      apiClient.get<Paginated<Photo>>(
        `/photography/albums/${albumId}/photos?page=${pageParam}&page_size=48`,
      ),
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.page < last.pages ? last.page + 1 : undefined,
    enabled: Boolean(albumId),
  });

  const canEdit =
    Boolean(user) &&
    (user?.role === "admin" || user?.id === albumQuery.data?.owner_id);

  const uploadMutation = useMutation({
    mutationFn: async (files: FileList) => {
      const form = new FormData();
      Array.from(files).forEach((f) => form.append("files", f));
      return apiClient.postForm<Photo[]>(`/photography/albums/${albumId}/photos`, form);
    },
    onSuccess: () => {
      setUploadError(null);
      void qc.invalidateQueries({ queryKey: ["photography", "photos", albumId] });
      void qc.invalidateQueries({ queryKey: ["photography", "album", albumId] });
      void qc.invalidateQueries({ queryKey: ["photography", "albums"] });
    },
    onError: (err) => {
      setUploadError(err instanceof AppError ? err.message : "上传失败");
    },
  });

  const deletePhotoMutation = useMutation({
    mutationFn: (id: string) => apiClient.del(`/photography/photos/${id}`),
    onSuccess: () => {
      setToDeletePhoto(null);
      setPreview(null);
      void qc.invalidateQueries({ queryKey: ["photography", "photos", albumId] });
      void qc.invalidateQueries({ queryKey: ["photography", "album", albumId] });
      void qc.invalidateQueries({ queryKey: ["photography", "albums"] });
    },
  });

  const deleteAlbumMutation = useMutation({
    mutationFn: () => apiClient.del(`/photography/albums/${albumId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["photography", "albums"] });
      navigate("/photography", { replace: true });
    },
  });

  const setCoverMutation = useMutation({
    mutationFn: (photoId: string) =>
      apiClient.put<PhotoAlbum>(`/photography/albums/${albumId}`, {
        cover_photo_id: photoId,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["photography", "album", albumId] });
      void qc.invalidateQueries({ queryKey: ["photography", "albums"] });
    },
  });

  const [dragOver, setDragOver] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const batchDeleteMutation = useMutation({
    mutationFn: async (ids: string[]) => {
      for (const id of ids) {
        await apiClient.del(`/photography/photos/${id}`);
      }
    },
    onSuccess: () => {
      setSelected(new Set());
      setPreview(null);
      void qc.invalidateQueries({ queryKey: ["photography", "photos", albumId] });
      void qc.invalidateQueries({ queryKey: ["photography", "album", albumId] });
      void qc.invalidateQueries({ queryKey: ["photography", "albums"] });
    },
  });

  function enqueueFiles(list: FileList | File[]) {
    const arr = Array.from(list).filter((f) => f.type.startsWith("image/"));
    if (arr.length === 0) return;
    const dt = new DataTransfer();
    arr.slice(0, 30).forEach((f) => dt.items.add(f));
    uploadMutation.mutate(dt.files);
  }

  function onPickFiles(e: ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    enqueueFiles(files);
    e.target.value = "";
  }

  function onDropFiles(e: DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (!canEdit) return;
    if (e.dataTransfer.files?.length) enqueueFiles(e.dataTransfer.files);
  }

  if (albumQuery.isPending) {
    return (
      <div className="p-6">
        <GallerySkeleton />
      </div>
    );
  }
  if (albumQuery.isError || !albumQuery.data) {
    return (
      <div className="p-6">
        <ErrorState
          error={albumQuery.error ?? new Error("相册不存在")}
          onRetry={() => void albumQuery.refetch()}
        />
      </div>
    );
  }

  const album = albumQuery.data;
  const photos = photosQuery.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div>
      <PageHeader
        title={album.title}
        description={
          album.description ||
          (album.style_tags
            ? `风格：${album.style_tags}`
            : `共 ${album.photo_count} 张 · 可继续上传图集`)
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => navigate("/photography")}>
              <ArrowLeft className="h-4 w-4" aria-hidden />
              返回
            </Button>
            {canEdit && (
              <>
                <Button
                  size="sm"
                  onClick={() => fileRef.current?.click()}
                  loading={uploadMutation.isPending}
                >
                  <Upload className="h-4 w-4" aria-hidden />
                  上传图片
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setToDeleteAlbum(true)}
                  className="text-danger"
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                  删除相册
                </Button>
              </>
            )}
          </div>
        }
      />

      <input
        ref={fileRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif"
        multiple
        className="hidden"
        onChange={onPickFiles}
      />

      <div className="space-y-4 p-4 md:p-6">
        {uploadError && (
          <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger" role="alert">
            {uploadError}
          </p>
        )}

        {canEdit && (
          <Card
            className={cn(
              "flex flex-col items-start gap-3 border-dashed p-4 transition-colors sm:flex-row sm:items-center sm:justify-between",
              dragOver && "border-primary bg-primary/5",
            )}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDropFiles}
          >
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-primary/12 text-primary-text">
                <ImagePlus className="h-5 w-5" aria-hidden />
              </span>
              <div>
                <p className="text-sm font-medium">
                  {uploadMutation.isPending ? "正在上传…" : "拖拽或选择写真图集"}
                </p>
                <p className="text-xs text-muted-foreground">
                  支持 JPG / PNG / WebP / GIF，单张 ≤ 20MB，单次最多 30 张
                  {uploadMutation.isPending ? " · 上传中请勿关闭页面" : ""}
                </p>
              </div>
            </div>
            <Button onClick={() => fileRef.current?.click()} loading={uploadMutation.isPending}>
              <Upload className="h-4 w-4" aria-hidden />
              选择图片
            </Button>
          </Card>
        )}

        {canEdit && selected.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2">
            <span className="text-sm text-muted-foreground">已选 {selected.size} 张</span>
            <Button
              size="sm"
              variant="outline"
              className="text-danger"
              loading={batchDeleteMutation.isPending}
              onClick={() => batchDeleteMutation.mutate([...selected])}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
              批量删除
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
              取消选择
            </Button>
          </div>
        )}

        {photosQuery.isPending ? (
          <GallerySkeleton />
        ) : photosQuery.isError ? (
          <ErrorState error={photosQuery.error} onRetry={() => void photosQuery.refetch()} />
        ) : photos.length === 0 ? (
          <EmptyState
            title="相册还是空的"
            description={
              canEdit
                ? "把你的写真参考图上传进来，后续可直接作为风格参考。"
                : "作者还没有上传图片。"
            }
            action={
              canEdit ? (
                <Button onClick={() => fileRef.current?.click()}>
                  <Upload className="h-4 w-4" aria-hidden />
                  上传第一批
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <div className="columns-2 gap-3 sm:columns-3 lg:columns-4 xl:columns-5">
              {photos.map((photo) => (
                <figure
                key={photo.id}
                className="group relative mb-3 break-inside-avoid overflow-hidden rounded-xl border border-border bg-surface"
              >
                <button
                  className="block w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => setPreview(photo)}
                  aria-label={photo.caption || photo.filename}
                >
                  <AuthImage
                    accessEndpoint={
                      photo.access_url_endpoint ??
                      `/photography/photos/${photo.id}/access-url`
                    }
                    alt={photo.caption || photo.filename}
                    className="w-full bg-muted object-cover"
                  />
                </button>
                {canEdit && (
                  <div className="absolute right-2 top-2 flex flex-col gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleSelect(photo.id);
                      }}
                      aria-label={selected.has(photo.id) ? "取消选择" : "选择照片"}
                      className={cn(
                        "grid h-8 w-8 place-items-center rounded-lg border border-white/15 backdrop-blur",
                        selected.has(photo.id)
                          ? "bg-primary text-primary-foreground"
                          : "bg-black/55 text-white",
                      )}
                    >
                      {selected.has(photo.id) ? "✓" : "○"}
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setCoverMutation.mutate(photo.id);
                      }}
                      aria-label="设为封面"
                      title="设为封面"
                      className="grid h-8 w-8 place-items-center rounded-lg border border-white/15 bg-black/55 text-white backdrop-blur"
                    >
                      <Camera className="h-4 w-4" aria-hidden />
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setToDeletePhoto(photo);
                      }}
                      aria-label="删除照片"
                      className="grid h-8 w-8 place-items-center rounded-lg border border-white/15 bg-black/55 text-white backdrop-blur"
                    >
                      <Trash2 className="h-4 w-4" aria-hidden />
                    </button>
                  </div>
                )}
                {album.cover_photo_id === photo.id && (
                  <span className="absolute left-2 top-2 rounded-full bg-primary px-2 py-0.5 text-[10px] font-medium text-primary-foreground">
                    封面
                  </span>
                )}
                {photo.caption && (
                  <figcaption className="truncate px-2 py-1.5 text-xs text-muted-foreground">
                    {photo.caption}
                  </figcaption>
                )}
                </figure>
              ))}
            </div>
            {photosQuery.hasNextPage && (
              <div className="flex justify-center pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void photosQuery.fetchNextPage()}
                  loading={photosQuery.isFetchingNextPage}
                >
                  加载更多
                </Button>
              </div>
            )}
          </>
        )}
      </div>

      {preview && (
        <Dialog open onClose={() => setPreview(null)} title={preview.caption || preview.filename}>
          <div className="space-y-3 p-4">
            <AuthImage
              accessEndpoint={
                preview.access_url_endpoint ??
                `/photography/photos/${preview.id}/access-url`
              }
              alt={preview.caption || preview.filename}
              className="max-h-[70dvh] w-full rounded-xl object-contain"
            />
            <p className="text-xs text-muted-foreground">
              {preview.filename} · {(preview.size_bytes / 1024).toFixed(0)} KB
            </p>
            {canEdit && (
              <div className="flex flex-col gap-2 sm:flex-row">
                <Button
                  className="flex-1"
                  onClick={() =>
                    navigate("/create/image", {
                      state: {
                        reference_photo_id: preview.id,
                        reference_label: preview.caption || preview.filename,
                        width: preview.width > 0 ? preview.width : undefined,
                        height: preview.height > 0 ? preview.height : undefined,
                        prompt: preview.caption
                          ? `参考写真「${preview.caption}」的气质与构图，`
                          : "参考人物气质与构图，",
                      },
                    })
                  }
                >
                  <Sparkles className="h-4 w-4" aria-hidden />
                  用作参考出图
                </Button>
                <Button
                  variant="outline"
                  className="flex-1"
                  loading={setCoverMutation.isPending}
                  onClick={() => setCoverMutation.mutate(preview.id)}
                >
                  <Camera className="h-4 w-4" aria-hidden />
                  设为封面
                </Button>
                <Button
                  variant="outline"
                  className="flex-1 text-danger"
                  onClick={() => setToDeletePhoto(preview)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden />
                  删除
                </Button>
              </div>
            )}
            {!canEdit && (
              <Button
                className="w-full"
                onClick={() =>
                  navigate("/create/image", {
                    state: {
                      reference_photo_id: preview.id,
                      reference_label: preview.caption || preview.filename,
                      prompt: "参考人物气质与构图，",
                    },
                  })
                }
              >
                <Sparkles className="h-4 w-4" aria-hidden />
                用作参考出图
              </Button>
            )}
          </div>
        </Dialog>
      )}

      <ConfirmDialog
        open={toDeletePhoto !== null}
        title="删除照片"
        description={`将删除「${toDeletePhoto?.filename ?? ""}」，此操作不可恢复。`}
        confirmText="删除"
        loading={deletePhotoMutation.isPending}
        onConfirm={() => toDeletePhoto && deletePhotoMutation.mutate(toDeletePhoto.id)}
        onCancel={() => setToDeletePhoto(null)}
      />

      <ConfirmDialog
        open={toDeleteAlbum}
        title="删除相册"
        description={`将删除相册「${album.title}」及其中全部 ${album.photo_count} 张照片，此操作不可恢复。`}
        confirmText="删除相册"
        loading={deleteAlbumMutation.isPending}
        onConfirm={() => deleteAlbumMutation.mutate()}
        onCancel={() => setToDeleteAlbum(false)}
      />
    </div>
  );
}
