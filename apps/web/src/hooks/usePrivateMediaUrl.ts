import { useCallback, useEffect, useRef, useState } from "react";

import type { MediaAccess } from "@aigc/shared-types";

import { AppError, apiClient } from "@/lib/apiClient";
import { toClientApiPath } from "@/lib/paths";

function isBrowserDirectUrl(url: string): boolean {
  return (
    url.startsWith("http://") ||
    url.startsWith("https://") ||
    url.startsWith("blob:") ||
    url.startsWith("data:")
  );
}

/** 并发请求队列：限制同时进行的媒体请求数，避免触发限流。 */
class MediaRequestQueue {
  private queue: Array<() => void> = [];
  private active = 0;

  constructor(private maxConcurrent = 2) {}

  schedule<T>(task: () => Promise<T>): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const run = () => {
        this.active += 1;
        task().then(resolve, reject).finally(() => {
          this.active -= 1;
          const next = this.queue.shift();
          if (next) next();
        });
      };
      if (this.active < this.maxConcurrent) {
        run();
      } else {
        this.queue.push(run);
      }
    });
  }
}

const mediaQueue = new MediaRequestQueue(2);

/** access-url 短缓存：同页多缩略图/StrictMode 双挂载时复用，减少打点。
 *  容量上限 200（LRU 淘汰），登出时由 auth store 清空，避免跨账号残留。 */
const accessCache = new Map<string, { access: MediaAccess; until: number }>();
const ACCESS_CACHE_TTL_MS = 60_000;
const ACCESS_CACHE_MAX = 200;

export function clearMediaAccessCache(): void {
  accessCache.clear();
}

function getCachedAccess(key: string): MediaAccess | null {
  const hit = accessCache.get(key);
  if (!hit) return null;
  if (Date.now() > hit.until) {
    accessCache.delete(key);
    return null;
  }
  return hit.access;
}

function setCachedAccess(key: string, access: MediaAccess): void {
  const exp = Date.parse(access.expires_at);
  const until = Number.isNaN(exp)
    ? Date.now() + ACCESS_CACHE_TTL_MS
    : Math.min(Date.now() + ACCESS_CACHE_TTL_MS, exp - 5_000);
  accessCache.set(key, { access, until: Math.max(Date.now() + 5_000, until) });
  // LRU 上限：超出时删除最早插入的条目
  if (accessCache.size > ACCESS_CACHE_MAX) {
    const oldest = accessCache.keys().next().value;
    if (oldest !== undefined) accessCache.delete(oldest);
  }
}

/** 带退避的重试：遇到 429 等待后重试；上限 8s，加抖动避免齐步重试。 */
async function withRetry<T>(fn: () => Promise<T>, maxRetries = 4): Promise<T> {
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      const retryAfter =
        err instanceof AppError && "retryAfter" in err
          ? Number((err as AppError & { retryAfter?: number }).retryAfter)
          : undefined;
      if (err instanceof AppError && err.status === 429 && attempt < maxRetries) {
        const base = Number.isFinite(retryAfter) && retryAfter! > 0 ? retryAfter! : 2 ** attempt;
        const capped = Math.min(8, Math.max(1, base));
        const jitter = Math.random() * 0.4 * capped;
        await new Promise((r) => setTimeout(r, (capped + jitter) * 1000));
        continue;
      }
      throw err;
    }
  }
  throw new Error("unreachable");
}

/**
 * 私有媒体：请求 access-url，换取可展示地址。
 * local → 相对 /content，再 getBlob 成 object URL
 * r2   → 预签名绝对 URL，直接给 img
 */
export function usePrivateMediaUrl(accessEndpoint?: string | null) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(accessEndpoint));
  const [error, setError] = useState<string | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const genRef = useRef(0);

  const clearObjectUrl = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const load = useCallback(async () => {
    if (!accessEndpoint) {
      clearObjectUrl();
      setUrl(null);
      setError(null);
      setLoading(false);
      return;
    }

    const gen = ++genRef.current;
    setLoading(true);
    setError(null);
    clearTimer();

    const path = toClientApiPath(accessEndpoint);

    try {
      let access = getCachedAccess(path);
      if (!access) {
        access = await withRetry(() =>
          mediaQueue.schedule(() => apiClient.get<MediaAccess>(path)),
        );
        setCachedAccess(path, access);
      }
      if (gen !== genRef.current) return;

      let display = access.url;
      if (!isBrowserDirectUrl(display)) {
        const blob = await withRetry(() =>
          mediaQueue.schedule(() => apiClient.getBlob(toClientApiPath(display))),
        );
        if (gen !== genRef.current) return;
        clearObjectUrl();
        display = URL.createObjectURL(blob);
        objectUrlRef.current = display;
      } else {
        clearObjectUrl();
      }

      setUrl(display);
      setLoading(false);

      const expires = Date.parse(access.expires_at);
      if (!Number.isNaN(expires)) {
        const delay = Math.max(5_000, expires - Date.now() - 30_000);
        timerRef.current = setTimeout(() => {
          accessCache.delete(path);
          void load();
        }, delay);
      }
    } catch (err) {
      if (gen !== genRef.current) return;
      clearObjectUrl();
      setUrl(null);
      setLoading(false);
      setError(err instanceof AppError ? err.message : "媒体加载失败");
    }
  }, [accessEndpoint, clearObjectUrl, clearTimer]);

  useEffect(() => {
    void load();
    return () => {
      genRef.current += 1;
      clearTimer();
      clearObjectUrl();
    };
  }, [load, clearTimer, clearObjectUrl]);

  return { url, loading, error, refresh: load };
}
